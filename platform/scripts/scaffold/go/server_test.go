package main

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/xiant10/t10-modkit/module"
	"github.com/xiant10/t10-modkit/ontology"

	"github.com/jackc/pgx/v5/pgxpool"
)

// What every module answers is tested in t10-modkit's module package; these test this module's own.

var admin = module.Caller{TenantID: "ten_acme", UserID: "usr_1", TenantAdmin: true, Permissions: []string{}}

func serve(t *testing.T, method, path, token, body string) (int, map[string]any) {
	t.Helper()
	s := &Server{Module: module.Module{ID: moduleID, Service: service, Label: "__Id__", Sections: sections(),
		Access: module.Fake{Caller: admin, Actions: []string{readAction, moduleID + ":propose"}}, Ping: func(context.Context) error { return nil }, Tools: tools()}}
	newOntology(s, newNotes(true))
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	var out map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	return w.Code, out
}

func TestHome(t *testing.T) {
	if code, _ := serve(t, "GET", "/t/ten_acme/", "", ""); code != 303 {
		t.Errorf("home before sign-in: %d", code)
	}
	if code, _ := serve(t, "GET", "/t/ten_acme/", "person", ""); code != 200 {
		t.Errorf("home: %d", code)
	}
	if code, _ := serve(t, "GET", "/t/ten_other/", "person", ""); code != 403 {
		t.Errorf("another tenant's home: %d", code)
	}
}

func TestWhoami(t *testing.T) {
	call := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"__id___whoami","arguments":{}}}`
	code, body := serve(t, "POST", "/mcp", "agent", call)
	if result, _ := body["result"].(map[string]any); code != 200 || result["isError"] == true || !strings.Contains(fmtJSON(result), "ten_acme") {
		t.Errorf("whoami: %d %v", code, body)
	}
}

func TestOntology(t *testing.T) {
	if code, body := serve(t, "GET", "/v1/module", "person", ""); code != 200 || !strings.Contains(fmtJSON(body["features"]), "ontology") {
		t.Errorf("the manifest lists ontology: %d %v", code, body)
	}
	if code, body := serve(t, "GET", "/v1/ontology", "person", ""); code != 200 || body["module"] != moduleID {
		t.Errorf("descriptor: %d %v", code, body)
	}
	code, body := serve(t, "POST", "/v1/objects/note/search", "person", `{"filter":{"property":"state","op":"eq","value":"open"}}`)
	if objects, _ := body["objects"].([]any); code != 200 || len(objects) != 3 {
		t.Errorf("open notes: %d %v", code, body)
	}
	if code, _ := serve(t, "GET", "/v1/objects/note/n_welcome", "person:", ""); code != 404 {
		t.Errorf("a member without %s reads a note: %d", useAction, code)
	}
	if code, body := serve(t, "POST", "/v1/actions/note.archive/apply", "person", `{"object":"__id__:note:n_welcome","revision":1}`); code != 403 {
		t.Errorf("archiving another author's note: %d %v", code, body)
	}
	if code, body := serve(t, "POST", "/v1/actions/note.edit/apply", "person", `{"object":"__id__:note:n_archived","revision":1,"params":{"title":"x"}}`); code != 409 || body["error"] != "wrong_state" {
		t.Errorf("editing an archived note: %d %v", code, body)
	}
	if code, body := serve(t, "POST", "/v1/actions/note.edit/apply", "person", `{"object":"__id__:note:n_welcome","revision":1,"params":{"title":"Hello"}}`); code != 200 {
		t.Errorf("edit: %d %v", code, body)
	}
}

// A page starts after its cursor's sort value and ID, so a note edited between pages, which
// moves to the top, doesn't make the next page repeat the first.
func TestSearchPagesByCursor(t *testing.T) {
	ctx := context.Background()
	store := newNotes(true)
	newest := ontology.Query{Sort: ontology.Sort{Property: "updated_at", Desc: true}, Limit: 2}
	first, err := store.search(ctx, admin, newest)
	if err != nil || len(first) != 3 {
		t.Fatalf("first page: %v %v", first, err)
	}
	last := first[1]
	if err := store.update(admin, last.ID, last.Revision, func(n *note) { n.Title = "Edited" }); err != nil {
		t.Fatal(err)
	}
	newest.After = &ontology.Position{Value: last.Updated.Truncate(time.Second), ID: last.ID}
	next, err := store.search(ctx, admin, newest)
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range next {
		if r.ID == first[0].ID || r.ID == first[1].ID {
			t.Errorf("the next page repeats %s: %v", r.ID, next)
		}
	}
	if len(next) != 2 {
		t.Errorf("the next page: want the 2 older notes, have %v", next)
	}
}

// TestOntologyIsPinned keeps the pack's module/ontology.json, the core descriptor this module
// publishes, equal to the code. make check reads it for the grant actions the generated tools
// need. After a change to an object or action type, raise ontologyVersion when it removes,
// retypes or loosens anything, and write the copy again with UPDATE_ONTOLOGY=1 go test, so the
// change is a reviewed diff.
func TestOntologyIsPinned(t *testing.T) {
	s := &Server{Module: module.Module{ID: moduleID, Service: service}}
	newOntology(s, newNotes(false))
	got, err := json.MarshalIndent(s.Ontology.Core(), "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	got = append(got, '\n')
	if os.Getenv("UPDATE_ONTOLOGY") != "" {
		if err := os.WriteFile("module/ontology.json", got, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	pinned, err := os.ReadFile("module/ontology.json")
	if err != nil || string(pinned) != string(got) {
		t.Errorf("module/ontology.json isn't the ontology in the code: write it again with UPDATE_ONTOLOGY=1 (%v)", err)
	}
}

func TestAgentsDraftNotes(t *testing.T) {
	call := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"__id___propose","arguments":{"action":"note.create","params":{"title":"From the agent"}}}}`
	if code, body := serve(t, "POST", "/mcp", "agent", call); code != 200 || strings.Contains(fmtJSON(body), "isError") {
		t.Errorf("__id___propose: %d %v", code, body)
	}
	if code, _ := serve(t, "POST", "/v1/actions/note.create/apply", "agent", `{"params":{"title":"x"}}`); code != 401 {
		t.Errorf("an agent applies an action itself: %d", code)
	}
}

func TestEveryToolNeedsAnAction(t *testing.T) {
	for _, tl := range tools() {
		if !strings.HasPrefix(tl.Action, moduleID+":") {
			t.Errorf("%s: action %q isn't one of this module's", tl.Name, tl.Action)
		}
	}
}

// testDB is a Postgres of its own for a test that needs one: `make test` starts one and sets
// TEST_DATABASE_URL. Elsewhere the test skips, and `make test` counts the skips.
func testDB(t *testing.T) *pgxpool.Pool {
	t.Helper()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL isn't set (make test sets it)")
	}
	pool, err := pgxpool.New(context.Background(), url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func TestDatabaseAnswers(t *testing.T) {
	if err := testDB(t).Ping(context.Background()); err != nil {
		t.Fatal(err)
	}
}

func fmtJSON(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

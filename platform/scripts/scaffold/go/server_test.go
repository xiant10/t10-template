package main

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"t10kit/module"

	"github.com/jackc/pgx/v5/pgxpool"
)

// What every module answers is tested in the kit (kit/go/module); these test this module's own.

var admin = module.Caller{TenantID: "ten_acme", UserID: "usr_1", TenantAdmin: true, Permissions: []string{}}

func serve(t *testing.T, method, path, token, body string) (int, map[string]any) {
	t.Helper()
	s := &Server{Module: module.Module{ID: moduleID, Service: service, Label: "__Id__", Sections: sections(),
		Access: module.Fake{Caller: admin, Actions: []string{readAction}}, Ping: func(context.Context) error { return nil }, Tools: tools()}}
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

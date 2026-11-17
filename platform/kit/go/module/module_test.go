package module

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

var admin = Caller{TenantID: "ten_acme", UserID: "usr_1", TenantAdmin: true, Permissions: []string{}}

func testModule(access Access) *Module {
	return &Module{
		ID: "crm", Service: "t10-crm", Label: "CRM", PublicURL: "http://app.example", Access: access,
		Tools: []Tool{{
			Name: "crm_echo", Description: "Echo", Action: "crm:read", ReadOnly: true,
			Schema: Schema([]string{"text"}, map[string]any{"text": map[string]any{"type": "string"}}),
			Run: Args(func(_ context.Context, c Caller, a struct {
				Text string `json:"text"`
			}) (any, error) {
				return map[string]any{"text": a.Text, "tenant_id": c.TenantID}, nil
			}),
		}},
	}
}

func serve(t *testing.T, m *Module, method, path, token, body string, header ...string) (int, map[string]any) {
	t.Helper()
	mux := http.NewServeMux()
	m.Register(mux)
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	for i := 0; i+1 < len(header); i += 2 {
		req.Header.Set(header[i], header[i+1])
	}
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	var out map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	return w.Code, out
}

func call(name, args string) string {
	return `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"` + name + `","arguments":` + args + `}}`
}

func TestReadyNeedsAuthAndPing(t *testing.T) {
	if code, _ := serve(t, testModule(Fake{Caller: admin}), "GET", "/readyz", "", ""); code != 200 {
		t.Errorf("ready: %d", code)
	}
	if code, _ := serve(t, testModule(Fake{Down: true}), "GET", "/readyz", "", ""); code != 503 {
		t.Errorf("ready with auth down: %d", code)
	}
	m := testModule(Fake{Caller: admin})
	m.Ping = func(context.Context) error { return ErrUnavailable }
	if code, body := serve(t, m, "GET", "/readyz", "", ""); code != 503 || body["error"] != "database_unavailable" {
		t.Errorf("ready with the database down: %d %v", code, body)
	}
}

func TestManifestAndAccess(t *testing.T) {
	m := testModule(Fake{Caller: admin})
	if code, _ := serve(t, m, "GET", "/v1/module", "", ""); code != 401 {
		t.Errorf("manifest without a token: %d", code)
	}
	if code, _ := serve(t, m, "GET", "/v1/module", "agent", ""); code != 403 {
		t.Errorf("manifest for an agent: %d", code)
	}
	code, body := serve(t, m, "GET", "/v1/module", "person", "")
	if code != 200 || body["action_prefix"] != "crm" {
		t.Errorf("manifest: %d %v", code, body)
	}
	code, body = serve(t, m, "GET", "/v1/access", "person", "")
	if code != 200 || body["tenant_admin"] != true {
		t.Errorf("access: %d %v", code, body)
	}
}

func TestToolsListWithoutToken(t *testing.T) {
	code, body := serve(t, testModule(Fake{}), "POST", "/mcp", "", `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`)
	listed, _ := body["result"].(map[string]any)["tools"].([]any)
	if code != 200 || len(listed) != 1 {
		t.Fatalf("tools/list: %d %v", code, body)
	}
}

func TestToolCallNeedsAnAgent(t *testing.T) {
	m := testModule(Fake{Caller: admin, Actions: []string{"crm:read"}})
	c := call("crm_echo", `{"text":"hi"}`)
	if code, _ := serve(t, m, "POST", "/mcp", "", c); code != 401 {
		t.Errorf("without a token: %d", code)
	}
	if code, _ := serve(t, m, "POST", "/mcp", "person", c); code != 403 {
		t.Errorf("a person's own token: %d", code)
	}
	if code, _ := serve(t, m, "POST", "/mcp", "agent", c, "Origin", "http://evil.example"); code != 403 {
		t.Errorf("from a page: %d", code)
	}
	code, body := serve(t, m, "POST", "/mcp", "agent", c)
	result, _ := body["result"].(map[string]any)
	if code != 200 || result["isError"] == true || !strings.Contains(fmtJSON(result), "ten_acme") {
		t.Errorf("tool call: %d %v", code, body)
	}
	if code, _ := serve(t, testModule(Fake{Caller: admin, Actions: []string{"crm:write"}}), "POST", "/mcp", "agent", c); code != 403 {
		t.Errorf("an agent without the tool's action: %d", code)
	}
}

func TestUnknownToolNeedsAnAgentFirst(t *testing.T) {
	m := testModule(Fake{Caller: admin})
	if code, _ := serve(t, m, "POST", "/mcp", "person", call("crm_nothing", "{}")); code != 403 {
		t.Errorf("a person asking for an unknown tool: %d", code)
	}
	_, body := serve(t, m, "POST", "/mcp", "agent", call("crm_nothing", "{}"))
	if body["error"] == nil {
		t.Errorf("an unknown tool: %v", body)
	}
}

func TestToolArgumentsAreChecked(t *testing.T) {
	_, body := serve(t, testModule(Fake{Caller: admin}), "POST", "/mcp", "agent", call("crm_echo", `{"surprise":1}`))
	if result, _ := body["result"].(map[string]any); result["isError"] != true {
		t.Errorf("unknown argument accepted: %v", body)
	}
}

func fmtJSON(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

func TestStandaloneOnlyAlone(t *testing.T) {
	dir := t.TempDir()
	_ = os.MkdirAll(filepath.Join(dir, "permissions"), 0o755)
	_ = os.WriteFile(filepath.Join(dir, "permissions", "crm.yaml"), []byte(`{"agent": {"actions": ["crm:read"]}}`), 0o644)
	t.Setenv("T10_PACK_DIR", dir)
	t.Setenv("T10_STANDALONE", "1")
	t.Setenv("AUTH_ISSUER", "")
	access, err := NewAccess("crm", "t10-crm")
	if err != nil {
		t.Fatal(err)
	}
	if code, _ := serve(t, testModule(access), "GET", "/v1/access", "person", ""); code != 200 {
		t.Errorf("standalone person: %d", code)
	}
	if _, err := access.Agent(context.Background(), "Bearer agent", "crm:write"); err == nil {
		t.Error("standalone agent used an action the catalog doesn't grant")
	}
	c, err := access.Person(context.Background(), "Bearer person:crm:read,crm:write")
	if err != nil || c.TenantAdmin || len(c.Permissions) != 2 || c.Permissions[0] != "crm:read" {
		t.Errorf("standalone member with permissions: %v %+v", err, c)
	}
	t.Setenv("AUTH_ISSUER", "http://auth.example")
	if _, err := NewAccess("crm", "t10-crm"); err == nil {
		t.Error("standalone mode started beside AUTH_ISSUER")
	}
}

func TestWebLoginAndSessionCookie(t *testing.T) {
	t.Setenv("T10_STANDALONE", "1")
	t.Setenv("AUTH_ISSUER", "")
	m := testModule(Fake{Caller: admin})
	mux := http.NewServeMux()
	m.Register(mux)
	mux.HandleFunc("POST /v1/item", func(w http.ResponseWriter, r *http.Request) {
		if c, ok := m.Person(w, r); ok {
			Reply(w, 200, map[string]any{"user_id": c.UserID, "tenant_admin": c.TenantAdmin, "permissions": c.Permissions})
		}
	})

	req := httptest.NewRequest("GET", "/auth/login?next=/dashboard&permissions=crm:read", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != http.StatusSeeOther || w.Header().Get("Location") != "/dashboard" {
		t.Fatalf("login redirect: %d %s", w.Code, w.Header().Get("Location"))
	}
	cookies := w.Result().Cookies()
	if len(cookies) != 1 || cookies[0].Name != "crm_session" {
		t.Fatalf("expected crm_session cookie, got %v", cookies)
	}

	req = httptest.NewRequest("GET", "/v1/access", nil)
	req.AddCookie(cookies[0])
	w = httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	var body map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	if w.Code != 200 || body["tenant_admin"] != false {
		t.Fatalf("session access: %d %v", w.Code, body)
	}

	// Cross-site POST with a session cookie is refused.
	req = httptest.NewRequest("POST", "/v1/item", strings.NewReader("{}"))
	req.AddCookie(cookies[0])
	req.Header.Set("Origin", "http://evil.example")
	w = httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != 403 {
		t.Errorf("cross-origin POST with session cookie: %d", w.Code)
	}

	// Same-origin POST succeeds.
	req = httptest.NewRequest("POST", "/v1/item", strings.NewReader("{}"))
	req.AddCookie(cookies[0])
	req.Header.Set("Origin", "http://app.example")
	w = httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Errorf("same-origin POST with session cookie: %d", w.Code)
	}
}

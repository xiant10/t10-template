package main

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

// fakeAccess stands in for auth-server: "Bearer person" is a person, "Bearer agent" an agent
// allowed readAction, anything else is refused.
type fakeAccess struct{ down bool }

var admin = Caller{TenantID: "ten_acme", UserID: "usr_1", TenantAdmin: true, Permissions: []string{}}

func (f fakeAccess) Ready(context.Context) error {
	if f.down {
		return ErrUnavailable
	}
	return nil
}

func (f fakeAccess) Person(_ context.Context, header string) (Caller, error) {
	switch header {
	case "Bearer person":
		return admin, nil
	case "":
		return Caller{}, ErrUnauthorized
	}
	return Caller{}, ErrForbidden
}

func (f fakeAccess) Agent(_ context.Context, header, action string) (Caller, error) {
	switch {
	case header == "Bearer agent" && action == readAction:
		return admin, nil
	case header == "":
		return Caller{}, ErrUnauthorized
	}
	return Caller{}, ErrForbidden
}

func serve(t *testing.T, access fakeAccess, method, path, token, body string, header ...string) (int, map[string]any) {
	t.Helper()
	s := &Server{Access: access, Ping: func(context.Context) error { return nil }, PublicURL: "http://app.example"}
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	for i := 0; i+1 < len(header); i += 2 {
		req.Header.Set(header[i], header[i+1])
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	var out map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	return w.Code, out
}

func TestReadyNeedsAuth(t *testing.T) {
	if code, _ := serve(t, fakeAccess{}, "GET", "/readyz", "", ""); code != 200 {
		t.Errorf("ready: %d", code)
	}
	if code, _ := serve(t, fakeAccess{down: true}, "GET", "/readyz", "", ""); code != 503 {
		t.Errorf("ready with auth down: %d", code)
	}
}

func TestManifestAndAccess(t *testing.T) {
	if code, _ := serve(t, fakeAccess{}, "GET", "/v1/module", "", ""); code != 401 {
		t.Errorf("manifest without a token: %d", code)
	}
	if code, _ := serve(t, fakeAccess{}, "GET", "/v1/module", "agent", ""); code != 403 {
		t.Errorf("manifest for an agent: %d", code)
	}
	code, body := serve(t, fakeAccess{}, "GET", "/v1/module", "person", "")
	if code != 200 || body["action_prefix"] != moduleID {
		t.Errorf("manifest: %d %v", code, body)
	}
	code, body = serve(t, fakeAccess{}, "GET", "/v1/access", "person", "")
	if code != 200 || body["tenant_admin"] != true {
		t.Errorf("access: %d %v", code, body)
	}
}

func TestToolsListWithoutToken(t *testing.T) {
	code, body := serve(t, fakeAccess{}, "POST", "/mcp", "", `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`)
	listed, _ := body["result"].(map[string]any)["tools"].([]any)
	if code != 200 || len(listed) != len(tools()) {
		t.Fatalf("tools/list: %d %v", code, body)
	}
}

func TestToolCallNeedsAnAgent(t *testing.T) {
	call := `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"` + tools()[0].name + `","arguments":{}}}`
	if code, _ := serve(t, fakeAccess{}, "POST", "/mcp", "", call); code != 401 {
		t.Errorf("without a token: %d", code)
	}
	if code, _ := serve(t, fakeAccess{}, "POST", "/mcp", "person", call); code != 403 {
		t.Errorf("a person's own token: %d", code)
	}
	if code, _ := serve(t, fakeAccess{}, "POST", "/mcp", "agent", call, "Origin", "http://evil.example"); code != 403 {
		t.Errorf("from a page: %d", code)
	}
	code, body := serve(t, fakeAccess{}, "POST", "/mcp", "agent", call)
	result, _ := body["result"].(map[string]any)
	if code != 200 || result["isError"] == true || !strings.Contains(fmtJSON(result), "ten_acme") {
		t.Errorf("tool call: %d %v", code, body)
	}
}

func TestToolArgumentsAreChecked(t *testing.T) {
	call := `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"` + tools()[0].name + `","arguments":{"surprise":1}}}`
	_, body := serve(t, fakeAccess{}, "POST", "/mcp", "agent", call)
	if result, _ := body["result"].(map[string]any); result["isError"] != true {
		t.Errorf("unknown argument accepted: %v", body)
	}
}

func TestEveryToolNeedsAnAction(t *testing.T) {
	for _, tl := range tools() {
		if tl.action == "" || !strings.HasPrefix(tl.action, moduleID+":") {
			t.Errorf("%s: action %q isn't one of this module's", tl.name, tl.action)
		}
	}
}

func fmtJSON(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

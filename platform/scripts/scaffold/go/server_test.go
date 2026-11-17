package main

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"

	"t10kit/module"
)

// What every module answers is tested in the kit (kit/go/module); these test this module's own.

var admin = module.Caller{TenantID: "ten_acme", UserID: "usr_1", TenantAdmin: true, Permissions: []string{}}

func serve(t *testing.T, method, path, token, body string) (int, map[string]any) {
	t.Helper()
	s := &Server{Module: module.Module{ID: moduleID, Service: service, Label: "__Id__",
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
	if code, _ := serve(t, "GET", "/", "", ""); code != 200 {
		t.Errorf("home: %d", code)
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

func fmtJSON(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

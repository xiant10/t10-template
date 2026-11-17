package module

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

// fakeAuth is auth-server's person-facing API, as a module's web app calls it. It records each
// call's body by path.
func fakeAuth(t *testing.T) (*httptest.Server, map[string]string) {
	t.Helper()
	got := map[string]string{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer tok" {
			w.WriteHeader(401)
			return
		}
		body, _ := io.ReadAll(r.Body)
		got[r.Method+" "+r.URL.Path] = string(body)
		switch r.Method + " " + r.URL.Path {
		case "POST /v1/me/browser-logout":
			Reply(w, 200, map[string]string{"ticket": "tkt"})
		case "GET /v1/me/preferences":
			Reply(w, 200, map[string]string{"language": "zh-Hans", "theme": "dark"})
		case "PUT /v1/me/preferences":
			Reply(w, 200, map[string]string{})
		case "GET /v1/me":
			Reply(w, 200, map[string]string{"display_name": "Ada"})
		case "GET /v1/me/homes":
			Reply(w, 200, map[string]any{"account": map[string]string{"url": "http://auth.example/v1/account"},
				"workbench": map[string]any{"tenants": []map[string]any{{"id": "ten_acme", "name": "Acme", "url": "http://wb/t/ten_acme/",
					"apps": []map[string]string{{"id": "crm", "label": "CRM", "url": "http://app.example/t/ten_acme/"}}}}}})
		default:
			w.WriteHeader(404)
		}
	}))
	t.Cleanup(srv.Close)
	return srv, got
}

// withSession is a request carrying the module's session cookie for token.
func withSession(t *testing.T, m *Module, method, path, token string) *http.Request {
	t.Helper()
	w := httptest.NewRecorder()
	if err := m.setSessionCookie(w, token, 600); err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(method, path, nil)
	req.AddCookie(w.Result().Cookies()[0])
	return req
}

func webMux(m *Module) *http.ServeMux {
	mux := http.NewServeMux()
	m.Register(mux)
	mux.HandleFunc("GET /t/{tenant}/{$}", func(w http.ResponseWriter, r *http.Request) {
		if c, ok := m.PersonPage(w, r); ok {
			m.Page(w, r, m.View(r, c), Page{Title: "Home", Section: "home", Body: "<p>hello</p>"})
		}
	})
	return mux
}

func do(mux http.Handler, req *http.Request) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	return w
}

func TestLoginGoesToAuthorize(t *testing.T) {
	t.Setenv("T10_STANDALONE", "")
	t.Setenv("AUTH_ISSUER", "http://auth.example")
	w := do(webMux(testModule(Fake{Caller: admin})), httptest.NewRequest("GET", "/auth/login?next=/t/ten_acme/&tenant=ten_acme", nil))
	loc, _ := url.Parse(w.Header().Get("Location"))
	q := loc.Query()
	if w.Code != 303 || loc.Host != "auth.example" || loc.Path != "/v1/authorize" || q.Get("client_id") != "t10-crm-web" ||
		q.Get("tenant") != "ten_acme" || q.Get("redirect_uri") != "http://app.example/auth/callback" {
		t.Errorf("login: %d %s", w.Code, loc)
	}
}

func TestPersonPageSignsInFirst(t *testing.T) {
	t.Setenv("T10_STANDALONE", "1")
	t.Setenv("AUTH_ISSUER", "")
	m := testModule(Fake{Caller: admin})
	mux := webMux(m)

	w := do(mux, httptest.NewRequest("GET", "/t/ten_acme/", nil))
	if w.Code != 303 || w.Header().Get("Location") != "/auth/login?next=%2Ft%2Ften_acme%2F&tenant=ten_acme" {
		t.Errorf("not signed in: %d %s", w.Code, w.Header().Get("Location"))
	}
	if w := do(mux, withSession(t, m, "GET", "/t/ten_acme/", "person")); w.Code != 200 || !strings.Contains(w.Body.String(), "<p>hello</p>") {
		t.Errorf("signed in: %d", w.Code)
	}
	// A session that has ended signs in again.
	if w := do(mux, withSession(t, m, "GET", "/t/ten_acme/", "")); w.Code != 303 {
		t.Errorf("ended session: %d", w.Code)
	}
	// An API caller is answered, not redirected.
	req := httptest.NewRequest("GET", "/t/ten_other/", nil)
	req.Header.Set("Authorization", "Bearer person")
	if w := do(mux, req); w.Code != 403 {
		t.Errorf("bearer for another tenant: %d", w.Code)
	}
}

func TestPersonPageSwitchesTenantOnce(t *testing.T) {
	t.Setenv("T10_STANDALONE", "1")
	t.Setenv("AUTH_ISSUER", "")
	m := testModule(Fake{Caller: admin})
	mux := webMux(m)
	w := do(mux, withSession(t, m, "GET", "/t/ten_other/", "person"))
	if w.Code != 303 || !strings.Contains(w.Header().Get("Location"), "tenant=ten_other") {
		t.Fatalf("other tenant: %d %s", w.Code, w.Header().Get("Location"))
	}
	req := withSession(t, m, "GET", "/t/ten_other/", "person")
	req.AddCookie(w.Result().Cookies()[0])
	if w := do(mux, req); w.Code != 403 {
		t.Errorf("other tenant again: %d", w.Code)
	}
}

func TestLogoutEndsTheSignIn(t *testing.T) {
	auth, got := fakeAuth(t)
	t.Setenv("T10_STANDALONE", "")
	t.Setenv("AUTH_ISSUER", "http://auth.example")
	t.Setenv("AUTH_URL", auth.URL)
	m := testModule(Fake{Caller: admin})
	mux := webMux(m)

	w := do(mux, withSession(t, m, "POST", "/auth/logout", "tok"))
	if w.Code != 303 || w.Header().Get("Location") != "http://auth.example/v1/signout/complete?ticket=tkt" {
		t.Errorf("logout: %d %s", w.Code, w.Header().Get("Location"))
	}
	if c := w.Result().Cookies(); len(c) != 1 || c[0].Name != "crm_session" || c[0].MaxAge != -1 {
		t.Errorf("logout keeps the session: %v", c)
	}
	var asked map[string]string
	_ = json.Unmarshal([]byte(got["POST /v1/me/browser-logout"]), &asked)
	if asked["client_id"] != "t10-crm-web" || asked["return_to"] != "http://app.example/signed-out" {
		t.Errorf("ticket asked for %v", asked)
	}
	// No session left to ask for a ticket: auth-server's own page.
	if w := do(mux, httptest.NewRequest("POST", "/auth/logout", nil)); w.Header().Get("Location") != "http://auth.example/v1/signout" {
		t.Errorf("logout without a session: %s", w.Header().Get("Location"))
	}
	auth.Close()
	if w := do(mux, withSession(t, m, "POST", "/auth/logout", "tok")); w.Header().Get("Location") != "/signed-out?reason=incomplete" {
		t.Errorf("logout with auth-server down: %s", w.Header().Get("Location"))
	}
	if w := do(mux, httptest.NewRequest("GET", "/signed-out?reason=incomplete", nil)); w.Code != 200 || !strings.Contains(w.Body.String(), "signed out") {
		t.Errorf("signed-out page: %d", w.Code)
	}
}

func TestPageWearsTheFrame(t *testing.T) {
	auth, got := fakeAuth(t)
	t.Setenv("T10_STANDALONE", "")
	t.Setenv("AUTH_ISSUER", "http://auth.example")
	t.Setenv("AUTH_URL", auth.URL)
	m := testModule(Fake{Caller: admin})
	m.LabelZH = "客户"
	m.Sections = []Section{
		{Key: "home", Label: "Home", LabelZH: "首页"},
		{Key: "setup", To: "setup", Label: "Setup", Group: "setup", Allowed: func(c Caller) bool { return c.TenantAdmin }},
	}
	mux := webMux(m)
	req := withSession(t, m, "GET", "/t/ten_acme/", "tok")
	m.Access = fakeToken{admin}
	w := do(mux, req)
	page := w.Body.String()
	for _, want := range []string{`data-theme="dark"`, "首页", `href="/t/ten_acme/setup"`, "Ada", "退出登录", `action="/frame/theme"`, "return_to="} {
		if !strings.Contains(page, want) {
			t.Errorf("page lacks %q", want)
		}
	}

	req = withSession(t, m, "POST", "/frame/theme", "tok")
	req.Body = io.NopCloser(strings.NewReader("theme=light&next=/t/ten_acme/"))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	if w := do(mux, req); w.Code != 303 || w.Header().Get("Location") != "/t/ten_acme/" || got["PUT /v1/me/preferences"] != "{\"theme\":\"light\"}" {
		t.Errorf("theme: %d %s %q", w.Code, w.Header().Get("Location"), got["PUT /v1/me/preferences"])
	}
}

// fakeToken accepts the token fakeAuth does as c.
type fakeToken struct{ c Caller }

func (f fakeToken) Ready(context.Context) error { return nil }
func (f fakeToken) Person(_ context.Context, h string) (Caller, error) {
	if h != "Bearer tok" {
		return Caller{}, ErrUnauthorized
	}
	return f.c, nil
}
func (f fakeToken) Agent(context.Context, string, string) (Caller, error) {
	return Caller{}, ErrForbidden
}

type notes struct{ read []string }

func (n *notes) Notifications(_ context.Context, c Caller, cursor string, limit int) ([]Notification, string, error) {
	x := Notification{ID: "n1", To: "tasks/1", Title: c.UserID}
	x.Event.Kind = "task.assigned"
	return []Notification{x}, "c2", nil
}

func (n *notes) MarkRead(_ context.Context, _ Caller, ids []string) error {
	n.read = ids
	return nil
}

func TestNotificationsAndNav(t *testing.T) {
	m := testModule(Fake{Caller: admin})
	code, body := serve(t, m, "GET", "/v1/notifications?limit=200&after=c1", "person", "")
	if list, _ := body["notifications"].([]any); code != 200 || list == nil || len(list) != 0 || body["cursor"] != "c1" {
		t.Errorf("no notifier: %d %v", code, body)
	}
	if code, _ := serve(t, m, "POST", "/v1/notifications/read", "person", `{"ids":["n1"]}`); code != 204 {
		t.Errorf("read without a notifier: %d", code)
	}
	n := &notes{}
	m.Notifier = n
	code, body = serve(t, m, "GET", "/v1/notifications", "person", "")
	if list, _ := body["notifications"].([]any); code != 200 || len(list) != 1 || body["cursor"] != "c2" || !strings.Contains(fmtJSON(list[0]), `"read_at":null`) {
		t.Errorf("notifier: %d %v", code, body)
	}
	if code, _ := serve(t, m, "POST", "/v1/notifications/read", "person", `{"ids":["n1"]}`); code != 204 || len(n.read) != 1 {
		t.Errorf("read: %d %v", code, n.read)
	}

	m.Sections = []Section{{Key: "home", Label: "Home"}, {Key: "setup", To: "setup", Label: "Setup", Group: "setup", Allowed: func(c Caller) bool { return c.TenantAdmin }}}
	code, body = serve(t, m, "GET", "/v1/me/nav", "person:crm:read", "")
	if code != 200 || fmtJSON(body["sections"]) != `[{"group":"daily","key":"home","label":"Home","label_zh":"Home","to":""}]` {
		t.Errorf("nav for a member: %d %v", code, fmtJSON(body))
	}
	_, body = serve(t, m, "GET", "/v1/module", "person", "")
	if app, _ := body["app"].(map[string]any); app["label_zh"] != "CRM" || len(app["nav"].([]any)) != 2 {
		t.Errorf("manifest app: %v", body["app"])
	}
}

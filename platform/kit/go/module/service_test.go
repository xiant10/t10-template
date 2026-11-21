package module

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
)

// orgAuth is auth-server's token and org API: two pages of members, and their units.
func orgAuth(t *testing.T, tokens *int) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reply := func(v any) { _ = json.NewEncoder(w).Encode(v) }
		if r.URL.Path != "/v1/token" && r.Header.Get("Authorization") != "Bearer svc-token" {
			w.WriteHeader(401)
			return
		}
		switch {
		case r.URL.Path == "/v1/token":
			*tokens++
			reply(map[string]any{"access_token": "svc-token", "expires_in": 300})
		case r.URL.Path == "/v1/org/members" && r.URL.Query().Get("tenant") == "ten_acme" && r.URL.Query().Get("cursor") == "":
			reply(map[string]any{"members": []map[string]string{
				{"user_id": "usr_1", "display_name": "Ann", "kind": "user", "org_unit_id": "ou_sales"},
				{"user_id": "usr_bot", "kind": "agent"},
			}, "next_cursor": "p2"})
		case r.URL.Path == "/v1/org/members" && r.URL.Query().Get("cursor") == "p2":
			reply(map[string]any{"members": []map[string]string{{"user_id": "usr_2", "display_name": "Bo", "kind": "user"}}})
		case r.URL.Path == "/v1/org/units":
			reply(map[string]any{"units": []map[string]string{{"id": "ou_sales", "name": "Sales"}}})
		default:
			w.WriteHeader(404)
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestMembersWithTheServiceToken(t *testing.T) {
	tokens := 0
	srv := orgAuth(t, &tokens)
	a := &Auth{Module: "crm", Service: "t10-crm", URL: srv.URL, Secret: "s", HTTP: srv.Client()}
	got, err := a.Members(context.Background(), "ten_acme")
	if err != nil {
		t.Fatal(err)
	}
	want := []Member{
		{UserID: "usr_1", Name: "Ann", Kind: "user", Unit: "Sales"},
		{UserID: "usr_bot", Name: "usr_bot", Kind: "agent"},
		{UserID: "usr_2", Name: "Bo", Kind: "user"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("members: %+v", got)
	}
	if tok, err := a.ServiceToken(context.Background()); err != nil || tok != "svc-token" || tokens != 1 {
		t.Errorf("service token %q, %v, fetched %d times", tok, err, tokens)
	}
}

func TestFakeIsAService(t *testing.T) {
	var access Access = Fake{Caller: admin}
	svc, ok := access.(Service)
	if !ok {
		t.Fatal("Fake isn't a Service")
	}
	if m, err := svc.Members(context.Background(), "ten_acme"); err != nil || len(m) != 1 || m[0].UserID != "usr_1" {
		t.Errorf("members: %+v, %v", m, err)
	}
	if m, _ := svc.Members(context.Background(), "ten_other"); len(m) != 0 {
		t.Errorf("another tenant's members: %+v", m)
	}
	if _, err := (Fake{Down: true}).ServiceToken(context.Background()); err != ErrUnavailable {
		t.Errorf("down: %v", err)
	}
	var _ Service = (*Auth)(nil)
}

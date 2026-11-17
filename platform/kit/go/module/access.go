package module

import (
	"bytes"
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"t10kit/verifier"
)

var (
	ErrUnauthorized = errors.New("unauthorized")
	ErrForbidden    = errors.New("forbidden")
	ErrUnavailable  = errors.New("authorization unavailable")
)

// Caller is the person a request is for, with their live standing in this module. An agent
// calling a tool gets no rights of its own: it acts as this person.
type Caller struct {
	TenantID, UserID string
	TenantAdmin      bool
	// Permissions are this module's permissions the person holds, such as crm:admin.
	Permissions []string
}

// Access checks who a request is for. Auth is the real one; tests use Fake.
type Access interface {
	Ready(ctx context.Context) error
	// Person accepts only a person's own token, from a browser or app.
	Person(ctx context.Context, header string) (Caller, error)
	// Agent accepts only a delegated token whose whole grant chain allows action.
	Agent(ctx context.Context, header, action string) (Caller, error)
}

// Auth checks tokens offline with the verifier, then reads the person's standing from
// auth-server on every request, so a removed member loses access at once.
type Auth struct {
	// Module is the MODULE_ID, whose permissions Caller holds; Service is its auth-server account.
	Module, Service string
	URL, Secret     string
	HTTP            *http.Client
	Verifier        *verifier.Verifier

	mu           sync.Mutex
	serviceTok   string
	serviceUntil time.Time
}

// NewAuth is Auth for the module's service, from the settings the project's standard wiring
// gives every module: AUTH_ISSUER, AUTH_URL and AUTH_CLIENT_SECRET.
func NewAuth(module, service string) (*Auth, error) {
	issuer, secret := os.Getenv("AUTH_ISSUER"), os.Getenv("AUTH_CLIENT_SECRET")
	authURL := cmp.Or(os.Getenv("AUTH_URL"), issuer)
	client := &http.Client{Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	v, err := verifier.New(verifier.Config{Issuer: issuer, URL: authURL, Service: service, ClientSecret: secret, HTTPClient: client})
	if err != nil {
		return nil, err
	}
	return &Auth{Module: module, Service: service, URL: authURL, Secret: secret, HTTP: client, Verifier: v}, nil
}

func bearer(header string) (string, bool) {
	parts := strings.Fields(header)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
		return "", false
	}
	return parts[1], true
}

func (a *Auth) Person(ctx context.Context, header string) (Caller, error) {
	token, ok := bearer(header)
	if !ok {
		return Caller{}, ErrUnauthorized
	}
	who, err := a.Verifier.Verify(ctx, token)
	if err != nil {
		return Caller{}, ErrUnauthorized
	}
	if who.UserID == "" || who.TenantID == "" || who.ServiceID != "" || who.Agent != nil {
		return Caller{}, ErrForbidden
	}
	// The session must still be live, not only the token unexpired.
	var live struct {
		UserID string `json:"user_id"`
		Tenant string `json:"active_tenant"`
	}
	if err := a.request(ctx, "GET", "/v1/me/access", token, nil, &live); err != nil {
		return Caller{}, err
	}
	if live.UserID != who.UserID || live.Tenant != who.TenantID {
		return Caller{}, ErrForbidden
	}
	return a.entitled(ctx, who.TenantID, who.UserID)
}

func (a *Auth) Agent(ctx context.Context, header, action string) (Caller, error) {
	token, ok := bearer(header)
	if !ok {
		return Caller{}, ErrUnauthorized
	}
	who, err := a.Verifier.Verify(ctx, token)
	if errors.Is(err, verifier.ErrGrantUnavailable) {
		return Caller{}, ErrUnavailable
	}
	if err != nil {
		return Caller{}, ErrUnauthorized
	}
	if who.UserID == "" || who.TenantID == "" || who.Agent == nil || !who.Allows(action) {
		return Caller{}, ErrForbidden
	}
	// A module defines no grant constraints, so a grant that sets one is refused rather
	// than ignored.
	for _, raw := range who.Constraints() {
		if c := string(bytes.TrimSpace(raw)); c != "" && c != "null" && c != "{}" {
			return Caller{}, ErrForbidden
		}
	}
	return a.entitled(ctx, who.TenantID, who.UserID)
}

// Ready gets this service's own token and verifies it, so /readyz fails until auth-server
// knows this service and serves its keys.
func (a *Auth) Ready(ctx context.Context) error {
	token, err := a.serviceToken(ctx)
	if err != nil {
		return err
	}
	if who, err := a.Verifier.Verify(ctx, token); err != nil || who.ServiceID == "" {
		return ErrUnavailable
	}
	return nil
}

// entitled is one person's live status and grants in this module. Nothing is cached.
func (a *Auth) entitled(ctx context.Context, tenant, user string) (Caller, error) {
	token, err := a.serviceToken(ctx)
	if err != nil {
		return Caller{}, err
	}
	var e struct {
		Tenant string `json:"tenant_id"`
		Status string `json:"tenant_status"`
		Module string `json:"module"`
		Users  []struct {
			ID         string `json:"user_id"`
			Active     bool   `json:"active"`
			Account    string `json:"account_status"`
			Membership string `json:"membership_status"`
			Admin      bool   `json:"tenant_admin"`
			Grants     []struct {
				Permission string `json:"permission"`
			} `json:"grants"`
		} `json:"users"`
	}
	q := url.Values{"tenant": {tenant}, "user": {user}, "module": {a.Module}}
	if err := a.request(ctx, "GET", "/v1/entitlements?"+q.Encode(), token, nil, &e); err != nil {
		return Caller{}, ErrUnavailable
	}
	if e.Tenant != tenant || e.Module != a.Module || len(e.Users) != 1 || e.Users[0].ID != user {
		return Caller{}, ErrUnavailable
	}
	u := e.Users[0]
	if e.Status != "active" || !u.Active || u.Account != "active" || u.Membership != "active" {
		return Caller{}, ErrForbidden
	}
	c := Caller{TenantID: tenant, UserID: user, TenantAdmin: u.Admin, Permissions: []string{}}
	for _, g := range u.Grants {
		if strings.HasPrefix(g.Permission, a.Module+":") {
			c.Permissions = append(c.Permissions, g.Permission)
		}
	}
	return c, nil
}

func (a *Auth) serviceToken(ctx context.Context) (string, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.serviceTok != "" && time.Until(a.serviceUntil) > 30*time.Second {
		return a.serviceTok, nil
	}
	var out struct {
		Token     string `json:"access_token"`
		ExpiresIn int    `json:"expires_in"`
	}
	body := map[string]string{"grant_type": "client_credentials", "client_id": a.Service, "client_secret": a.Secret}
	if err := a.request(ctx, "POST", "/v1/token", "", body, &out); err != nil || out.Token == "" {
		return "", ErrUnavailable
	}
	ttl := cmp.Or(out.ExpiresIn, 300)
	a.serviceTok = out.Token
	a.serviceUntil = time.Now().Add(time.Duration(ttl) * time.Second)
	return out.Token, nil
}

func (a *Auth) request(ctx context.Context, method, path, token string, body, out any) error {
	var b bytes.Buffer
	if body != nil {
		if err := json.NewEncoder(&b).Encode(body); err != nil {
			return ErrUnavailable
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, a.URL+path, &b)
	if err != nil {
		return ErrUnavailable
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	req.Header.Set("Content-Type", "application/json")
	res, err := a.HTTP.Do(req)
	if err != nil {
		return ErrUnavailable
	}
	defer res.Body.Close()
	switch res.StatusCode {
	case 200:
	case 401:
		return ErrUnauthorized
	case 403:
		return ErrForbidden
	default:
		return ErrUnavailable
	}
	if json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(out) != nil {
		return ErrUnavailable
	}
	return nil
}

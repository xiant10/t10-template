package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"

	"__service__/verifier"
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
	// Permissions are this module's permissions the person holds, such as __id__:admin.
	Permissions []string
}

// Access checks who a request is for. Auth is the real one; tests use their own.
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
	URL, Secret string
	HTTP        *http.Client
	Verifier    *verifier.Verifier
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
	// This module defines no grant constraints, so a grant that sets one is refused rather
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
	q := url.Values{"tenant": {tenant}, "user": {user}, "module": {moduleID}}
	if err := a.request(ctx, "GET", "/v1/entitlements?"+q.Encode(), token, nil, &e); err != nil {
		return Caller{}, ErrUnavailable
	}
	if e.Tenant != tenant || e.Module != moduleID || len(e.Users) != 1 || e.Users[0].ID != user {
		return Caller{}, ErrUnavailable
	}
	u := e.Users[0]
	if e.Status != "active" || !u.Active || u.Account != "active" || u.Membership != "active" {
		return Caller{}, ErrForbidden
	}
	c := Caller{TenantID: tenant, UserID: user, TenantAdmin: u.Admin, Permissions: []string{}}
	for _, g := range u.Grants {
		if strings.HasPrefix(g.Permission, moduleID+":") {
			c.Permissions = append(c.Permissions, g.Permission)
		}
	}
	return c, nil
}

func (a *Auth) serviceToken(ctx context.Context) (string, error) {
	var out struct {
		Token string `json:"access_token"`
	}
	body := map[string]string{"grant_type": "client_credentials", "client_id": service, "client_secret": a.Secret}
	if err := a.request(ctx, "POST", "/v1/token", "", body, &out); err != nil || out.Token == "" {
		return "", ErrUnavailable
	}
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

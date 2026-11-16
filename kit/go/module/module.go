// Package module is what every business module's service answers, so a module's own code is
// only its tools and its web app: /readyz, /v1/module (the manifest workbench reads),
// /v1/access, and its tools at /mcp, with a person's token and an agent's delegated token
// checked against auth-server (docs/module.md in the project).
//
// It's the template's (kit/go/), shared by every module whose code is in the project, so a fix
// here reaches each of them with `make template-update`.
package module

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"
)

// Module is one module's service: who it is, how it checks callers, and its tools.
type Module struct {
	// ID is the MODULE_ID, the prefix of its actions; Service is its Compose service and account.
	ID, Service string
	// Label is its name in workbench; PublicURL its web app's address.
	Label, PublicURL string
	Access           Access
	// Ping reports whether what it needs, such as its database, answers; nil means nothing.
	Ping  func(context.Context) error
	Tools []Tool
}

// Register adds the routes every module answers to mux. The module adds its own beside them.
func (m *Module) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { Reply(w, 200, map[string]string{"status": "ok"}) })
	mux.HandleFunc("GET /readyz", m.ready)
	mux.HandleFunc("GET /v1/module", m.manifest)
	mux.HandleFunc("GET /v1/access", m.access)
	mux.HandleFunc("POST /mcp", m.mcp)
}

func (m *Module) ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if m.Ping != nil && m.Ping(ctx) != nil {
		Reply(w, 503, map[string]string{"error": "database_unavailable"})
		return
	}
	if m.Access.Ready(ctx) != nil {
		Reply(w, 503, map[string]string{"error": "authorization_unavailable"})
		return
	}
	Reply(w, 200, map[string]string{"status": "ready"})
}

// manifest is what workbench reads to show the module.
func (m *Module) manifest(w http.ResponseWriter, r *http.Request) {
	if _, ok := m.Person(w, r); !ok {
		return
	}
	Reply(w, 200, map[string]any{
		"id": m.ID, "api_version": 1, "action_prefix": m.ID, "enabled": true,
		"app": map[string]any{"url": m.PublicURL, "label": m.Label},
	})
}

// access tells a signed-in person what they may do here.
func (m *Module) access(w http.ResponseWriter, r *http.Request) {
	c, ok := m.Person(w, r)
	if !ok {
		return
	}
	Reply(w, 200, map[string]any{"tenant_id": c.TenantID, "user_id": c.UserID, "tenant_admin": c.TenantAdmin, "permissions": c.Permissions})
}

// Person is the signed-in person a request is for, or false after answering 401, 403 or 503.
// A module's own API uses it the same way.
func (m *Module) Person(w http.ResponseWriter, r *http.Request) (Caller, bool) {
	c, err := m.Access.Person(r.Context(), r.Header.Get("Authorization"))
	if err != nil {
		Refuse(w, err)
		return Caller{}, false
	}
	return c, true
}

// Refuse answers an Access error: 401, 403, or 503 when access couldn't be checked.
func Refuse(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrUnauthorized):
		w.Header().Set("WWW-Authenticate", "Bearer")
		Reply(w, 401, map[string]string{"error": "unauthorized"})
	case errors.Is(err, ErrForbidden):
		Reply(w, 403, map[string]string{"error": "forbidden"})
	default:
		Reply(w, 503, map[string]string{"error": "authorization_unavailable"})
	}
}

// Reply answers with v as JSON, never cached.
func Reply(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

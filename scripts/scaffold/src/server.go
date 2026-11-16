package main

import (
	"context"
	"encoding/json"
	"errors"
	"html/template"
	"net/http"
	"time"
)

// Server is the module's HTTP API. Access and Ping are interfaces so tests can run it
// without auth-server or a database.
type Server struct {
	Access    Access
	Ping      func(context.Context) error
	PublicURL string
}

func (s *Server) Handler() http.Handler {
	m := http.NewServeMux()
	m.HandleFunc("GET /{$}", s.home)
	m.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { reply(w, 200, map[string]string{"status": "ok"}) })
	m.HandleFunc("GET /readyz", s.ready)
	m.HandleFunc("GET /v1/module", s.manifest)
	m.HandleFunc("GET /v1/access", s.access)
	m.HandleFunc("POST /mcp", s.mcp)
	return m
}

var homePage = template.Must(template.New("home").Parse(`<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{.}}</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem}</style>
<h1>{{.}}</h1>
<p>This module is running. Its web app goes here.</p>
`))

// home is the module's web app, a placeholder until it has one. Signing people in here uses
// its web client (module/clients.fragment.json) with AUTH_WEB_CLIENT_SECRET.
func (s *Server) home(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_ = homePage.Execute(w, "__Id__")
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if s.Ping(ctx) != nil {
		reply(w, 503, map[string]string{"error": "database_unavailable"})
		return
	}
	if s.Access.Ready(ctx) != nil {
		reply(w, 503, map[string]string{"error": "authorization_unavailable"})
		return
	}
	reply(w, 200, map[string]string{"status": "ready"})
}

// manifest is what workbench reads to show the module.
func (s *Server) manifest(w http.ResponseWriter, r *http.Request) {
	if _, ok := s.person(w, r); !ok {
		return
	}
	reply(w, 200, map[string]any{
		"id": moduleID, "api_version": 1, "action_prefix": moduleID, "enabled": true,
		"app": map[string]any{"url": s.PublicURL, "label": "__Id__"},
	})
}

// access tells a signed-in person what they may do here.
func (s *Server) access(w http.ResponseWriter, r *http.Request) {
	c, ok := s.person(w, r)
	if !ok {
		return
	}
	reply(w, 200, map[string]any{"tenant_id": c.TenantID, "user_id": c.UserID, "tenant_admin": c.TenantAdmin, "permissions": c.Permissions})
}

func (s *Server) person(w http.ResponseWriter, r *http.Request) (Caller, bool) {
	c, err := s.Access.Person(r.Context(), r.Header.Get("Authorization"))
	if err != nil {
		refuse(w, err)
		return Caller{}, false
	}
	return c, true
}

func refuse(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrUnauthorized):
		w.Header().Set("WWW-Authenticate", "Bearer")
		reply(w, 401, map[string]string{"error": "unauthorized"})
	case errors.Is(err, ErrForbidden):
		reply(w, 403, map[string]string{"error": "forbidden"})
	default:
		reply(w, 503, map[string]string{"error": "authorization_unavailable"})
	}
}

func reply(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

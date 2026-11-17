package main

import (
	"html/template"
	"net/http"

	"t10kit/module"
)

// Server is the module's HTTP API: what every module answers, from module.Module, and its own
// routes. Access and Ping are in Module, so tests run it without auth-server or a database.
type Server struct {
	module.Module
}

func (s *Server) Handler() http.Handler {
	m := http.NewServeMux()
	s.Register(m)
	m.HandleFunc("GET /{$}", s.home)
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
// its web client (module/clients.fragment.json) with AUTH_WEB_CLIENT_SECRET; an API of its own
// checks the person with s.Person, as /v1/access does.
func (s *Server) home(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_ = homePage.Execute(w, s.Label)
}

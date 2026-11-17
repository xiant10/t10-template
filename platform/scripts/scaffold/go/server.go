package main

import (
	"html/template"
	"net/http"
	"net/url"
	"strings"

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
	m.HandleFunc("GET /{$}", s.root)
	m.HandleFunc("GET /t/{tenant}/{$}", s.home)
	return m
}

// sections are the web app's pages, under /t/<tenant>/, in the rail and in Workbench's menu.
// Add one here with its route in Handler; Allowed hides one from people who can't use it.
func sections() []module.Section {
	return []module.Section{
		{Key: "home", To: "", Label: "Home", LabelZH: "首页",
			Icon: `<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>`},
	}
}

var homeBody = template.Must(template.New("home").Parse(`<div class="card">
<p>{{.T "This module is running. Its web app goes here." "模块已运行，这里将是它的网页应用。"}}</p>
<p class="mut">{{.T "Tenant" "租户"}} {{.TenantID}}{{if .TenantAdmin}} · {{.T "administrator" "管理员"}}{{end}}</p>
</div>`))

// root is where the app's bare address goes: its home in the tenant the person is signed in to.
func (s *Server) root(w http.ResponseWriter, r *http.Request) {
	c, ok := s.PersonPage(w, r)
	if !ok {
		return
	}
	http.Redirect(w, r, "/t/"+url.PathEscape(c.TenantID)+"/", http.StatusSeeOther)
}

// home is the web app's first page, a placeholder until it has one. Workbench and auth-server's
// Apps list open the app at /t/<tenant>/. PersonPage sends a browser that isn't signed in to
// sign-in and back, and one signed in to another tenant to this one; s.Page draws the page in
// the frame every t10 app wears.
func (s *Server) home(w http.ResponseWriter, r *http.Request) {
	c, ok := s.PersonPage(w, r)
	if !ok {
		return
	}
	v := s.View(r, c)
	var body template.HTML
	if b, err := execute(homeBody, v); err == nil {
		body = b
	}
	s.Page(w, r, v, module.Page{Title: s.Label, Section: "home", Body: body})
}

func execute(t *template.Template, data any) (template.HTML, error) {
	var b strings.Builder
	if err := t.Execute(&b, data); err != nil {
		return "", err
	}
	return template.HTML(b.String()), nil // #nosec G203 -- html/template escaped it
}

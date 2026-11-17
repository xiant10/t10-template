package module

import (
	"bytes"
	"cmp"
	_ "embed"
	"encoding/json"
	"html/template"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"

	"t10kit/frame"
)

// A module's web app drawn on the server, in the frame every t10 app wears (t10kit/frame):
// the rail with its own sections, the same Apps list as Workbench, and the account menu with
// language, theme, Account and Sign out. Language and theme are the person's, saved with
// auth-server, so they match whatever they chose in any other app.
//
// An app's pages are under /t/<tenant>/: Workbench and auth-server's Apps list open it there,
// and each Section's To is a path under it. Register mounts what the frame needs:
// GET /v1/me/nav (this person's sections, which Workbench's menu shows too), POST
// /frame/language and /frame/theme (the account menu), and GET /signed-out.

// Styles is Workbench's tokens (workbench web/src/kit/app.css), light and dark, and its base
// elements: headings, links, .card, .rows and .item, buttons (.primary), inputs, .notice and
// .error, .mut. Page includes it; a page of a module's own can too.
//
//go:embed page.css
var Styles string

// Section is one page of a module's web app, as its rail and Workbench's menu show it. Its JSON
// is Workbench's NavSection.
type Section struct {
	// Key names it; Page.Section marks the current one.
	Key string
	// To is its path under /t/<tenant>/: "" for the app's home.
	To string
	// LabelZH is its name in Chinese; Label when empty.
	Label, LabelZH string
	// Group is "daily" (the default, with no heading), "records" or "setup".
	Group string
	// Icon is what goes inside a 24×24 stroked <svg>, such as a Lucide icon's paths; a
	// generic one when empty.
	Icon template.HTML
	// Allowed says whether this person may open it; nil is everyone signed in.
	Allowed func(Caller) bool
}

func (s Section) MarshalJSON() ([]byte, error) {
	type wire struct {
		Key     string `json:"key"`
		To      string `json:"to"`
		Label   string `json:"label"`
		LabelZH string `json:"label_zh"`
		Group   string `json:"group"`
	}
	return json.Marshal(wire{Key: s.Key, To: s.To, Label: s.Label, LabelZH: cmp.Or(s.LabelZH, s.Label), Group: cmp.Or(s.Group, "daily")})
}

// sectionsFor are the sections this person may open, in order.
func (m *Module) sectionsFor(c Caller) []Section {
	out := []Section{}
	for _, s := range m.Sections {
		if s.Allowed == nil || s.Allowed(c) {
			out = append(out, s)
		}
	}
	return out
}

func (m *Module) nav(w http.ResponseWriter, r *http.Request) {
	c, ok := m.Person(w, r)
	if !ok {
		return
	}
	Reply(w, 200, map[string]any{"sections": m.sectionsFor(c)})
}

// Page is one page of a module's web app, drawn inside the frame.
type Page struct {
	Title string
	// Section is the Key of the section it belongs to, marked in the rail.
	Section string
	// Notice and Error, when set, show above the body.
	Notice, Error string
	Body          template.HTML
}

// View is what a page is drawn for: the person, in their language and theme, with the places
// they can go. View reads it from auth-server as the person; auth-server being slow or down
// costs the Apps list and the saved choices, never the page.
type View struct {
	Caller
	// Lang is "en" or "zh-Hans"; Theme is "system", "light" or "dark".
	Lang, Theme string
	// Name is what the person is called: their display name, or else their user ID.
	Name  string
	homes frame.Homes
}

// Zh is whether the page is in Chinese.
func (v View) Zh() bool { return v.Lang == "zh-Hans" }

// T is the English text, or its Chinese when the page is in Chinese.
func (v View) T(en, zh string) string {
	if v.Zh() && zh != "" {
		return zh
	}
	return en
}

// View is the view of a page for c, who PersonPage or Person has let in.
func (m *Module) View(r *http.Request, c Caller) View {
	v := View{Caller: c, Lang: acceptedLang(r.Header.Get("Accept-Language")), Theme: "system", Name: c.UserID}
	token := m.Token(r)
	if token == "" || os.Getenv("AUTH_ISSUER") == "" {
		return v
	}
	var prefs struct {
		Language string `json:"language"`
		Theme    string `json:"theme"`
	}
	var me struct {
		DisplayName string `json:"display_name"`
	}
	var wg sync.WaitGroup
	wg.Go(func() { _, _ = callAuth(r.Context(), http.MethodGet, "/v1/me/preferences", token, nil, &prefs) })
	wg.Go(func() { _, _ = callAuth(r.Context(), http.MethodGet, "/v1/me/homes", token, nil, &v.homes) })
	wg.Go(func() { _, _ = callAuth(r.Context(), http.MethodGet, "/v1/me", token, nil, &me) })
	wg.Wait()
	if validLang(prefs.Language) {
		v.Lang = prefs.Language
	}
	if frame.ValidTheme(prefs.Theme) {
		v.Theme = prefs.Theme
	}
	v.Name = cmp.Or(strings.TrimSpace(me.DisplayName), v.Name)
	return v
}

// acceptedLang is Chinese when the browser prefers it to English, as auth-server decides.
func acceptedLang(header string) string {
	for part := range strings.SplitSeq(header, ",") {
		tag, _, _ := strings.Cut(part, ";")
		tag = strings.ToLower(strings.TrimSpace(tag))
		if tag == "zh" || strings.HasPrefix(tag, "zh-") {
			return "zh-Hans"
		}
		if tag == "en" || strings.HasPrefix(tag, "en-") {
			return "en"
		}
	}
	return "en"
}

// frameZh is the frame's words in Chinese, as Workbench and auth-server say them.
var frameZh = map[string]string{
	"Apps": "应用", "Workbench": "工作台", "Platform console": "平台控制台", "Account": "账户",
	"Language": "语言", "Theme": "主题", "System": "跟随系统", "Light": "浅色", "Dark": "深色",
	"Sign out": "退出登录", "Records": "档案", "Setup": "设置",
	"You're signed out": "你已退出登录", "Sign in again": "重新登录",
	"This app's session has ended, but sign-in couldn't be reached to end the others. Sign out there too.": "本应用已退出，但无法连接登录服务来退出其他应用。请在那里再退出一次。",
}

func translator(zh bool) func(string) string {
	return func(text string) string {
		if t, ok := frameZh[text]; ok && zh {
			return t
		}
		return text
	}
}

type railLink struct {
	Key, Label, Href string
	Icon             template.HTML
}

type railGroup struct {
	Label string
	Links []railLink
}

type pageData struct {
	Page
	View
	App, Home, Theme string
	Groups           []railGroup
	Places           []frame.Place
	Menu             frame.Menu
}

// Page draws p for v: the frame, with the module's sections this person may open, around the
// page's body.
func (m *Module) Page(w http.ResponseWriter, r *http.Request, v View, p Page) {
	t := translator(v.Zh())
	base := "/t/" + url.PathEscape(v.TenantID) + "/"
	d := pageData{Page: p, View: v, App: v.T(m.Label, m.LabelZH), Home: base, Theme: v.Theme}
	for _, g := range []string{"daily", "records", "setup"} {
		group := railGroup{}
		if g != "daily" {
			group.Label = t(strings.ToUpper(g[:1]) + g[1:])
		}
		for _, s := range m.sectionsFor(v.Caller) {
			if cmp.Or(s.Group, "daily") == g {
				group.Links = append(group.Links, railLink{Key: s.Key, Label: v.T(s.Label, s.LabelZH), Href: base + strings.TrimLeft(s.To, "/"), Icon: s.Icon})
			}
		}
		if len(group.Links) > 0 {
			d.Groups = append(d.Groups, group)
		}
	}
	d.Places = frame.Places(v.homes, v.TenantID, m.ID, v.Zh())
	detail := v.TenantID
	if v.homes.Workbench != nil {
		for _, tn := range v.homes.Workbench.Tenants {
			if tn.ID == v.TenantID && tn.Name != "" {
				detail = tn.Name
			}
		}
	}
	here := safeNext(r.URL.RequestURI())
	account := ""
	if issuer := strings.TrimRight(os.Getenv("AUTH_ISSUER"), "/"); issuer != "" {
		account = frame.AccountLink(cmp.Or(v.homes.Account.URL, issuer+"/v1/account"), strings.TrimRight(m.PublicURL, "/")+here)
	}
	d.Menu = frame.Menu{
		Name: v.Name, Detail: detail, Lang: v.Lang, Theme: v.Theme, Here: here,
		LanguageAction: "/frame/language", ThemeAction: "/frame/theme", AccountURL: account,
		SignOutAction: "/auth/logout",
	}
	m.draw(w, http.StatusOK, "page", v.Zh(), d)
}

// signedOut is where auth-server returns the browser after signing it out of every app.
func (m *Module) signedOut(w http.ResponseWriter, r *http.Request) {
	zh := acceptedLang(r.Header.Get("Accept-Language")) == "zh-Hans"
	m.draw(w, http.StatusOK, "signed-out", zh, map[string]any{
		"App": m.Label, "Zh": zh, "Incomplete": r.URL.Query().Get("reason") == "incomplete",
		"Issuer": strings.TrimRight(os.Getenv("AUTH_ISSUER"), "/"),
	})
}

// savePreference saves a language or theme chosen in the account menu with auth-server, which
// keeps it for every app, and comes back to the page.
func (m *Module) savePreference(field string, valid func(string) bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if _, ok := m.Person(w, r); !ok { // a session's form must come from this site
			return
		}
		value := r.FormValue(field)
		if token := m.Token(r); valid(value) && token != "" && os.Getenv("AUTH_ISSUER") != "" {
			key := map[string]string{"lang": "language", "theme": "theme"}[field]
			if _, err := callAuth(r.Context(), http.MethodPut, "/v1/me/preferences", token, map[string]string{key: value}, nil); err != nil {
				log.Printf("saving %s: %v", key, err)
			}
		}
		http.Redirect(w, r, safeNext(r.FormValue("next")), http.StatusSeeOther)
	}
}

func validLang(lang string) bool { return lang == "en" || lang == "zh-Hans" }

//go:embed page.html
var pageHTML string

var pageTemplates = template.Must(template.New("").Funcs(template.FuncMap{
	"t":        func(text string) string { return text },
	"styles":   func() template.CSS { return template.CSS(Styles) },
	"frameCSS": func() template.CSS { return template.CSS(frame.CSS) },
}).Parse(pageHTML + frame.Templates))

func (m *Module) draw(w http.ResponseWriter, status int, name string, zh bool, data any) {
	tpl := template.Must(pageTemplates.Clone()).Funcs(template.FuncMap{"t": translator(zh)})
	var buf bytes.Buffer
	if err := tpl.ExecuteTemplate(&buf, name, data); err != nil {
		log.Printf("drawing %s: %v", name, err)
		http.Error(w, "page unavailable", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_, _ = buf.WriteTo(w)
}

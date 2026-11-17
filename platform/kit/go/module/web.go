package module

import (
	"bytes"
	"cmp"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// Web sign-in and encrypted session cookies for a module with `web` in CAPABILITIES.
//
// The template's standard wiring gives every web module AUTH_ISSUER, AUTH_URL,
// AUTH_WEB_CLIENT_SECRET, <ID>_PUBLIC_URL and <ID>_SESSION_KEY, and registers <Service>-web in
// clients.yaml with redirect_uris ["${<ID>_PUBLIC_URL}/auth/callback"]. Register mounts
// GET /auth/login, GET /auth/callback, POST /auth/logout and GET /signed-out; Person accepts
// either an Authorization: Bearer header or the session cookie, and PersonPage sends a browser
// that isn't signed in to sign-in instead of answering 401. In standalone mode
// (T10_STANDALONE=1), GET /auth/login signs in as the standalone person immediately.

func (m *Module) sessionCookieName() string { return m.ID + "_session" }
func (m *Module) oauthCookieName() string   { return m.ID + "_oauth" }

func (m *Module) sessionKey() []byte {
	envKey := strings.ToUpper(strings.ReplaceAll(m.ID, "-", "_")) + "_SESSION_KEY"
	raw := os.Getenv(envKey)
	if decoded, err := base64.StdEncoding.DecodeString(raw); err == nil && len(decoded) == 32 {
		return decoded
	}
	sum := sha256.Sum256([]byte(raw + ":" + os.Getenv("AUTH_WEB_CLIENT_SECRET") + ":" + m.ID + ":t10kit-session"))
	return sum[:]
}

func (m *Module) seal(plain string) (string, error) {
	block, err := aes.NewCipher(m.sessionKey())
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}
	sealed := gcm.Seal(nonce, nonce, []byte(plain), []byte(m.ID))
	return base64.RawURLEncoding.EncodeToString(sealed), nil
}

func (m *Module) open(encoded string) (string, bool) {
	raw, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		return "", false
	}
	block, err := aes.NewCipher(m.sessionKey())
	if err != nil {
		return "", false
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil || len(raw) < gcm.NonceSize() {
		return "", false
	}
	nonce, ciphertext := raw[:gcm.NonceSize()], raw[gcm.NonceSize():]
	plain, err := gcm.Open(nil, nonce, ciphertext, []byte(m.ID))
	if err != nil {
		return "", false
	}
	return string(plain), true
}

func (m *Module) secureCookie() bool {
	return strings.HasPrefix(m.PublicURL, "https://")
}

func safeNext(next string) string {
	if strings.HasPrefix(next, "/") && !strings.HasPrefix(next, "//") && !strings.ContainsAny(next, "\r\n\\") {
		return next
	}
	return "/"
}

func randomToken(size int) string {
	b := make([]byte, size)
	_, _ = io.ReadFull(rand.Reader, b)
	return base64.RawURLEncoding.EncodeToString(b)
}

func (m *Module) sameOrigin(r *http.Request) bool {
	if r.Header.Get("Sec-Fetch-Site") == "cross-site" {
		return false
	}
	origin := r.Header.Get("Origin")
	if origin == "" {
		return true
	}
	u, err := url.Parse(origin)
	if err != nil || u.Host == "" {
		return false
	}
	if strings.EqualFold(u.Host, r.Host) {
		return true
	}
	pub, err := url.Parse(m.PublicURL)
	return err == nil && pub.Host != "" && strings.EqualFold(u.Host, pub.Host)
}

func (m *Module) bearerOrSession(r *http.Request) (string, error) {
	if hdr := r.Header.Get("Authorization"); hdr != "" {
		return hdr, nil
	}
	c, err := r.Cookie(m.sessionCookieName())
	if err != nil || c.Value == "" {
		return "", nil
	}
	if r.Method != http.MethodGet && r.Method != http.MethodHead && r.Method != http.MethodOptions && !m.sameOrigin(r) {
		return "", ErrForbidden
	}
	tok, ok := m.open(c.Value)
	if !ok || tok == "" {
		return "", nil
	}
	return "Bearer " + tok, nil
}

// Token is the person's own token, from the Authorization header or the web session, to call
// auth-server as them, such as their homes or preferences. Empty when there's none. It isn't
// checked: call Person or PersonPage first.
func (m *Module) Token(r *http.Request) string {
	hdr, err := m.bearerOrSession(r)
	if err != nil {
		return ""
	}
	tok, _ := bearer(hdr)
	return tok
}

func (m *Module) setSessionCookie(w http.ResponseWriter, token string, maxAge int) error {
	val, err := m.seal(token)
	if err != nil {
		return err
	}
	http.SetCookie(w, &http.Cookie{
		Name: m.sessionCookieName(), Value: val, Path: "/", MaxAge: maxAge,
		HttpOnly: true, Secure: m.secureCookie(), SameSite: http.SameSiteLaxMode,
	})
	return nil
}

func (m *Module) login(w http.ResponseWriter, r *http.Request) {
	next := safeNext(r.URL.Query().Get("next"))
	if os.Getenv("T10_STANDALONE") != "" && os.Getenv("AUTH_ISSUER") == "" {
		tok := "person"
		if perms, ok := r.URL.Query()["permissions"]; ok {
			tok = "person:" + perms[0]
		}
		if m.setSessionCookie(w, tok, 12*3600) != nil {
			Reply(w, 500, map[string]string{"error": "session_unavailable"})
			return
		}
		http.Redirect(w, r, next, http.StatusSeeOther)
		return
	}
	issuer := strings.TrimRight(os.Getenv("AUTH_ISSUER"), "/")
	if issuer == "" || m.PublicURL == "" {
		Reply(w, 503, map[string]string{"error": "authorization_unavailable"})
		return
	}
	state, verifier := randomToken(16), randomToken(32)
	sealed, err := m.seal(state + "\n" + verifier + "\n" + next)
	if err != nil {
		Reply(w, 500, map[string]string{"error": "session_unavailable"})
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name: m.oauthCookieName(), Value: sealed, Path: "/auth/callback", MaxAge: 600,
		HttpOnly: true, Secure: m.secureCookie(), SameSite: http.SameSiteLaxMode,
	})
	sum := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(sum[:])
	q := url.Values{
		"response_type":         {"code"},
		"client_id":             {m.Service + "-web"},
		"redirect_uri":          {strings.TrimRight(m.PublicURL, "/") + "/auth/callback"},
		"state":                 {state},
		"code_challenge":        {challenge},
		"code_challenge_method": {"S256"},
	}
	// The tenant to sign in to, as the app's /t/<tenant>/ names it. auth-server takes it only
	// when the person is a member there.
	if tenant := r.URL.Query().Get("tenant"); tenant != "" {
		q.Set("tenant", tenant)
	}
	http.Redirect(w, r, issuer+"/v1/authorize?"+q.Encode(), http.StatusSeeOther)
}

func (m *Module) callback(w http.ResponseWriter, r *http.Request) {
	c, err := r.Cookie(m.oauthCookieName())
	http.SetCookie(w, &http.Cookie{
		Name: m.oauthCookieName(), Value: "", Path: "/auth/callback", MaxAge: -1,
		HttpOnly: true, Secure: m.secureCookie(), SameSite: http.SameSiteLaxMode,
	})
	if err != nil {
		Reply(w, 400, map[string]string{"error": "invalid_state"})
		return
	}
	plain, ok := m.open(c.Value)
	parts := strings.SplitN(plain, "\n", 3)
	code := r.URL.Query().Get("code")
	if !ok || len(parts) != 3 || parts[0] == "" || r.URL.Query().Get("state") != parts[0] || code == "" {
		Reply(w, 400, map[string]string{"error": "invalid_state"})
		return
	}
	verifier, next := parts[1], safeNext(parts[2])
	authURL := strings.TrimRight(cmp.Or(os.Getenv("AUTH_URL"), os.Getenv("AUTH_ISSUER")), "/")
	body, _ := json.Marshal(map[string]string{
		"grant_type":    "authorization_code",
		"client_id":     m.Service + "-web",
		"client_secret": os.Getenv("AUTH_WEB_CLIENT_SECRET"),
		"code":          code,
		"redirect_uri":  strings.TrimRight(m.PublicURL, "/") + "/auth/callback",
		"code_verifier": verifier,
	})
	req, err := http.NewRequestWithContext(r.Context(), http.MethodPost, authURL+"/v1/token", bytes.NewReader(body))
	if err != nil {
		Reply(w, 503, map[string]string{"error": "authorization_unavailable"})
		return
	}
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 5 * time.Second}
	res, err := client.Do(req)
	if err != nil {
		Reply(w, 503, map[string]string{"error": "authorization_unavailable"})
		return
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		Reply(w, 401, map[string]string{"error": "unauthorized"})
		return
	}
	var out struct {
		AccessToken string `json:"access_token"`
		ExpiresIn   int    `json:"expires_in"`
	}
	if json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(&out) != nil || out.AccessToken == "" {
		Reply(w, 503, map[string]string{"error": "authorization_unavailable"})
		return
	}
	if m.setSessionCookie(w, out.AccessToken, cmp.Or(out.ExpiresIn, 12*3600)) != nil {
		Reply(w, 500, map[string]string{"error": "session_unavailable"})
		return
	}
	http.Redirect(w, r, next, http.StatusSeeOther)
}

// logout ends this app's session, then sends the browser on to auth-server to end the sign-in
// behind it and every other t10 app's session in this browser, as every t10 app does: with a
// sign-out ticket when the session can ask for one, auth-server's own sign-out page when it
// can't, and /signed-out?reason=incomplete when auth-server isn't answering. Standalone, with no
// auth-server, it goes to next.
func (m *Module) logout(w http.ResponseWriter, r *http.Request) {
	if !m.sameOrigin(r) {
		Reply(w, 403, map[string]string{"error": "forbidden"})
		return
	}
	target := m.signOutTarget(r)
	m.clearSession(w)
	http.Redirect(w, r, target, http.StatusSeeOther)
}

func (m *Module) clearSession(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name: m.sessionCookieName(), Value: "", Path: "/", MaxAge: -1,
		HttpOnly: true, Secure: m.secureCookie(), SameSite: http.SameSiteLaxMode,
	})
}

func (m *Module) signOutTarget(r *http.Request) string {
	issuer := strings.TrimRight(os.Getenv("AUTH_ISSUER"), "/")
	if issuer == "" {
		return safeNext(r.URL.Query().Get("next"))
	}
	const incomplete = "/signed-out?reason=incomplete"
	token := m.Token(r)
	if token == "" {
		return issuer + "/v1/signout"
	}
	// auth-server returns the browser only to /signed-out on an origin registered for this
	// app's web client.
	pub, err := url.Parse(m.PublicURL)
	if err != nil || pub.Host == "" {
		return issuer + "/v1/signout"
	}
	var out struct {
		Ticket string `json:"ticket"`
	}
	status, err := callAuth(r.Context(), http.MethodPost, "/v1/me/browser-logout", token,
		map[string]string{"client_id": m.Service + "-web", "return_to": pub.Scheme + "://" + pub.Host + "/signed-out"}, &out)
	switch {
	case err != nil || status >= 500:
		return incomplete
	case status != http.StatusOK || out.Ticket == "":
		// The session had already ended: auth-server's page finishes the rest.
		return issuer + "/v1/signout"
	}
	return issuer + "/v1/signout/complete?ticket=" + url.QueryEscape(out.Ticket)
}

// callAuth calls auth-server as the person whose token this is, with a JSON body when body
// isn't nil, and decodes a 200's JSON answer into out when out isn't nil.
func callAuth(ctx context.Context, method, path, token string, body, out any) (int, error) {
	var rd io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return 0, err
		}
		rd = bytes.NewReader(raw)
	}
	authURL := strings.TrimRight(cmp.Or(os.Getenv("AUTH_URL"), os.Getenv("AUTH_ISSUER")), "/")
	req, err := http.NewRequestWithContext(ctx, method, authURL+path, rd)
	if err != nil {
		return 0, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	res, err := authHTTP.Do(req)
	if err != nil {
		return 0, err
	}
	defer res.Body.Close()
	if res.StatusCode == http.StatusOK && out != nil {
		if err := json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(out); err != nil {
			return 0, err
		}
	}
	return res.StatusCode, nil
}

var authHTTP = &http.Client{Timeout: 5 * time.Second}

// PersonPage is Person for a page a browser opens. A browser that isn't signed in, or whose
// session has ended, goes to sign-in and comes back here; on a page under /t/{tenant}/, a
// session for another tenant signs in to that one, once. A request with an Authorization header
// is answered as Person answers it.
func (m *Module) PersonPage(w http.ResponseWriter, r *http.Request) (Caller, bool) {
	hdr, err := m.bearerOrSession(r)
	if err != nil {
		Refuse(w, err)
		return Caller{}, false
	}
	browser := r.Header.Get("Authorization") == ""
	if hdr == "" {
		m.toSignIn(w, r, "")
		return Caller{}, false
	}
	c, err := m.Access.Person(r.Context(), hdr)
	if errors.Is(err, ErrUnauthorized) && browser {
		m.clearSession(w)
		m.toSignIn(w, r, "")
		return Caller{}, false
	}
	if err != nil {
		Refuse(w, err)
		return Caller{}, false
	}
	if tenant := r.PathValue("tenant"); tenant != "" && tenant != c.TenantID {
		// Once: auth-server signs in to another tenant when this person isn't in this one.
		tried, _ := r.Cookie(m.ID + "_tenant")
		if browser && r.Method == http.MethodGet && (tried == nil || tried.Value != tenant) {
			http.SetCookie(w, &http.Cookie{Name: m.ID + "_tenant", Value: tenant, Path: "/", MaxAge: 120,
				HttpOnly: true, Secure: m.secureCookie(), SameSite: http.SameSiteLaxMode})
			m.toSignIn(w, r, tenant)
			return Caller{}, false
		}
		Refuse(w, ErrForbidden)
		return Caller{}, false
	}
	return c, true
}

// toSignIn sends a GET to sign-in, to come back to the same address; anything else gets 401.
func (m *Module) toSignIn(w http.ResponseWriter, r *http.Request, tenant string) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		Refuse(w, ErrUnauthorized)
		return
	}
	q := url.Values{"next": {safeNext(r.URL.RequestURI())}}
	if tenant = cmp.Or(tenant, r.PathValue("tenant")); tenant != "" {
		q.Set("tenant", tenant)
	}
	http.Redirect(w, r, "/auth/login?"+q.Encode(), http.StatusSeeOther)
}

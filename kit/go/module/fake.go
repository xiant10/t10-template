package module

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"os"
	"path/filepath"
	"slices"
)

// Fake stands in for auth-server in a module's tests: "Bearer person" is Caller signed in,
// "Bearer agent" is an agent acting for Caller with Actions (any action when nil), anything
// else is refused. Down makes everything unavailable, as when auth-server is down.
type Fake struct {
	Caller  Caller
	Actions []string
	Down    bool
}

func (f Fake) Ready(context.Context) error {
	if f.Down {
		return ErrUnavailable
	}
	return nil
}

func (f Fake) Person(_ context.Context, header string) (Caller, error) {
	switch {
	case f.Down:
		return Caller{}, ErrUnavailable
	case header == "Bearer person":
		return f.Caller, nil
	case header == "":
		return Caller{}, ErrUnauthorized
	}
	return Caller{}, ErrForbidden
}

func (f Fake) Agent(_ context.Context, header, action string) (Caller, error) {
	switch {
	case f.Down:
		return Caller{}, ErrUnavailable
	case header == "Bearer agent" && (f.Actions == nil || slices.Contains(f.Actions, action)):
		return f.Caller, nil
	case header == "":
		return Caller{}, ErrUnauthorized
	}
	return Caller{}, ErrForbidden
}

// NewAccess is how a module's service checks callers: Auth against auth-server, from the
// settings the project's standard wiring gives every module, or, with T10_STANDALONE=1, a Fake
// for running the module alone (`make alone`), with no foundation: "Bearer person" is a tenant
// admin, "Bearer agent" an agent acting for them with any action. Standalone mode refuses to
// start when AUTH_ISSUER is set, as it is wherever the module runs with the foundation, so it
// can't be switched on there.
func NewAccess(module, service string) (Access, error) {
	if os.Getenv("T10_STANDALONE") == "" {
		return NewAuth(module, service)
	}
	if os.Getenv("AUTH_ISSUER") != "" {
		return nil, errors.New("T10_STANDALONE is set beside AUTH_ISSUER: standalone mode is only for running a module alone")
	}
	actions := catalogActions(module)
	log.Printf("standalone: no auth-server; Bearer person is a tenant admin, Bearer agent may use %v (make alone)", actions)
	return Fake{Caller: Caller{TenantID: "ten_alone", UserID: "usr_alone", TenantAdmin: true, Permissions: []string{}}, Actions: actions}, nil
}

// catalogActions are the actions the module's catalog lets its agent tools use, from the pack
// in its image (/module, or T10_PACK_DIR), so a tool whose action is missing there fails alone,
// as it would in the stack. nil, meaning any, when the catalog isn't JSON.
func catalogActions(module string) []string {
	dir := os.Getenv("T10_PACK_DIR")
	if dir == "" {
		dir = "/module"
	}
	var catalog struct {
		Agent struct {
			Actions []string `json:"actions"`
		} `json:"agent"`
	}
	raw, err := os.ReadFile(filepath.Join(dir, "permissions", module+".yaml"))
	if err != nil || json.Unmarshal(raw, &catalog) != nil {
		log.Printf("standalone: no JSON catalog in %s, so an agent may use any action", dir)
		return nil
	}
	return catalog.Agent.Actions
}

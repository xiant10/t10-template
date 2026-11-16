package module

import (
	"context"
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

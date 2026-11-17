package main

import (
	"context"

	"t10kit/module"
)

// readAction is the delegated action the tools here need unless one names another. Each
// action a tool uses goes in the catalog's agent block (module/permissions/__id__.yaml), the one
// place it's said: the project gives it to the agent, its runtimes and the harnesses.
const readAction = "__id__:read"

// tools are the module's agent tools. Each gets the person the agent acts for, never the
// agent's own rights. Replace the example with the module's own.
func tools() []module.Tool {
	return []module.Tool{{
		Name:        "__id___whoami",
		Description: "Say who the user is in the __Id__ module: their tenant, whether they administer it, and their __Id__ permissions.",
		Action:      readAction,
		ReadOnly:    true,
		Schema:      module.Schema(nil, map[string]any{}),
		Run: module.Args(func(ctx context.Context, c module.Caller, _ struct{}) (any, error) {
			return map[string]any{"tenant_id": c.TenantID, "user_id": c.UserID, "tenant_admin": c.TenantAdmin, "permissions": c.Permissions}, nil
		}),
	}}
}

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
)

// readAction is the delegated action every tool here needs unless it names another. Each
// action a tool uses must be in GRANT_ACTIONS (module/module.env), the catalog's agent block
// (module/permissions/__id__.yaml), the agent's grants (module/agents/__id__/agent.json) and
// the runtimes in module/clients.fragment.json. `make check` says when one is missing.
const readAction = "__id__:read"

var errBadArguments = errors.New("the arguments don't fit this tool")

// tool is one agent tool. run gets the person the agent acts for, never the agent's own rights.
type tool struct {
	name, description string
	action            string
	schema            map[string]any
	run               func(ctx context.Context, c Caller, args json.RawMessage) (any, error)
}

// tools are the module's agent tools. Replace the example with the module's own.
func tools() []tool {
	return []tool{{
		name:        "__id___whoami",
		description: "Say who the user is in the __Id__ module: their tenant, whether they administer it, and their __Id__ permissions.",
		action:      readAction,
		schema:      schema(nil, map[string]any{}),
		run: args(func(ctx context.Context, c Caller, _ struct{}) (any, error) {
			return map[string]any{"tenant_id": c.TenantID, "user_id": c.UserID, "tenant_admin": c.TenantAdmin, "permissions": c.Permissions}, nil
		}),
	}}
}

// args decodes a tool's arguments into A, refusing fields it doesn't know.
func args[A any](run func(ctx context.Context, c Caller, a A) (any, error)) func(context.Context, Caller, json.RawMessage) (any, error) {
	return func(ctx context.Context, c Caller, raw json.RawMessage) (any, error) {
		var a A
		if len(bytes.TrimSpace(raw)) > 0 && string(bytes.TrimSpace(raw)) != "null" {
			d := json.NewDecoder(bytes.NewReader(raw))
			d.DisallowUnknownFields()
			if d.Decode(&a) != nil {
				return nil, errBadArguments
			}
		}
		return run(ctx, c, a)
	}
}

func schema(required []string, properties map[string]any) map[string]any {
	if required == nil {
		required = []string{}
	}
	return map[string]any{"type": "object", "properties": properties, "required": required, "additionalProperties": false}
}

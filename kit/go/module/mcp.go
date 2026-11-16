package module

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"slices"
)

// Tool is one agent tool. Run gets the person the agent acts for, never the agent's own rights.
type Tool struct {
	Name, Description string
	// Action is the delegated action calling it needs, such as crm:read. It must be in the
	// catalog's agent block, the one place a module says what its tools need.
	Action string
	// ReadOnly tells harnesses the tool changes nothing.
	ReadOnly bool
	Schema   map[string]any
	Run      func(ctx context.Context, c Caller, args json.RawMessage) (any, error)
}

// ErrBadArguments is what Run returns when the arguments don't fit; Args returns it for you.
var ErrBadArguments = errors.New("the arguments don't fit this tool")

// Args decodes a tool's arguments into A, refusing fields it doesn't know.
func Args[A any](run func(ctx context.Context, c Caller, a A) (any, error)) func(context.Context, Caller, json.RawMessage) (any, error) {
	return func(ctx context.Context, c Caller, raw json.RawMessage) (any, error) {
		var a A
		if len(bytes.TrimSpace(raw)) > 0 && string(bytes.TrimSpace(raw)) != "null" {
			d := json.NewDecoder(bytes.NewReader(raw))
			d.DisallowUnknownFields()
			if d.Decode(&a) != nil {
				return nil, ErrBadArguments
			}
		}
		return run(ctx, c, a)
	}
}

// Schema is a tool's input schema: an object with these properties, no others.
func Schema(required []string, properties map[string]any) map[string]any {
	if required == nil {
		required = []string{}
	}
	return map[string]any{"type": "object", "properties": properties, "required": required, "additionalProperties": false}
}

// The tools side of MCP over Streamable HTTP, with no session and no stream. Harnesses reach
// it only through ai-gateway-tools, with a delegated token for the person they act for.

// mcpVersions are the protocol versions spoken here, newest first.
var mcpVersions = []string{"2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"}

const (
	rpcParseError     = -32700
	rpcMethodNotFound = -32601
	rpcInvalidParams  = -32602
)

type rpcMessage struct {
	ID     json.RawMessage `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

// Listing needs no token: harnesses list at startup with no user, and the list holds
// nothing about a tenant. Calling one needs the person's delegated token.
func (m *Module) mcp(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	// For harnesses through the gateway only, never for pages.
	if r.Header.Get("Origin") != "" {
		Reply(w, 403, map[string]string{"error": "forbidden"})
		return
	}
	var message rpcMessage
	if json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10)).Decode(&message) != nil {
		rpcError(w, 400, nil, rpcParseError, "the body isn't a JSON-RPC message")
		return
	}
	if message.ID == nil {
		w.WriteHeader(202)
		return
	}
	switch message.Method {
	case "initialize":
		var params struct {
			ProtocolVersion string `json:"protocolVersion"`
		}
		_ = json.Unmarshal(message.Params, &params)
		version := mcpVersions[0]
		if slices.Contains(mcpVersions, params.ProtocolVersion) {
			version = params.ProtocolVersion
		}
		rpcResult(w, message.ID, map[string]any{"protocolVersion": version, "capabilities": map[string]any{"tools": map[string]any{}},
			"serverInfo": map[string]any{"name": m.Service, "version": "1"}})
	case "ping":
		rpcResult(w, message.ID, map[string]any{})
	case "tools/list":
		listed := []map[string]any{}
		for _, t := range m.Tools {
			listed = append(listed, map[string]any{"name": t.Name, "description": t.Description, "inputSchema": t.Schema,
				"annotations": map[string]any{"readOnlyHint": t.ReadOnly}})
		}
		rpcResult(w, message.ID, map[string]any{"tools": listed})
	case "tools/call":
		m.call(w, r, message)
	default:
		rpcError(w, 200, message.ID, rpcMethodNotFound, "unknown method")
	}
}

func (m *Module) call(w http.ResponseWriter, r *http.Request, message rpcMessage) {
	var params struct {
		Name      string          `json:"name"`
		Arguments json.RawMessage `json:"arguments"`
	}
	if json.Unmarshal(message.Params, &params) != nil {
		rpcError(w, 200, message.ID, rpcInvalidParams, "params aren't valid")
		return
	}
	i := slices.IndexFunc(m.Tools, func(t Tool) bool { return t.Name == params.Name })
	// Check the token before saying whether the tool exists: for an unknown one, against the
	// first tool's action.
	action := m.ID + ":read"
	if i >= 0 {
		action = m.Tools[i].Action
	} else if len(m.Tools) > 0 {
		action = m.Tools[0].Action
	}
	c, err := m.Access.Agent(r.Context(), r.Header.Get("Authorization"), action)
	if errors.Is(err, ErrUnauthorized) || errors.Is(err, ErrForbidden) {
		Refuse(w, err)
		return
	}
	if err != nil {
		rpcResult(w, message.ID, toolFailure("unavailable", "this person's access couldn't be checked; try again shortly"))
		return
	}
	if i < 0 {
		rpcError(w, 200, message.ID, rpcInvalidParams, "unknown tool")
		return
	}
	out, err := m.Tools[i].Run(r.Context(), c, params.Arguments)
	if errors.Is(err, ErrBadArguments) {
		rpcResult(w, message.ID, toolFailure("invalid_arguments", "check the arguments against the tool's schema; don't repeat the same call"))
		return
	}
	if err != nil {
		slog.Error("tool failed", "tool", params.Name, "error", err)
		rpcResult(w, message.ID, toolFailure("unavailable", "the "+m.ID+" module couldn't answer; try again shortly"))
		return
	}
	encoded, err := json.Marshal(out)
	if err != nil {
		rpcResult(w, message.ID, toolFailure("internal_error", "something went wrong"))
		return
	}
	// Marked as data, since people wrote the text in it. json.Marshal escapes <, so the text
	// can't close the tag.
	rpcResult(w, message.ID, map[string]any{"content": []map[string]any{{"type": "text",
		"text": "<module_record module=\"" + m.ID + "\">\n" + string(encoded) + "\n</module_record>"}}})
}

func toolFailure(code, text string) map[string]any {
	return map[string]any{"isError": true, "content": []map[string]any{{"type": "text", "text": code + ": " + text}}}
}

func rpcResult(w http.ResponseWriter, id json.RawMessage, result any) {
	Reply(w, 200, map[string]any{"jsonrpc": "2.0", "id": id, "result": result})
}

func rpcError(w http.ResponseWriter, status int, id json.RawMessage, code int, message string) {
	Reply(w, status, map[string]any{"jsonrpc": "2.0", "id": id, "error": map[string]any{"code": code, "message": message}})
}

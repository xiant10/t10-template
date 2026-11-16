package main

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"slices"
)

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
func (s *Server) mcp(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	// For harnesses through the gateway only, never for pages.
	if r.Header.Get("Origin") != "" {
		reply(w, 403, map[string]string{"error": "forbidden"})
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
			"serverInfo": map[string]any{"name": service, "version": "1"}})
	case "ping":
		rpcResult(w, message.ID, map[string]any{})
	case "tools/list":
		listed := []map[string]any{}
		for _, t := range tools() {
			listed = append(listed, map[string]any{"name": t.name, "description": t.description, "inputSchema": t.schema,
				"annotations": map[string]any{"readOnlyHint": t.action == readAction}})
		}
		rpcResult(w, message.ID, map[string]any{"tools": listed})
	case "tools/call":
		s.call(w, r, message)
	default:
		rpcError(w, 200, message.ID, rpcMethodNotFound, "unknown method")
	}
}

func (s *Server) call(w http.ResponseWriter, r *http.Request, message rpcMessage) {
	var params struct {
		Name      string          `json:"name"`
		Arguments json.RawMessage `json:"arguments"`
	}
	if json.Unmarshal(message.Params, &params) != nil {
		rpcError(w, 200, message.ID, rpcInvalidParams, "params aren't valid")
		return
	}
	all := tools()
	i := slices.IndexFunc(all, func(t tool) bool { return t.name == params.Name })
	action := readAction
	if i >= 0 {
		action = all[i].action
	}
	// Check the token before saying whether the tool exists.
	c, err := s.Access.Agent(r.Context(), r.Header.Get("Authorization"), action)
	if errors.Is(err, ErrUnauthorized) || errors.Is(err, ErrForbidden) {
		refuse(w, err)
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
	out, err := all[i].run(r.Context(), c, params.Arguments)
	if errors.Is(err, errBadArguments) {
		rpcResult(w, message.ID, toolFailure("invalid_arguments", "check the arguments against the tool's schema; don't repeat the same call"))
		return
	}
	if err != nil {
		slog.Error("tool failed", "tool", params.Name, "error", err)
		rpcResult(w, message.ID, toolFailure("unavailable", "the __id__ module couldn't answer; try again shortly"))
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
		"text": "<module_record module=\"" + moduleID + "\">\n" + string(encoded) + "\n</module_record>"}}})
}

func toolFailure(code, text string) map[string]any {
	return map[string]any{"isError": true, "content": []map[string]any{{"type": "text", "text": code + ": " + text}}}
}

func rpcResult(w http.ResponseWriter, id json.RawMessage, result any) {
	reply(w, 200, map[string]any{"jsonrpc": "2.0", "id": id, "result": result})
}

func rpcError(w http.ResponseWriter, status int, id json.RawMessage, code int, message string) {
	reply(w, status, map[string]any{"jsonrpc": "2.0", "id": id, "error": map[string]any{"code": code, "message": message}})
}

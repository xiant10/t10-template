// A scripted OpenAI-compatible model, so the stack can be checked with no provider key.
// Adapted from t10-quickstart's scripted/fake-model.mjs. Each module may name a tool to call,
// in a SCRIPTED_TOOL_<ID> variable its compose/scripted.yml sets: {"tool": suffix, "args": {…}}.
// When a user turn offers a tool whose name ends with one of those suffixes, it calls it, then
// quotes what the tool returned, which completes one agent loop through ai-gateway-llm, a
// harness, ai-gateway-tools and the module. Otherwise it replies with fixed text.
// /seen lists identity headers it received, so a check can prove none reach a provider.
import { createServer } from "node:http";

const scripted = Object.entries(process.env).filter(([k]) => k.startsWith("SCRIPTED_TOOL_")).map(([, v]) => JSON.parse(v));

const seen = [];
createServer(async (req, res) => {
	if (req.url === "/seen") return res.end(JSON.stringify(seen));
	let raw = "";
	for await (const part of req) raw += part;
	const { messages = [], tools = [] } = JSON.parse(raw || "{}");
	const last = messages.at(-1) ?? {};
	seen.push(...Object.keys(req.headers).filter((name) => ["x-user-id", "x-tenant-id", "x-session-id", "x-turn-id"].includes(name)));
	res.writeHead(200, { "content-type": "text/event-stream" });
	const chunk = (delta, finish_reason = null) => `data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", choices: [{ index: 0, delta, finish_reason }] })}\n\n`;
	const names = tools.map((t) => t.function?.name).filter(Boolean);
	const pick = scripted.map((s) => ({ ...s, name: names.find((n) => n.endsWith(s.tool)) })).find((s) => s.name);
	if (last.role === "user" && pick) {
		const call = { index: 0, id: "call_1", type: "function", function: { name: pick.name, arguments: JSON.stringify(pick.args ?? {}) } };
		return res.end(`${chunk({ role: "assistant", tool_calls: [call] })}${chunk({}, "tool_calls")}data: [DONE]\n\n`);
	}
	const reply = last.role === "tool" ? `tool said: ${String(typeof last.content === "string" ? last.content : JSON.stringify(last.content)).slice(0, 200)}` : "scripted reply";
	res.end(`${chunk({ role: "assistant", content: reply })}${chunk({}, "stop")}data: [DONE]\n\n`);
}).listen(8080);

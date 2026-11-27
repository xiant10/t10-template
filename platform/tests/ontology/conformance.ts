/**
 * Black-box tests of the ontology contract (README.md). It speaks only HTTP to a module, so a module in any language can
 * run it, with three test tokens and a config naming the module's own fixtures:
 *
 *   node contracts/ontology/conformance.ts <module URL> <config.json>
 *   node contracts/ontology/conformance.ts --self-test   # against t10-modkit's stub, unbroken and broken each way
 *
 * The config, such as testdata/stub.json, gives:
 *   tokens: in_scope (a person who sees `visible`), out_of_scope (a person in the same tenant who doesn't), agent (a
 *     delegated token for in_scope's person);
 *   visible: a reference in_scope sees;
 *   search: {type, body, limit, expect}: a search in_scope sees `expect` objects of, paged by `limit`;
 *   forbidden, wrong_state, apply: {action, object, params}: an action in_scope sees but may not take, one on an
 *     object in a state that refuses it, and a repeatable one;
 *   idempotent: an idempotent action; undo: an undo action, with `dependent`, an action that then depends on it. A
 *     module with none leaves them out, and those checks are skipped.
 * An object may be "$first:<type>", the first object in_scope's search finds, or "$newest:<type>", the same, read
 * when it's used. The self-test needs Go and the t10-modkit checkout beside this workspace.
 */
import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { checkDescriptor } from "./descriptor.ts";

type Json = any;
type ActionCase = { action: string; object?: string; params: Record<string, Json> };
export type Config = {
	tokens: { in_scope: string; out_of_scope: string; agent: string };
	visible: string;
	search: { type: string; body: Record<string, Json>; limit: number; expect: number };
	forbidden: ActionCase;
	wrong_state: ActionCase;
	apply: ActionCase;
	idempotent?: ActionCase;
	undo?: ActionCase & { dependent: ActionCase };
};

class Failure extends Error {}
const must = (ok: unknown, message: string) => {
	if (!ok) throw new Failure(message);
};

type Answer = { status: number; body: Json; text: string };

/** Runs every check, and answers the names of those that failed, each with why. */
export async function runSuite(base: string, config: Config, log: (line: string) => void = () => {}): Promise<string[]> {
	const call = async (method: string, path: string, token?: string, body?: unknown, headers: Record<string, string> = {}): Promise<Answer> => {
		const h: Record<string, string> = { ...headers };
		if (token) h.authorization = `Bearer ${token}`;
		if (body !== undefined) h["content-type"] = "application/json";
		const res = await fetch(base + path, { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) });
		const text = await res.text();
		let parsed: Json;
		try {
			parsed = JSON.parse(text);
		} catch {
			parsed = undefined;
		}
		return { status: res.status, body: parsed, text };
	};
	const { in_scope: person, out_of_scope: outsider, agent } = config.tokens;
	const split = (ref: string) => {
		const [module, type, ...rest] = ref.split(":");
		return { module, type, id: rest.join(":") };
	};
	const objectPath = (ref: string) => `/v1/objects/${encodeURIComponent(split(ref).type)}/${encodeURIComponent(split(ref).id)}`;
	const resolveRef = async (ref: string | undefined): Promise<string | undefined> => {
		const m = ref?.match(/^\$(first|newest):(\w+)$/);
		if (!m) return ref;
		const found = await call("POST", `/v1/objects/${m[2]}/search`, person, { limit: 1 });
		must(found.status === 200 && found.body.objects.length > 0, `${ref}: in_scope's search of ${m[2]} found nothing`);
		return found.body.objects[0].ref;
	};
	const body = async (c: ActionCase, revision?: number) => {
		const object = await resolveRef(c.object);
		const params: Record<string, Json> = {};
		for (const [k, v] of Object.entries(c.params)) params[k] = typeof v === "string" && v.startsWith("$") ? await resolveRef(v) : v;
		let rev = revision;
		if (rev === undefined && object) {
			const got = await call("GET", objectPath(object), person);
			must(got.status === 200, `${object} isn't visible to in_scope (${got.status})`);
			rev = got.body.revision;
		}
		return { object, revision: rev, params };
	};
	const apply = async (c: ActionCase, token = person, key?: string, revision?: number) =>
		call("POST", `/v1/actions/${encodeURIComponent(c.action)}/apply`, token, await body(c, revision), key ? { "idempotency-key": key } : {});

	let manifest: Json;
	let descriptor: Json;
	const failed: string[] = [];
	const check = async (name: string, run: () => Promise<void>, skip?: string) => {
		if (skip) {
			log(`skip ${name}: ${skip}`);
			return;
		}
		try {
			await run();
			log(`ok   ${name}`);
		} catch (e) {
			const why = e instanceof Error ? e.message : String(e);
			failed.push(`${name}: ${why}`);
			log(`FAIL ${name}: ${why}`);
		}
	};

	await check("manifest lists ontology", async () => {
		const m = await call("GET", "/v1/module", person);
		must(m.status === 200, `GET /v1/module answered ${m.status}`);
		manifest = m.body;
		must((manifest.features ?? []).includes("ontology"), "features doesn't list ontology");
	});
	await check("descriptor answers people and agents, not anonymous callers", async () => {
		const d = await call("GET", "/v1/ontology", person);
		must(d.status === 200, `a person's token answered ${d.status}`);
		descriptor = d.body;
		must(descriptor.module === manifest?.id, `module ${descriptor.module} isn't the manifest's id ${manifest?.id}`);
		must((await call("GET", "/v1/ontology", agent)).status === 200, "a delegated token can't read the descriptor");
		const none = await call("GET", "/v1/ontology");
		must(none.status === 401 && typeof none.body?.error === "string", `no token answered ${none.status} ${none.text}`);
	});
	await check("descriptor meets the schema and the contract's rules", async () => {
		const errors = checkDescriptor(descriptor);
		must(errors.length === 0, errors.join("; "));
	});
	await check("a module with an undoable action names it in the config", async () => {
		const undoable = Object.entries(descriptor?.action_types ?? {}).filter(([, a]: [string, Json]) => a.agent === "undoable").map(([k]) => k);
		must(undoable.length === 0 || config.undo !== undefined, `the descriptor has ${undoable.join(", ")}, so the config needs undo`);
	});
	await check("descriptor's events are in the manifest", async () => {
		const named = new Set<string>();
		for (const field of ["events", "trigger_events"]) {
			const v = manifest?.[field];
			for (const k of Array.isArray(v) ? v : Object.keys(v ?? {})) named.add(k);
		}
		for (const kind of Object.keys(descriptor?.events ?? {})) must(named.has(kind), `the manifest doesn't name ${kind}`);
	});
	await check("objects have the contract's shape and actions lists", async () => {
		const o = await call("GET", objectPath(config.visible), person);
		must(o.status === 200, `GET ${config.visible} answered ${o.status}`);
		for (const k of ["ref", "type", "title", "revision", "properties", "actions"]) must(k in o.body, `the answer has no ${k}`);
		must(o.body.ref === config.visible, `ref ${o.body.ref}`);
		const type = split(config.visible).type;
		const declared = Object.entries(descriptor.action_types).filter(([, a]: [string, Json]) => a.on === type).map(([k]) => k).sort();
		const listed = o.body.actions.map((a: Json) => a.action).sort();
		must(JSON.stringify(declared) === JSON.stringify(listed), `actions lists ${listed}, the descriptor declares ${declared}`);
		for (const a of o.body.actions) must(typeof a.allowed === "boolean" && (a.allowed || typeof a.reason === "string"), `${a.action} has no reason`);
	});
	await check("objects a caller can't reach answer 404, as missing ones do", async () => {
		const hidden = await call("GET", objectPath(config.visible), outsider);
		const missing = await call("GET", `/v1/objects/${split(config.visible).type}/conformance-missing-${randomUUID()}`, outsider);
		must(hidden.status === 404, `out_of_scope got ${hidden.status}`);
		must(hidden.text === missing.text, `hidden ${hidden.text} and missing ${missing.text} differ`);
	});
	await check("unknown types answer 404 unknown_type", async () => {
		const a = await call("GET", "/v1/objects/conformance_nothing/x", person);
		must(a.status === 404 && a.body?.error === "unknown_type", `answered ${a.status} ${a.text}`);
	});
	await check("delegated tokens are refused on object routes", async () => {
		for (const [method, path, b] of [
			["GET", objectPath(config.visible)],
			["POST", `/v1/objects/${split(config.visible).type}/search`, {}],
			["POST", "/v1/objects/resolve", { refs: [config.visible] }],
		] as const) {
			const a = await call(method, path, agent, b);
			must(a.status === 401, `${method} ${path} answered ${a.status}`);
		}
	});
	await check("search applies scope before sorting and paging", async () => {
		const { type, body: q, limit, expect } = config.search;
		let cursor: string | undefined;
		const seen: string[] = [];
		let first = true;
		for (let pages = 0; pages < 50; pages++) {
			const a = await call("POST", `/v1/objects/${type}/search`, person, { ...q, limit, ...(cursor ? { cursor } : {}) });
			must(a.status === 200, `search answered ${a.status} ${a.text}`);
			const objs = a.body.objects as Json[];
			if (first) must(objs.length === Math.min(limit, expect), `the first page has ${objs.length} objects, not ${Math.min(limit, expect)}`);
			first = false;
			for (const o of objs) {
				must((await call("GET", objectPath(o.ref), person)).status === 200, `search answered ${o.ref}, which get doesn't`);
				seen.push(o.ref);
			}
			cursor = a.body.next_cursor;
			if (!cursor) break;
		}
		must(seen.length === expect && new Set(seen).size === expect, `found ${seen.length} (${new Set(seen).size} distinct), not ${expect}`);
	});
	await check("search refuses bad bodies", async () => {
		const type = config.search.type;
		for (const [what, b] of [
			["a limit over 100", { limit: 101 }],
			["an unknown property", { filter: { property: "conformance_nothing", op: "eq", value: 1 } }],
			["a cursor it didn't issue", { cursor: "Y29uZm9ybWFuY2U" }],
		] as const) {
			const a = await call("POST", `/v1/objects/${type}/search`, person, b);
			must(a.status === 400 && typeof a.body?.error === "string", `${what} answered ${a.status}`);
		}
	});
	await check("resolve leaves out what it can't show", async () => {
		const refs = [config.visible, `${split(config.visible).module}:${split(config.visible).type}:conformance-missing`, "conformance:thing:x"];
		const mine = await call("POST", "/v1/objects/resolve", person, { refs });
		must(mine.status === 200, `answered ${mine.status}`);
		const got = mine.body.objects.map((o: Json) => o.ref);
		must(JSON.stringify(got) === JSON.stringify([config.visible]), `in_scope resolved ${got}`);
		const theirs = await call("POST", "/v1/objects/resolve", outsider, { refs });
		const leaked = theirs.body?.objects?.map((o: Json) => o.ref) ?? [];
		must(theirs.status === 200 && leaked.length === 0, `out_of_scope resolved ${leaked}`);
	});
	await check("delegated tokens are refused on action, proposal and undo routes", async () => {
		for (const [method, path] of [
			["POST", `/v1/actions/${config.apply.action}/validate`],
			["POST", `/v1/actions/${config.apply.action}/apply`],
			["POST", "/v1/undo/conformance"],
			["GET", "/v1/proposals"],
			["POST", "/v1/proposals/conformance/confirm"],
			["POST", "/v1/proposals/conformance/dismiss"],
		] as const) {
			const a = await call(method, path, agent, method === "POST" ? {} : undefined);
			must(a.status === 401, `${method} ${path} answered ${a.status}`);
		}
	});
	await check("apply answers 403 to a visible object it refuses, and 404 to a hidden one", async () => {
		const a = await apply(config.forbidden);
		must(a.status === 403, `answered ${a.status} ${a.text}`);
		const b = await apply(config.apply, outsider);
		must(b.status === 404, `out_of_scope's apply answered ${b.status}`);
	});
	await check("apply answers 409 wrong_state", async () => {
		const a = await apply(config.wrong_state);
		must(a.status === 409 && a.body?.error === "wrong_state", `answered ${a.status} ${a.text}`);
	});
	await check("apply answers 409 stale_revision", async () => {
		const b = await body(config.apply);
		const first = await call("POST", `/v1/actions/${config.apply.action}/apply`, person, b);
		must(first.status === 200, `the first apply answered ${first.status} ${first.text}`);
		const again = await call("POST", `/v1/actions/${config.apply.action}/apply`, person, b);
		must(again.status === 409 && again.body?.error === "stale_revision", `the stale apply answered ${again.status} ${again.text}`);
	});
	await check("idempotent actions replay the first answer, and refuse a new body under the same key", async () => {
		const idempotent = config.idempotent!;
		const key = `conformance-${randomUUID()}`;
		const b = await body(idempotent);
		const path = `/v1/actions/${idempotent.action}/apply`;
		const none = await call("POST", path, person, b);
		must(none.status === 400, `no key answered ${none.status}`);
		const one = await call("POST", path, person, b, { "idempotency-key": key });
		const two = await call("POST", path, person, b, { "idempotency-key": key });
		must(one.status === 200 && two.status === 200, `answered ${one.status} and ${two.status}`);
		must(JSON.stringify(one.body) === JSON.stringify(two.body), `the replay answered ${two.text}, not ${one.text}`);
		const other = await call("POST", path, person, { ...b, revision: (b.revision ?? 0) + 1000 }, { "idempotency-key": key });
		must(other.status === 409, `another body under the same key answered ${other.status}`);
	}, config.idempotent ? undefined : "the config names no idempotent action");
	await check("undo works by ID within its window, once, and only for its person", async () => {
		const a = await apply(config.undo!, person, `conformance-${randomUUID()}`);
		must(a.status === 200 && typeof a.body?.undo?.id === "string", `apply answered ${a.status} ${a.text}`);
		must(Date.parse(a.body.undo.expires_at) > Date.now(), "expires_at is past");
		const id = a.body.undo.id;
		must((await call("POST", `/v1/undo/${id}`, outsider, {})).status === 404, "another person could undo it");
		must((await call("POST", `/v1/undo/${id}`, agent, {})).status === 401, "a delegated token could undo it");
		const done = await call("POST", `/v1/undo/${id}`, person, {});
		must(done.status === 200, `undo answered ${done.status} ${done.text}`);
		const again = await call("POST", `/v1/undo/${id}`, person, {});
		must(again.status === 409, `a second undo answered ${again.status}`);
	}, config.undo ? undefined : "the config names no undoable action");
	await check("undo after a dependent change answers 409 undo_conflict", async () => {
		const a = await apply(config.undo!, person, `conformance-${randomUUID()}`);
		must(a.status === 200, `apply answered ${a.status} ${a.text}`);
		const dep = await apply(config.undo!.dependent);
		must(dep.status === 200, `the dependent change answered ${dep.status} ${dep.text}`);
		const u = await call("POST", `/v1/undo/${a.body.undo.id}`, person, {});
		must(u.status === 409 && u.body?.error === "undo_conflict", `undo answered ${u.status} ${u.text}`);
	}, config.undo ? undefined : "the config names no undoable action");
	await check("proposals list the caller's own drafts", async () => {
		const a = await call("GET", "/v1/proposals", person);
		must(a.status === 200 && Array.isArray(a.body?.proposals), `answered ${a.status} ${a.text}`);
	});
	return failed;
}

const here = fileURLToPath(new URL(".", import.meta.url));

// The check each of the stub's -break modes must fail.
const breaks: Record<string, string> = {
	scope: "search applies scope",
	paging: "search applies scope",
	hidden: "objects a caller can't reach",
	"unknown-type": "unknown types",
	resolve: "resolve leaves out",
	delegated: "delegated tokens are refused on object routes",
	forbidden: "apply answers 403",
	"wrong-state": "apply answers 409 wrong_state",
	stale: "apply answers 409 stale_revision",
	replay: "idempotent actions replay",
	"undo-owner": "undo works by ID",
	"undo-conflict": "undo after a dependent change",
	tier: "descriptor meets the schema",
	undoable: "descriptor meets the schema",
	"tenant-action": "descriptor meets the schema",
	label: "descriptor meets the schema",
	events: "descriptor's events",
	interface: "descriptor meets the schema",
};

async function freePort(): Promise<number> {
	return new Promise((resolve) => {
		const s = createServer().listen(0, "127.0.0.1", () => {
			const port = (s.address() as { port: number }).port;
			s.close(() => resolve(port));
		});
	});
}

async function withStub<T>(binary: string, rule: string, run: (base: string) => Promise<T>): Promise<T> {
	const port = await freePort();
	const child: ChildProcess = spawn(binary, ["-addr", `127.0.0.1:${port}`, ...(rule ? ["-break", rule] : [])], { stdio: "ignore" });
	const base = `http://127.0.0.1:${port}`;
	try {
		for (let i = 0; ; i++) {
			try {
				await fetch(`${base}/v1/module`);
				break;
			} catch {
				if (i > 100) throw new Error("the stub didn't start");
				await new Promise((r) => setTimeout(r, 50));
			}
		}
		return await run(base);
	} finally {
		child.kill();
	}
}

async function selfTest(): Promise<number> {
	const modkit = join(here, "../../t10-modkit");
	const dir = mkdtempSync(join(tmpdir(), "ontology-stub-"));
	const binary = join(dir, "stub");
	try {
		execFileSync("go", ["build", "-o", binary, "./ontology/testdata/ledgermod/stub"], { cwd: modkit, stdio: "inherit" });
		const config = JSON.parse(readFileSync(join(here, "testdata/stub.json"), "utf8")) as Config;
		let bad = 0;
		const clean = await withStub(binary, "", (base) => runSuite(base, config));
		if (clean.length > 0) {
			bad++;
			console.error(`the unbroken stub fails:\n  ${clean.join("\n  ")}`);
		}
		for (const [rule, want] of Object.entries(breaks)) {
			const failed = await withStub(binary, rule, (base) => runSuite(base, config));
			if (!failed.some((f) => f.startsWith(want))) {
				bad++;
				console.error(`-break ${rule} should fail "${want}", but failed: ${failed.join("; ") || "nothing"}`);
			}
		}
		console.log(bad === 0 ? `ontology conformance self-test passed (${Object.keys(breaks).length} broken stubs caught)` : `ontology conformance self-test: ${bad} wrong`);
		return bad === 0 ? 0 : 1;
	} finally {
		rmSync(dir, { recursive: true, force: true });
	}
}

if (process.argv[1] !== undefined && fileURLToPath(import.meta.url) === process.argv[1]) {
	const args = process.argv.slice(2);
	if (args[0] === "--self-test") process.exit(await selfTest());
	if (args.length !== 2) {
		console.error("usage: conformance.ts <module URL> <config.json> | --self-test");
		process.exit(2);
	}
	const failed = await runSuite(args[0].replace(/\/+$/, ""), JSON.parse(readFileSync(args[1], "utf8")), console.log);
	console.log(failed.length === 0 ? "ontology conformance passed" : `ontology conformance: ${failed.length} failed`);
	process.exit(failed.length === 0 ? 0 : 1);
}

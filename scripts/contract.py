#!/usr/bin/env python3
"""`make contract MODULE=<id>`: whether one module keeps the module contract (docs/module.md),
on its own, before it joins the stack. Gate 2 of docs/integration.md.

    scripts/contract.py ID [URL]     # URL defaults to where `make alone` runs it

1. Its pack: module.env has every key, a PACK_VERSION this template reads and CAPABILITIES, and
   follows the names its ID sets; its catalog, agents and OAuth clients agree with it; its
   Dockerfile ships the pack at /module. What a capability needs is checked only for a module
   that has it: the agent block and tools for `tools`, the agents for `agent`, the web client for
   `web`.
2. Its service, running (`make alone`, or URL): /readyz; /v1/module and /v1/access for a person,
   and refused without a token or for an agent; with `tools`, its tools over MCP, listed without
   a token, each called by an agent with the actions its catalog grants, and refused for a
   person, without a token, or from a page.

Standalone mode (T10_STANDALONE=1) stands in for auth-server with fixed tokens: "Bearer person"
and "Bearer agent". Against the full stack, `make smoke` checks the same with real tokens.
"""
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import alone  # noqa: E402
import lib  # noqa: E402
import wiring  # noqa: E402

check = lib.check
KEYS = ("PACK_VERSION", "MODULE_ID", "SERVICE", "PORT", "SERVICE_ACCOUNTS", "CAPABILITIES")


def load(path):
    """A JSON file, or None, with a failed check saying why."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        check(f"{path.relative_to(lib.ROOT)} is JSON", False, str(e))
        return None


def pack(mid, folder, src, m):
    u = wiring.upper(mid)
    check("module.env has every key", all(k in m for k in KEYS), ", ".join(k for k in KEYS if k not in m))
    check(f"PACK_VERSION is one this template reads ({', '.join(wiring.PACK_VERSIONS)})",
          m.get("PACK_VERSION") in wiring.PACK_VERSIONS, m.get("PACK_VERSION", "not set"))
    check(f"MODULE_ID is {mid}, the folder's name", m.get("MODULE_ID") == mid, m.get("MODULE_ID", ""))
    web, tools, agents = wiring.has(m, "web"), wiring.has(m, "tools"), wiring.agents(m)
    if web:
        check(f"PUBLIC_URL_SETTING is {u}_PUBLIC_URL", wiring.public_url_setting(m) == f"{u}_PUBLIC_URL", m.get("PUBLIC_URL_SETTING", ""))
    accounts = wiring.accounts(m)
    check("SERVICE_ACCOUNTS has SERVICE" + (" and each agent's runtime" if agents else ""),
          m["SERVICE"] in accounts and all(a["runtime"] in accounts for a in agents), str(accounts))

    catalog = load(src / "module" / "permissions" / f"{mid}.yaml")
    actions = []
    if catalog:
        agent = catalog.get("agent", {})
        actions = agent.get("actions", [])
        check("the catalog is this module's: module and prefix are its ID", catalog.get("module") == mid and catalog.get("prefix") == mid)
        if tools:
            check("the catalog's agent block names actions, each the module's", bool(actions) and all(a.startswith(f"{mid}:") for a in actions), str(actions))
            check("the catalog's agent audience is its SERVICE", agent.get("audience") == m["SERVICE"], str(agent.get("audience")))
        keys = [p.get("key", "") for p in catalog.get("permissions", [])]
        check("every permission is the module's", all(k.startswith(f"{mid}:") for k in keys), str(keys))

    for a in agents:
        agent = load(src / "module" / "agents" / a["name"] / "agent.json")
        if agent:
            grants = agent.get("grants", {})
            check(f"its agent {a['name']} signs in as {a['runtime']}", grants.get("clientId") == a["runtime"], str(grants.get("clientId")))
            check(f"its agent {a['name']} reads its secret from {a['secret']}", f"${{{a['secret']}" in str(grants.get("clientSecret")))

    fragment = load(src / "module" / "clients.fragment.json") if (web or agents or (src / "module" / "clients.fragment.json").exists()) else None
    if fragment:
        runtimes = [r.get("name") for r in fragment.get("runtimes", [])]
        check("its OAuth clients name each agent's runtime", all(a["runtime"] in runtimes for a in agents), str(runtimes))
        text = json.dumps(fragment.get("clients", []))
        if web:
            check(f"its web client uses {u}_PUBLIC_URL and the hash of {u}_WEB_CLIENT_SECRET",
                  f"${{{u}_PUBLIC_URL}}" in text and f"${{sha256:{u}_WEB_CLIENT_SECRET}}" in text)

    dockerfile = src / "Dockerfile"
    check("its Dockerfile ships the pack at /module", dockerfile.exists() and re.search(r"COPY\s+(--\S+\s+)*module/?\s+/module", dockerfile.read_text()))
    return actions


def http(url, token=None, data=None, headers=None):
    headers = dict(headers or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)


def rpc(url, method, params=None, token=None, headers=None):
    return http(f"{url}/mcp", token, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, headers)


def service(mid, url, tools=True):
    code, body = http(f"{url}/readyz")
    check(f"it's ready at {url}", code == 200, f"{code} {body}" if code else f"{body}: make alone MODULE={mid}")
    if code != 200:
        return
    code, body = http(f"{url}/v1/module")
    check("/v1/module refuses a request without a token", code == 401, str(code))
    code, body = http(f"{url}/v1/module", "agent")
    check("/v1/module refuses an agent", code == 403, str(code))
    code, body = http(f"{url}/v1/module", "person")
    check("/v1/module gives a person its manifest, with action_prefix its ID",
          code == 200 and isinstance(body, dict) and body.get("id") == mid and body.get("action_prefix") == mid, f"{code} {body}")
    code, body = http(f"{url}/v1/access", "person")
    check("/v1/access tells a tenant admin they are one", code == 200 and isinstance(body, dict) and body.get("tenant_admin") is True, f"{code} {body}")

    if not tools:
        return
    code, body = rpc(url, "initialize", {"protocolVersion": "2025-06-18"})
    check("/mcp answers initialize", code == 200 and "result" in body, f"{code} {body}")
    code, body = rpc(url, "tools/list")
    tools = body.get("result", {}).get("tools", []) if code == 200 and isinstance(body, dict) else []
    check("/mcp lists its tools without a token", bool(tools), f"{code} {body}")
    for t in tools:
        name = t.get("name", "")
        check(f"{name}: named for the module and has an object schema",
              name.startswith((f"{mid}_", f"{mid.replace('-', '_')}_")) and t.get("inputSchema", {}).get("type") == "object", json.dumps(t)[:200])
        code, body = rpc(url, "tools/call", {"name": name, "arguments": {}}, "agent")
        result = body.get("result") if isinstance(body, dict) else None
        text = json.dumps(result)[:300]
        # An agent with the catalog's actions may call it; the arguments may not fit a tool that needs some.
        check(f"{name}: an agent with the catalog's actions may call it", code == 200 and result is not None
              and (not result.get("isError") or "invalid_arguments" in text), f"{code} {body if result is None else text}"
              + (" (is its action in the catalog's agent block?)" if code == 403 else ""))
    if tools:
        call = {"name": tools[0]["name"], "arguments": {}}
        check("a tool call is refused without a token", rpc(url, "tools/call", call)[0] == 401)
        check("a tool call is refused for a person's own token", rpc(url, "tools/call", call, "person")[0] == 403)
        check("a tool call is refused from a page", rpc(url, "tools/call", call, "agent", {"Origin": "http://page.example"})[0] == 403)


def main(argv):
    if len(argv) not in (1, 2):
        sys.exit(__doc__)
    mid = argv[0]
    folder, src, m = alone.module(mid)
    print(f"== {mid}: its pack, {src.relative_to(lib.ROOT)}/module/")
    pack(mid, folder, src, m)
    url = argv[1] if len(argv) == 2 else alone.url(mid)
    print(f"\n== {mid}: its service, {url}")
    service(mid, url.rstrip("/"), wiring.has(m, "tools"))
    lib.finish(f": {mid} keeps the module contract on its own; next, make up && make smoke")


if __name__ == "__main__":
    main(sys.argv[1:])

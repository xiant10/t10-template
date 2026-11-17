#!/usr/bin/env python3
"""Checks a running stack end to end. `make smoke` runs it.

On local, all of the steps below. On a server (dev, prod), only what Caddy publishes is
reachable and auth-server refuses dev mode, so it checks step 1 through the public addresses and
that auth-server serves its signing key there, then stops: signing in there needs a smoke account
of its own (docs/plan.md).

1. Every published service answers /readyz or /health, each module at its public address (one
   without `web` at its local port, and on a server not at all).
2. The bootstrap admin signs in (password grant: dev mode only).
3. Each module answers /v1/module and /v1/access for that person.
4. auth-server's landing data lists each module's web app for the tenant, and for each, a browser
   signs in as a person does: the app's /auth/login, auth-server's /v1/authorize and sign-in
   page, the app's /auth/callback, then the app's home for the tenant, /t/<tenant>/.
5. Every agent in the route document answers session.create by name through ai-gateway-agent,
   and each module agent answers a turn. With the scripted model and a module's
   compose/scripted.yml, that turn's tool call reaches the module through ai-gateway-tools.
6. Each part's hooks/smoke.py, if it has one, in part order. It runs in here, with check, http,
   compose, agent, open_session, turn, tool_calls, token, cfg and SCRIPTED, and for a module's,
   its module.env as `module` and its address as `url` (both None for any other part). A part's
   hooks/smoke.sh is one check, which passes when it exits 0.
7. With the scripted model (SCRIPTED=1), no identity header reached the model.
"""
import http.cookiejar as http_cookies
import json
import os
import pathlib
import runpy
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402
import wiring  # noqa: E402

ENV = os.environ.get("ENV", "local")
SCRIPTED = bool(os.environ.get("SCRIPTED"))
cfg = lib.settings(ENV)
secrets = lib.secret_values(ENV)
LOCAL = lib.shape(ENV) == "local"
port = lambda name: f"http://127.0.0.1:{cfg[name]}"
public = lambda name: cfg[name].rstrip("/")
AUTH = port("AUTH_PORT") if LOCAL else public("AUTH_PUBLIC_URL")
# Caddy's own CA signs *.localhost, which a test of the dev shape on this machine uses.
UNVERIFIED = ssl._create_unverified_context()


def module_url(m):
    """Where a module answers from here: its web app's public address, or else, on this machine,
    its local port. None for a module without `web` on a server, where Caddy doesn't publish it."""
    if wiring.has(m, "web"):
        return cfg[wiring.public_url_setting(m)].rstrip("/")
    return f"http://127.0.0.1:{cfg[wiring.upper(m['MODULE_ID']) + '_PORT']}" if LOCAL else None


MODULES = [(m, module_url(m), folder) for folder, _, m in lib.modules() if module_url(m)]
check = lib.check


def http(url, token=None, data=None, form=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    body = None
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
    elif data is not None:
        body = json.dumps(data).encode()
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        context = UNVERIFIED if (urllib.parse.urlsplit(url).hostname or "").endswith(".localhost") else None
        with urllib.request.urlopen(req, timeout=15, context=context) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]


def compose(*args):
    env = dict(os.environ, ENV=ENV)
    return subprocess.run([str(lib.PLATFORM / "scripts" / "compose.sh"), *args], capture_output=True, text=True, env=env)


def tool_calls(session, wait=30):
    """ai-gateway-tools' audit records for one agent session, waiting up to `wait` seconds."""
    seen = ""
    for _ in range(wait):
        seen = compose("exec", "-T", "ai-gateway-tools", "cat", "/var/lib/ai-gateway-tools/audit.jsonl").stdout
        if session in seen:
            break
        time.sleep(1)
    return [json.loads(line) for line in seen.splitlines() if session in line]


def agent(method, params=None, name=None, session=None):
    """One call to ai-gateway-agent as the admin: (status, its result, or the error)."""
    headers = {"Authorization": f"Bearer {token}", "content-type": "application/json", "Agent-Method": method}
    headers.update({k: v for k, v in (("Agent-Name", name), ("Agent-Session-Id", session)) if v})
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(port("AGENT_GATEWAY_PORT") + "/agent", data=body, headers=headers), timeout=15) as r:
            return r.status, json.load(r).get("result", {})
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]


def open_session(name, wait=30):
    """session.create with the agent `name`: its session ID, or the error. Retries while no
    replica is ready, as ai-gateway-agent takes a few seconds to see a newly published route."""
    for _ in range(wait):
        status, result = agent("session.create", name=name)
        if status == 200:
            return result.get("sessionId", "")
        if b"replica_unavailable" not in result:
            break
        time.sleep(1)
    return f"{status} {result}"


def turn(name, text, wait=60):
    """A turn with the agent `name`, as the admin: (its session, the messages once it replied),
    or ("", []) if no session opened."""
    session = open_session(name)
    if not session.startswith(name + "."):
        return "", []
    agent("session.prompt", {"input": text, "requestId": f"smoke-{int(time.time())}", "wait": False}, session=session)
    messages = []
    for _ in range(wait):
        time.sleep(1)
        status, result = agent("session.messages", session=session)
        messages = result.get("messages", []) if status == 200 else []
        if any(m.get("role") == "assistant" and m.get("stopReason") == "stop" for m in messages):
            break
    return session, messages


# 1. Health.
# Only what runs: a component that's off has no port or public address among the settings.
if LOCAL:
    up = [(name.removesuffix("_PORT").lower(), port(name) + path) for name, path in [
        ("AUTH_PORT", "/readyz"), ("WORKBENCH_PORT", "/readyz"), ("CONSOLE_PORT", "/readyz"),
        ("AGENT_CONTROL_PORT", "/readyz"), ("AUTOMATIONS_PORT", "/readyz"), ("COLLAB_PORT", "/readyz"),
        ("KNOWLEDGE_PORT", "/readyz"), ("AGENT_PI_PORT", "/readyz"),
        ("AGENT_TI_PORT", "/readyz"), ("LLM_GATEWAY_PORT", "/health"), ("AGENT_GATEWAY_PORT", "/health"),
        ("TOOLS_GATEWAY_PORT", "/health")] if name in cfg]
else:
    up = [(name.removesuffix("_PUBLIC_URL").lower(), public(name) + "/readyz")
          for name in ("AUTH_PUBLIC_URL", "WORKBENCH_PUBLIC_URL", "CONSOLE_PUBLIC_URL") if name in cfg]
up += [(m["MODULE_ID"], url + "/readyz") for m, url, _ in MODULES]
for name, url in up:
    try:
        status, _ = http(url)
    except OSError as e:
        status = str(e)
    check(f"{name} is up", status == 200, str(status))

if not LOCAL:
    status, body = http(AUTH + "/.well-known/jwks.json")
    check("auth-server serves its signing key at its public address", status == 200 and bool(body.get("keys")), f"{status} {body}")
    lib.finish(" (on a server: public addresses only)")

# 2. Sign in.
admin = os.environ.get("AUTH_SETUP_ADMIN", "admin@acme.example")
tenant = os.environ.get("AUTH_SETUP_TENANT_ID", "ten_acme")
status, body = http(AUTH + "/v1/token", form={"grant_type": "password", "client_id": "t10-mac-client", "username": admin,
                                              "password": secrets["AUTH_ADMIN_PASSWORD"], "tenant": tenant})
token = body.get("access_token") if status == 200 else None
check("admin signs in", bool(token), f"{status} {body}")
if not token:
    sys.exit(1)

# 3. Each module's contract.
for m, url, _ in MODULES:
    mid = m["MODULE_ID"]
    status, body = http(url + "/v1/module", token)
    check(f"{mid} serves its manifest", status == 200 and body.get("action_prefix") == mid, f"{status}")
    status, body = http(url + "/v1/access", token)
    check(f"{mid} sees the admin as tenant admin", status == 200 and body.get("tenant_admin") is True, f"{status} {body}")

# 4. Landing page.
status, body = http(AUTH + "/v1/me/homes", token)
apps = [a["id"] for t in (body.get("workbench", {}).get("tenants", []) if status == 200 else []) for a in t.get("apps", [])]
for m, _, _ in MODULES:
    if wiring.has(m, "web"):
        check(f"auth-server lists the {m['MODULE_ID']} app", m["MODULE_ID"] in apps, f"{status} {apps}")


def browser_sign_in(url):
    """A browser opening a module's web app and signing in: where it ends up, and its status."""
    jar = http_cookies.CookieJar()
    browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    home = f"/t/{urllib.parse.quote(tenant)}/"
    try:
        page = browser.open(url + "/auth/login?" + urllib.parse.urlencode({"next": home, "tenant": tenant}), timeout=15)
        signin = urllib.parse.urlsplit(page.geturl())
        if signin.path != "/v1/signin":
            return page.geturl(), page.status
        origin = f"{signin.scheme}://{signin.netloc}"
        form = {"name": admin, "password": secrets["AUTH_ADMIN_PASSWORD"],
                "next": urllib.parse.parse_qs(signin.query).get("next", ["/"])[0]}
        page = browser.open(urllib.request.Request(origin + "/v1/signin", data=urllib.parse.urlencode(form).encode(),
                                                   headers={"Origin": origin}), timeout=15)
        return page.geturl(), page.status
    except urllib.error.HTTPError as e:
        return e.geturl(), e.code
    except OSError as e:
        return str(e), 0


for m, url, _ in MODULES:
    if wiring.has(m, "web"):
        where, status = browser_sign_in(url)
        check(f"a browser signs in to the {m['MODULE_ID']} app and opens /t/{tenant}/",
              status == 200 and where == f"{url}/t/{urllib.parse.quote(tenant)}/", f"{status} at {where}")

# 5. Every agent in the route document is reachable by name through ai-gateway-agent, and each
# module's answers a turn, calling the module's tool with the scripted model.
routes = json.loads((lib.GENERATED / ENV / "agent-routes.json").read_text())
for name in sorted(routes["agents"]):
    sid = open_session(name)
    check(f"ai-gateway-agent routes {name}", sid.startswith(name + "."), sid)
for m, a in [(mod, a) for mod, _, _ in MODULES for a in wiring.agents(mod)]:
    # The module's ID in brackets: with several modules, the scripted model calls this one's tool.
    session, messages = turn(a["name"], f"What can you tell me about my access here? [{m['MODULE_ID']}]")
    replies = [x.get("text", "") for x in messages if x.get("role") == "assistant" and x.get("text")]
    check(f"the {a['title']} agent answers a turn", bool(replies), f"{messages}"[-300:] if session else "no session opened")
    if SCRIPTED and session and wiring.has(m, "tools") and m.get("SCRIPTED_TOOL") != "none":
        calls = tool_calls(session)
        check(f"its tool call reached {m['SERVICE']} through ai-gateway-tools",
              any(c.get("target", "").startswith(f"server:{m['MODULE_ID']}/") and c.get("outcome") == "ok" for c in calls), f"{calls}"[-300:])

# 6. Each part's own checks.
urls = {folder: url for _, url, folder in MODULES}
for part, hook in lib.hooks("smoke"):
    m = lib.module_of(part)
    if hook.suffix == ".py":
        runpy.run_path(str(hook), init_globals=dict(check=check, http=http, compose=compose, agent=agent, open_session=open_session, turn=turn, tool_calls=tool_calls,
                                                     token=token, cfg=cfg, SCRIPTED=SCRIPTED, module=m, url=urls.get(part)))
    else:
        r = subprocess.run(["sh", str(hook)], cwd=lib.ROOT, capture_output=True, text=True,
                           env=dict(os.environ, ENV=ENV, T10_PART=str(part.relative_to(lib.ROOT)), T10_MODULE=(m or {}).get("MODULE_ID", ""),
                                    T10_COMPOSE=str(lib.PLATFORM / "scripts" / "compose.sh")))
        check(str(hook.relative_to(lib.ROOT)), r.returncode == 0, (r.stdout + r.stderr).strip()[-400:])

# 7. No identity header reached the model.
if SCRIPTED:
    out = compose("exec", "-T", "fake-model", "node", "-e",
                  "fetch('http://127.0.0.1:8080/seen').then(r=>r.text()).then(t=>process.stdout.write(t))").stdout
    check("no identity header reached the model", out.strip() == "[]", out)

lib.finish()

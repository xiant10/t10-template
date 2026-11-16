#!/usr/bin/env python3
"""Checks a running stack end to end. `make smoke` runs it.

On local, all of the steps below. On a server (dev, prod), only what Caddy publishes is
reachable and auth-server refuses dev mode, so it checks step 1 through the public addresses and
that auth-server serves its signing key there, then stops: signing in there needs a smoke account
of its own (docs/plan.md).

1. Every published service answers /readyz or /health, each module at its public address.
2. The bootstrap admin signs in (password grant: dev mode only).
3. Each module answers /v1/module and /v1/access for that person.
4. auth-server's landing data lists each module's app for the tenant.
5. Every agent in the route document answers session.create by name through ai-gateway-agent.
6. Each module's modules/<id>/hooks/smoke.py, if it has one, such as a turn through its agent.
   It runs in here, with check, http, compose, tool_calls, token, cfg, SCRIPTED, the module's
   module.env as `module`, and its address as `url`.
7. With the scripted model (SCRIPTED=1), no identity header reached the model.
"""
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

ENV = os.environ.get("ENV", "local")
SCRIPTED = bool(os.environ.get("SCRIPTED"))
cfg = lib.settings(ENV)
secrets = lib.read_env(lib.secrets_file(ENV))
LOCAL = lib.shape(ENV) == "local"
port = lambda name: f"http://127.0.0.1:{cfg[name]}"
public = lambda name: cfg[name].rstrip("/")
AUTH = port("AUTH_PORT") if LOCAL else public("AUTH_PUBLIC_URL")
# Caddy's own CA signs *.localhost, which a test of the dev shape on this machine uses.
UNVERIFIED = ssl._create_unverified_context()
MODULES = [(m, cfg[m["PUBLIC_URL_SETTING"]].rstrip("/"), folder) for folder, _, m in lib.modules()]
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
    return subprocess.run([str(lib.ROOT / "scripts" / "compose.sh"), *args], capture_output=True, text=True, env=env)


def tool_calls(session, wait=30):
    """ai-gateway-tools' audit records for one agent session, waiting up to `wait` seconds."""
    seen = ""
    for _ in range(wait):
        seen = compose("exec", "-T", "ai-gateway-tools", "cat", "/var/lib/ai-gateway-tools/audit.jsonl").stdout
        if session in seen:
            break
        time.sleep(1)
    return [json.loads(line) for line in seen.splitlines() if session in line]


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
    check(f"auth-server lists the {m.get('AGENT_TITLE', m['MODULE_ID'])} app", m["MODULE_ID"] in apps, f"{status} {apps}")

# 5. Every agent in the route document is reachable by name through ai-gateway-agent.
routes = json.loads((lib.GENERATED / ENV / "agent-routes.json").read_text())
gateway = port("AGENT_GATEWAY_PORT") + "/agent"
for agent in sorted(routes["agents"]):
    req = urllib.request.Request(gateway, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "session.create", "params": {}}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "content-type": "application/json",
                                          "Agent-Method": "session.create", "Agent-Name": agent})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            sid = json.load(r).get("result", {}).get("sessionId", "")
    except urllib.error.HTTPError as e:
        sid = f"{e.code} {e.read()[:200]}"
    check(f"ai-gateway-agent routes {agent}", sid.startswith(agent + "."), sid)

# 6. Each module's own checks.
for m, url, folder in MODULES:
    hook = folder / "hooks" / "smoke.py"
    if hook.exists():
        runpy.run_path(str(hook), init_globals=dict(check=check, http=http, compose=compose, tool_calls=tool_calls, token=token, cfg=cfg,
                                                     SCRIPTED=SCRIPTED, module=m, url=url))

# 7. No identity header reached the model.
if SCRIPTED:
    out = compose("exec", "-T", "fake-model", "node", "-e",
                  "fetch('http://127.0.0.1:8080/seen').then(r=>r.text()).then(t=>process.stdout.write(t))").stdout
    check("no identity header reached the model", out.strip() == "[]", out)

lib.finish()

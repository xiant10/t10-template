"""The standard wiring every module gets, worked out from its pack's module.env.

Every module plugs into the foundation the same way: a database and login, its accounts in
auth-server, its agent copied into agent-ti, its service with the settings the module contract
gives it, and the foundation services that wait for it. Writing that out in each module's folder
would freeze it there, where a template update can't reach it, so scripts/render.py writes it
into the bundle on every run instead, as generated/<env>/modules/<id>/standard/<name>.yml, read
just before the module's own compose/<name>.yml. A module's folder then holds only what's
particular to it, and can override anything here (Compose merges its files over these).

    base      every environment: the one-shots <id>-db and <id>-seed, its agents, its services
    local     local: its port published on 127.0.0.1, and for code in the project, built from src/
    server    a server (dev, prod): rotated logs and a memory limit, as every service there
    build     DEV=1, for a module in its own repo: built from its checkout in src/
    scripted  SCRIPTED=1: the tool the scripted model calls on a user turn

And its standard secrets (which lib.inventory() adds before the module's own secrets.json) and its
standard OAuth web client, agent runtimes and runtime_grants (clients(), which scripts/render.py
adds before an optional clients.fragment.json in the pack and modules/<id>/clients.json).

What module.env says, beside the keys docs/module.md lists:

    PACK_VERSION      the pack format it's written for; PACK_VERSIONS are the ones this template reads
    CAPABILITIES      what it has, of web, tools, agent and database (capabilities(), below); each
                      one adds its wiring, secrets, clients, checks and smoke steps, and nothing else does
    AGENTS            its agents, for `agent` (agents(), below); AGENT_ACTIONS_<AGENT> may restrict
                      one agent to a subset of the module's tool actions
    SERVICES          more services beside SERVICE, from the same image, such as a worker
    REQUIRES          foundation components or other modules it needs (lib.modules checks them)
    SCRIPTED_TOOL     the tool SCRIPTED=1 calls (default <id>_whoami; "none" for none)

Names follow from the ID and the accounts: an account's secret is its name in capitals with
_SECRET (t10-crm: T10_CRM_SECRET), and its first agent's agent.json reads its runtime's as
<ID>_AUTH_CLIENT_SECRET, any other's as <AGENT>_AUTH_CLIENT_SECRET.
"""
import json
import re

# The pack formats this template reads. A pack without PACK_VERSION was written before v0.6.0,
# and is 1. A new format adds its number here, and reads the older ones as they are.
PACK_VERSIONS = ("1",)
CAPABILITIES = ("web", "tools", "agent", "database")


def upper(name):
    return name.upper().replace("-", "_")


def account_secret(account):
    """The secret of an auth-server service account: t10-crm's is T10_CRM_SECRET."""
    return upper(account) + "_SECRET"


def pack_version(m):
    return m.get("PACK_VERSION", "1")


def capabilities(m):
    """What a module has, from CAPABILITIES. A pack without it (written before v0.6.0) has web and
    tools, a database unless DATABASE=false, and an agent when AGENT names one."""
    if "CAPABILITIES" in m:
        if "DATABASE" in m:
            raise SystemExit(f"{m['MODULE_ID']}: module.env has CAPABILITIES and DATABASE: drop DATABASE, and say database in CAPABILITIES or not")
        have = {c.strip() for c in m["CAPABILITIES"].split(",") if c.strip()}
    else:
        have = {"web", "tools"}
        have |= {"database"} if m.get("DATABASE", "true").lower() != "false" else set()
        have |= {"agent"} if m.get("AGENTS") or m.get("AGENT") else set()
    unknown = have - set(CAPABILITIES)
    if unknown:
        raise SystemExit(f"{m['MODULE_ID']}: CAPABILITIES has {', '.join(sorted(unknown))}; it takes {', '.join(CAPABILITIES)}")
    return have


def has(m, capability):
    return capability in capabilities(m)


def has_database(m):
    return has(m, "database")


def public_url_setting(m):
    """The setting that holds its web app's public address: PUBLIC_URL_SETTING, or <ID>_PUBLIC_URL."""
    return m.get("PUBLIC_URL_SETTING") or upper(m["MODULE_ID"]) + "_PUBLIC_URL"


def agents(m):
    """Its agents, for `agent`: [{name, title, runtime, secret, actions}]. AGENTS lists them (a
    pack before v0.6.0 has one, AGENT). Each one's title is AGENT_TITLE_<AGENT>, else its name in
    title case; its runtime account AGENT_RUNTIME_<AGENT>, else agent-ti-<agent>; the first one's
    may be AGENT_TITLE and AGENT_RUNTIME. `secret` is the variable its agent.json reads its
    runtime's secret from on agent-ti: <ID>_AUTH_CLIENT_SECRET for the first,
    <AGENT>_AUTH_CLIENT_SECRET for any other. `actions` is None (meaning all of the module's tool
    actions), or the subset AGENT_ACTIONS_<AGENT> names."""
    if not has(m, "agent"):
        return []
    names = [a.strip() for a in (m.get("AGENTS") or m.get("AGENT") or "").split(",") if a.strip()]
    if not names:
        raise SystemExit(f"{m['MODULE_ID']}: CAPABILITIES has agent, so AGENTS names at least one")
    out = []
    for i, name in enumerate(names):
        k, first = upper(name), i == 0
        scoped = [x.strip() for x in m[f"AGENT_ACTIONS_{k}"].split(",") if x.strip()] if f"AGENT_ACTIONS_{k}" in m else None
        out.append({"name": name,
                    "title": m.get(f"AGENT_TITLE_{k}") or (first and m.get("AGENT_TITLE")) or name.replace("-", " ").title(),
                    "runtime": m.get(f"AGENT_RUNTIME_{k}") or (first and m.get("AGENT_RUNTIME")) or f"agent-ti-{name}",
                    "secret": f"{upper(m['MODULE_ID'])}_AUTH_CLIENT_SECRET" if first else f"{k}_AUTH_CLIENT_SECRET",
                    "actions": scoped})
    return out


def services(m):
    """Its services: SERVICE, which keeps the module contract, then SERVICES, more from the same
    image (a module's compose/base.yml gives each its command), such as a worker."""
    more = [s.strip() for s in m.get("SERVICES", "").split(",") if s.strip() and s.strip() != m["SERVICE"]]
    return [m["SERVICE"], *more]


def accounts(m):
    """Its accounts in auth-server: SERVICE, each agent's runtime, and any more in SERVICE_ACCOUNTS."""
    extra = [a.strip() for a in m.get("SERVICE_ACCOUNTS", "").split(",") if a.strip()]
    return list(dict.fromkeys([m["SERVICE"], *(a["runtime"] for a in agents(m)), *extra]))


def clients(m):
    """A module's standard additions to auth-server's clients.yaml, from its CAPABILITIES and
    AGENTS: its web client (for `web`), each agent's runtime (for `agent`), and in runtime_grants
    the foundation runtimes that may run its tools (for `tools`). A pack's clients.fragment.json
    or modules/<id>/clients.json can add more or change these."""
    mid, u, service = m["MODULE_ID"], upper(m["MODULE_ID"]), m["SERVICE"]
    title = agents(m)[0]["title"] if agents(m) else m.get(f"AGENT_TITLE_{u}") or m.get("AGENT_TITLE") or mid.replace("-", " ").title()
    out = {}
    if has(m, "web"):
        out["clients"] = [{
            "id": f"{service}-web", "name": title, "type": "confidential", "tenant": "required",
            "redirect_uris": [f"${{{public_url_setting(m)}}}/auth/callback"],
            "secret_sha256": f"${{sha256:{u}_WEB_CLIENT_SECRET}}", "idle_ttl": "12h", "absolute_ttl": "168h",
        }]
    if has(m, "agent"):
        out["runtimes"] = [{
            "name": a["runtime"], "optional": True, "actions": ["agent:use", "knowledge:read"],
            "audiences": [a["runtime"], "t10-knowledge", "ai-gateway-tools", "ai-gateway-llm"],
            "tool_audience": "ai-gateway-tools", "model_audience": "ai-gateway-llm",
        } for a in agents(m)]
    if has(m, "tools"):
        out["runtime_grants"] = {"runtimes": ["agent-pi", "agent-ti", "t10-livekit-agent", "t10-automations"]}
    return out


def compose(m, name, in_project, src=None, configured=(), init_db=None):
    """A module's standard Compose file for one name (base, local, server, build, scripted) as a
    dict, or None. configured: the services with settings in the bundle, env/<service>.env.
    init_db: relative path in the bundle of the module's own init-db.sh, if it has one."""
    mid, u, service, port = m["MODULE_ID"], upper(m["MODULE_ID"]), m["SERVICE"], m["PORT"]
    db = mid.replace("-", "_")
    built = {"image": f"{service}:dev", "build": f"../../modules/{mid}/src"}
    if in_project:
        # Code in the project builds with the template's kit, platform/kit/go/ (its go.mod's replace).
        built["build"] = {"context": f"../../modules/{mid}/src", "additional_contexts": {"kit": "../../platform/kit/go"}}
    more = services(m)[1:]
    if name == "local":
        svc = {"ports": [f"127.0.0.1:${{{u}_PORT}}:{port}"]}
        return {"services": {service: {**(built if in_project else {}), **svc}, **{s: dict(built) for s in more if in_project}}}
    if name == "build":
        return None if in_project else {"services": {s: dict(built) for s in services(m)}}
    if name == "scripted":
        if not has(m, "tools") or m.get("SCRIPTED_TOOL") == "none":
            return None
        tool = m.get("SCRIPTED_TOOL") or f"{mid}_whoami"
        return {"services": {"fake-model": {"environment": {f"SCRIPTED_TOOL_{u}": json.dumps({"tool": tool, "args": {}})}}}}
    if name == "server":
        # As every service on a server (foundation/compose/server.yml): rotated logs, a memory limit.
        limits = {"logging": {"driver": "local", "options": {"max-size": "${LOG_MAX_SIZE}", "max-file": "${LOG_MAX_FILES}"}},
                  "mem_limit": "${MEM_LIMIT}"}
        names = [*services(m), f"{mid}-seed"] + ([f"{mid}-db"] if has_database(m) else [])
        return {"services": {n: dict(limits) for n in names}}
    if name != "base":
        return None

    services_ = {}

    def runs(svc):
        return {
            "image": f"${{T10_{u}}}",
            "restart": "unless-stopped",
            **({"env_file": f"./env/{svc}.env"} if svc in configured else {}),
            # Its secrets come from secrets(), below, as every service's do.
            "environment": {
                "AUTH_ISSUER": "${AUTH_PUBLIC_URL}",
                "AUTH_URL": "http://auth-server:8081",
                **({f"{u}_PUBLIC_URL": f"${{{u}_PUBLIC_URL}}"} if has(m, "web") else {}),
                # Turns go through ai-gateway-agent, which routes Agent-Name: <AGENT> to agent-ti.
                "AGENT_URL": "http://ai-gateway-agent:18090/agent",
            },
            "read_only": True,
            "tmpfs": ["/tmp"],
            "depends_on": {"auth-server": {"condition": "service_healthy"}},
        }

    app = runs(service)
    # Only SERVICE keeps the module contract, so only it has /readyz.
    app["healthcheck"] = {"test": ["CMD", "wget", "-q", "--spider", f"http://127.0.0.1:{port}/readyz"],
                          "interval": "5s", "timeout": "3s", "retries": 12}
    app = {k: app[k] for k in ("image", "restart", "env_file", "environment", "read_only", "tmpfs", "healthcheck", "depends_on") if k in app}
    others = {s: runs(s) for s in more}

    if has_database(m):
        # Its database and login, made if missing and the password set, on every start, so a
        # module joins a stack whose database already exists. Its own init-db.sh, if it has one,
        # runs after, with the same environment.
        vols = ["./platform/foundation/module-init-db.sh:/init-db.sh:ro"]
        if init_db:
            vols.append(f"./{init_db}:/module-init-db.sh:ro")
        services_[f"{mid}-db"] = {
            "image": "${POSTGRES_IMAGE}",
            "entrypoint": ["sh", "-c", "sh /init-db.sh && { [ ! -f /module-init-db.sh ] || sh /module-init-db.sh; }"],
            "environment": {"PGHOST": "postgres", "PGUSER": "t10", "MODULE_DB": db},
            "volumes": vols,
            "depends_on": {"postgres": {"condition": "service_healthy"}},
        }
        for svc in (app, *others.values()):
            svc["depends_on"][f"{mid}-db"] = {"condition": "service_completed_successfully"}

    # Its accounts in auth-server, SERVICE_ACCOUNTS (upstream U2: auth-setup's list is fixed).
    names = accounts(m)
    services_[f"{mid}-seed"] = {
        "image": "${T10_AUTH_SERVER}",
        "entrypoint": ["/bin/sh", "-c", "set -eu\n" + "".join(
            f'AUTHCTL_SERVICE_SECRET="$${account_secret(a)}" authctl service-add --if-missing --name={a}\n' for a in names)],
        "depends_on": {"seed": {"condition": "service_completed_successfully"}},
    }
    services_["auth-server"] = {"depends_on": {f"{mid}-seed": {"condition": "service_completed_successfully"}}}

    if agents(m):
        # Its agents, which t10-agents copies into agent-ti's agents; each runtime's secret, which
        # its agent.json reads, is in secrets().
        services_["t10-agents"] = {"volumes": [f"./modules/{mid}/pack/agents/{a['name']}:/module-agents/{a['name']}:ro" for a in agents(m)]}

    services_[service] = app
    services_.update(others)
    # The tools gateway lists its /mcp for the harnesses; workbench reads its manifest.
    for waiting, needs in (("ai-gateway-tools", "tools"), ("workbench", "web")):
        if has(m, needs):
            services_[waiting] = {"depends_on": {service: {"condition": "service_healthy"}}}
    return {"services": services_}


def secrets(m):
    """A module's standard secrets, in the form of foundation/secrets.json, each with the
    services that get it (`env`), and its uses of the foundation's POSTGRES_PASSWORD. SERVICES
    get what SERVICE gets, but for its web app's."""
    mid, u, service = m["MODULE_ID"], upper(m["MODULE_ID"]), m["SERVICE"]
    db = mid.replace("-", "_")
    out = []
    pg = {f"{mid}-seed": {"DATABASE_URL": "postgres://t10:${POSTGRES_PASSWORD}@postgres:5432/auth?sslmode=disable"}}
    if has_database(m):
        pg[f"{mid}-db"] = {"PGPASSWORD": "${POSTGRES_PASSWORD}"}
        url = f"postgres://{db}:${{{u}_DB_PASSWORD}}@postgres:5432/{db}?sslmode=disable"
        out.append({"name": f"{u}_DB_PASSWORD", "generate": "hex32", "consumers": [*services(m), f"postgres role {db}"],
                    "rotate": f"Change the value, then make up: {mid}-db sets the role's password, and {service} restarts with it.", "rotation": "replace",
                    "env": {f"{mid}-db": {"MODULE_DB_PASSWORD": f"${{{u}_DB_PASSWORD}}", f"{u}_DB_PASSWORD": f"${{{u}_DB_PASSWORD}}"},
                            **{s: {"DATABASE_URL": url} for s in services(m)}}})
    out.append({"name": "POSTGRES_PASSWORD", "env": pg})
    runtimes = {a["runtime"]: a for a in agents(m)}
    for a in accounts(m):
        agent = runtimes.get(a)
        user = f"agent-ti ({agent['name']} agent)" if agent else service if a == service else a
        roll = "agent-ti" if agent else service if a == service else "what uses it"
        ref = f"${{{account_secret(a)}}}"
        env = {f"{mid}-seed": {account_secret(a): ref}}
        if a == service:
            env.update({s: {"AUTH_CLIENT_SECRET": ref} for s in services(m)})
        if agent:
            env["agent-ti"] = {agent["secret"]: ref}
        out.append({"name": account_secret(a), "generate": "hex32", "consumers": [user, f"auth-server account {a}"],
                    "rotate": f"authctl service-rotate --name={a}, roll {roll}, then service-finish.", "rotation": f"account:{a}", "env": env})
    if has(m, "web"):
        out.append({"name": f"{u}_WEB_CLIENT_SECRET", "generate": "hex32",
                    "consumers": [f"{service} (AUTH_WEB_CLIENT_SECRET)", "secret_sha256 in clients.yaml"],
                    "rotate": f"Change, re-render clients.yaml, roll auth-server and {service} together.", "rotation": "replace",
                    "env": {service: {"AUTH_WEB_CLIENT_SECRET": f"${{{u}_WEB_CLIENT_SECRET}}"}}})
        out.append({"name": f"{u}_SESSION_KEY", "generate": "b64key", "consumers": [service],
                    "rotate": f"Change and roll {service}. Everyone signs in again.", "rotation": "replace",
                    "env": {service: {f"{u}_SESSION_KEY": f"${{{u}_SESSION_KEY}}"}}})
    return out


def to_yaml(value, indent=0):
    """A Compose file as YAML text: maps and lists in block style, multi-line strings as literal
    blocks, and other strings plain where that's safe."""
    pad = "  " * indent
    lines = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines += [f"{pad}{k}:", to_yaml(v, indent + 1)]
            else:
                lines.append(f"{pad}{k}: {scalar(v, indent + 1)}")
    else:
        for v in value:
            if isinstance(v, dict) and v:
                first, *rest = to_yaml(v, indent + 1).split("\n")
                lines += [f"{pad}- {first.lstrip()}", *rest]
            else:
                lines.append(f"{pad}- {scalar(v, indent + 1)}")
    return "\n".join(lines)


PLAIN = re.compile(r"[A-Za-z_./@-][A-Za-z0-9_./:@=-]*")
KEYWORDS = {"true", "false", "null", "yes", "no", "on", "off", "~"}


def scalar(v, indent):
    """One value: plain when YAML reads it back as the same string, else quoted as JSON."""
    if isinstance(v, str) and "\n" in v:
        pad = "  " * indent
        return "|\n" + "\n".join(pad + line for line in v.rstrip("\n").split("\n"))
    if isinstance(v, str) and PLAIN.fullmatch(v) and v.lower() not in KEYWORDS:
        return v
    return json.dumps(v)

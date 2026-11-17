"""The standard wiring every module gets, worked out from its pack's module.env.

Every module plugs into the foundation the same way: a database and login, its accounts in
auth-server, its agent copied into agent-ti, its service with the settings the module contract
gives it, and the foundation services that wait for it. Writing that out in each module's folder
would freeze it there, where a template update can't reach it, so scripts/render.py writes it
into the bundle on every run instead, as generated/<env>/modules/<id>/standard/<name>.yml, read
just before the module's own compose/<name>.yml. A module's folder then holds only what's
particular to it, and can override anything here (Compose merges its files over these).

    base      every environment: the one-shots <id>-db and <id>-seed, its agent, its service
    local     local: its port published on 127.0.0.1, and for code in the project, built from src/
    server    a server (dev, prod): rotated logs and a memory limit, as every service there
    build     DEV=1, for a module in its own repo: built from its checkout in src/

And its standard secrets, which lib.inventory() adds before the module's own secrets.json.

What module.env says, beside the keys docs/module.md lists:

    DATABASE=false    no database: no <id>-db, no <ID>_DB_PASSWORD, no DATABASE_URL
    AGENT= (empty)    no agent: nothing for t10-agents or agent-ti

Names follow from the ID and the accounts: an account's secret is its name in capitals with
_SECRET (t10-crm: T10_CRM_SECRET), and its agent.json reads its runtime's as <ID>_AUTH_CLIENT_SECRET.
"""
import json
import re


def upper(name):
    return name.upper().replace("-", "_")


def account_secret(account):
    """The secret of an auth-server service account: t10-crm's is T10_CRM_SECRET."""
    return upper(account) + "_SECRET"


def has_database(m):
    return m.get("DATABASE", "true").lower() != "false"


def accounts(m):
    return [a for a in m.get("SERVICE_ACCOUNTS", m["SERVICE"]).split(",") if a]


def compose(m, name, in_project, src=None, env_file=True):
    """A module's standard Compose file for one name (base, local, build) as a dict, or None."""
    mid, u, service, port = m["MODULE_ID"], upper(m["MODULE_ID"]), m["SERVICE"], m["PORT"]
    db = mid.replace("-", "_")
    built = {"image": f"{service}:dev", "build": f"../../src/{src}"}
    if in_project:
        # Code in the project builds with the template's kit, kit/go/ (its go.mod's replace).
        built["build"] = {"context": f"../../src/{src}", "additional_contexts": {"kit": "../../kit/go"}}
    if name == "local":
        svc = {"ports": [f"127.0.0.1:${{{u}_PORT}}:{port}"]}
        return {"services": {service: {**(built if in_project else {}), **svc}}}
    if name == "build":
        return None if in_project else {"services": {service: built}}
    if name == "server":
        # As every service on a server (foundation/compose/server.yml): rotated logs, a memory limit.
        limits = {"logging": {"driver": "local", "options": {"max-size": "${LOG_MAX_SIZE}", "max-file": "${LOG_MAX_FILES}"}},
                  "mem_limit": "${MEM_LIMIT}"}
        names = [service, f"{mid}-seed"] + ([f"{mid}-db"] if has_database(m) else [])
        return {"services": {n: dict(limits) for n in names}}
    if name != "base":
        return None

    services = {}
    app = {
        "image": f"${{T10_{u}}}",
        "restart": "unless-stopped",
        **({"env_file": f"./env/{service}.env"} if env_file else {}),
        # Its secrets come from secrets(), below, as every service's do.
        "environment": {
            "AUTH_ISSUER": "${AUTH_PUBLIC_URL}",
            "AUTH_URL": "http://auth-server:8081",
            f"{u}_PUBLIC_URL": f"${{{u}_PUBLIC_URL}}",
            # Turns go through ai-gateway-agent, which routes Agent-Name: <AGENT> to agent-ti.
            "AGENT_URL": "http://ai-gateway-agent:18090/agent",
        },
        "read_only": True,
        "tmpfs": ["/tmp"],
        "healthcheck": {"test": ["CMD", "wget", "-q", "--spider", f"http://127.0.0.1:{port}/readyz"],
                        "interval": "5s", "timeout": "3s", "retries": 12},
        "depends_on": {"auth-server": {"condition": "service_healthy"}},
    }

    if has_database(m):
        # Its database and login, made if missing and the password set, on every start, so a
        # module joins a stack whose database already exists. Its own init-db.sh, if it has one,
        # runs after, with the same environment.
        services[f"{mid}-db"] = {
            "image": "${POSTGRES_IMAGE}",
            "entrypoint": ["sh", "-c", "sh /init-db.sh && { [ ! -f /module-init-db.sh ] || sh /module-init-db.sh; }"],
            "environment": {"PGHOST": "postgres", "PGUSER": "t10", "MODULE_DB": db},
            "volumes": ["./foundation/module-init-db.sh:/init-db.sh:ro"],
            "depends_on": {"postgres": {"condition": "service_healthy"}},
        }
        app["depends_on"][f"{mid}-db"] = {"condition": "service_completed_successfully"}

    # Its accounts in auth-server, SERVICE_ACCOUNTS (upstream U2: auth-setup's list is fixed).
    names = accounts(m)
    services[f"{mid}-seed"] = {
        "image": "${T10_AUTH_SERVER}",
        "entrypoint": ["/bin/sh", "-c", "set -eu\n" + "".join(
            f'AUTHCTL_SERVICE_SECRET="$${account_secret(a)}" authctl service-add --if-missing --name={a}\n' for a in names)],
        "depends_on": {"seed": {"condition": "service_completed_successfully"}},
    }
    services["auth-server"] = {"depends_on": {f"{mid}-seed": {"condition": "service_completed_successfully"}}}

    agent = m.get("AGENT")
    if agent:
        # Its agent, which t10-agents copies into agent-ti's agents; its runtime's secret, which
        # its agent.json reads, is in secrets().
        services["t10-agents"] = {"volumes": [f"./modules/{mid}/pack/agents/{agent}:/module-agents/{agent}:ro"]}

    services[service] = app
    # The tools gateway lists its /mcp for the harnesses; workbench reads its manifest.
    for waiting in ("ai-gateway-tools", "workbench"):
        services[waiting] = {"depends_on": {service: {"condition": "service_healthy"}}}
    return {"services": services}


def secrets(m):
    """A module's standard secrets, in the form of foundation/secrets.json, each with the
    services that get it (`env`), and its uses of the foundation's POSTGRES_PASSWORD."""
    mid, u, service = m["MODULE_ID"], upper(m["MODULE_ID"]), m["SERVICE"]
    db = mid.replace("-", "_")
    out = []
    pg = {f"{mid}-seed": {"DATABASE_URL": "postgres://t10:${POSTGRES_PASSWORD}@postgres:5432/auth?sslmode=disable"}}
    if has_database(m):
        pg[f"{mid}-db"] = {"PGPASSWORD": "${POSTGRES_PASSWORD}"}
        out.append({"name": f"{u}_DB_PASSWORD", "generate": "hex32", "consumers": [service, f"postgres role {db}"],
                    "rotate": f"Change the value, then make up: {mid}-db sets the role's password, and {service} restarts with it.", "rotation": "replace",
                    "env": {f"{mid}-db": {"MODULE_DB_PASSWORD": f"${{{u}_DB_PASSWORD}}", f"{u}_DB_PASSWORD": f"${{{u}_DB_PASSWORD}}"},
                            service: {"DATABASE_URL": f"postgres://{db}:${{{u}_DB_PASSWORD}}@postgres:5432/{db}?sslmode=disable"}}})
    out.append({"name": "POSTGRES_PASSWORD", "env": pg})
    runtime = m.get("AGENT_RUNTIME") if m.get("AGENT") else None
    for a in accounts(m):
        user = f"agent-ti ({mid} agent)" if a == runtime else service if a == service else a
        roll = "agent-ti" if a == runtime else service if a == service else "what uses it"
        ref = f"${{{account_secret(a)}}}"
        env = {f"{mid}-seed": {account_secret(a): ref}}
        if a == service:
            env[service] = {"AUTH_CLIENT_SECRET": ref}
        if a == runtime:
            env["agent-ti"] = {f"{u}_AUTH_CLIENT_SECRET": ref}
        out.append({"name": account_secret(a), "generate": "hex32", "consumers": [user, f"auth-server account {a}"],
                    "rotate": f"authctl service-rotate --name={a}, roll {roll}, then service-finish.", "rotation": f"account:{a}", "env": env})
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

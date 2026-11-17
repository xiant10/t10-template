#!/usr/bin/env python3
"""Writes generated/<env>/, the deployment bundle: everything Compose needs for that
environment, with nothing pointing back into the checkout, so it runs here or on the host
`make deploy` copies it to. scripts/compose.sh runs it before every command.

    scripts/render.py ENV

    compose.sh         docker compose on this bundle; scripts/compose.sh and the host both run it
    foundation/, modules/<id>/, site/
                       each part's compose/, config/, scripted/, pack/ and init-db.sh, copied;
                       for a module built from src/, its pack from src/<SRC>/module/, and its
                       agent.json given what its tools need (below)
    modules/<id>/standard/<name>.yml
                       each module's standard wiring for base, local and build, from its
                       module.env (scripts/wiring.py), read just before its own compose/<name>.yml
    env/<service>.env  a service's settings: every part's config/<service>.env, then every
                       part's config/<env>/<service>.env, later lines winning
    versions.env       every part's versions.env merged: foundation's pins, each module's, site's overrides
    secrets/<service>.env
                       a service's secrets, mode 600: each `env` in the parts' secrets.json, filled in
                       from the environment's values; secrets.yml has each service read its own
    secrets.env        all of the environment's secrets, mode 600, only for a project's Compose files
                       that still write ${SECRET}
                       For a server environment, these two are written only with T10_BUNDLE_SECRETS=1,
                       which scripts/compose.sh and scripts/deploy.sh set while they need them; the
                       values are decrypted from site/secrets/<env>.enc.env in memory (lib.secrets_text)
    clients.yaml       auth-server's clients: foundation/clients.json, each component's clients.json
                       and each pack's clients.fragment.json, with ${VAR}, "${sha256:VAR}" and
                       "${bool:VAR}" filled in

A module says what its agent tools need once, in its catalog's agent block (lib.grant). Every
place that needs it gets it from there: the harnesses' MODULE_GRANT_* lists, its own runtimes
and the foundation runtimes its runtime_grants names in clients.yaml, and its agent's grants.
    permissions/       every catalog auth-server loads: foundation/permissions/ and each pack's
    agent-routes.json  foundation/agent-routes.json, each component's, and a pool and an agent for
                       each module's agent
    modules.env        MODULE_* variables, appended to the foundation's lists in foundation/compose/base.yml:
                       what each component's component.env adds, then each module's
    Caddyfile          on a server (dev, prod): one site per public address, from each part's
                       public.json and each module's PUBLIC_URL_SETTING, proxied to its service

Files are rewritten in place and folders kept, so running containers see changes through their
bind mounts. Anything else in the folder is removed, so it holds exactly what's listed.

Addresses in modules.env are Compose service names; Kubernetes will have its own.
upstream U3: clients.yaml merging goes away once auth-server reads one file per module.
upstream U7: the foundation would read the catalogs' agent blocks itself.
"""
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402
import wiring  # noqa: E402

WHOLE = re.compile(r"^\$\{(sha256|bool):([A-Z0-9_]+)\}$")
REFERENCE = re.compile(r"\$\{([A-Z0-9_]+)(?::-((?:[^{}]|\$\{[^{}]*\})*))?\}")
PLAIN = re.compile(r"[A-Za-z0-9_./:@+=,?&%-]*")


def resolve(template, values):
    """A secret's `env` value with ${NAME}, ${NAME:-default} and ${A:-${B}} filled in, as Compose
    would; a name with no value and no default is empty."""
    return REFERENCE.sub(lambda m: values.get(m.group(1)) or (resolve(m.group(2), values) if m.group(2) is not None else ""), template)


def secret_files(values, raw):
    """{service: file text}: each service's secrets, as env lines. A value that is one secret as it
    is keeps the quoting it has in site/secrets/ (a PEM key's \\n escapes); any other is quoted
    when it needs to be."""
    out = {}
    for service, variables in sorted(lib.secret_env().items()):
        lines = [f"# {service}'s secrets, written by scripts/render.py from the parts' secrets.json. Don't edit."]
        for var, template in variables.items():
            whole = REFERENCE.fullmatch(template)
            if whole and raw.get(whole.group(1)) and values.get(whole.group(1)):
                lines.append(f"{var}={raw[whole.group(1)]}")
                continue
            value = resolve(template, values)
            lines.append(f"{var}={value}" if PLAIN.fullmatch(value) else f"{var}='{value}'")
        out[service] = "\n".join(lines) + "\n"
    return out
INLINE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def fill(value, env, where):
    if isinstance(value, dict):
        return {k: fill(v, env, f"{where}.{k}") for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [fill(v, env, where) for v in value]
    if not isinstance(value, str):
        return value

    def need(name):
        if not env.get(name):
            raise SystemExit(f"{where}: {name} is not set")
        return env[name]

    m = WHOLE.match(value)
    if m:
        kind, name = m.groups()
        if kind == "sha256":
            return hashlib.sha256(need(name).encode()).hexdigest()
        raw = need(name).lower()
        if raw not in ("true", "false"):
            raise SystemExit(f"{where}: {name} must be true or false, not {raw!r}")
        return raw == "true"
    return INLINE.sub(lambda m: need(m.group(1)), value)


def merge_clients(base, fragment, source):
    for kind, key in (("clients", "id"), ("runtimes", "name")):
        have = {item[key] for item in base[kind]}
        for item in fragment.get(kind, []):
            if item[key] in have:
                raise SystemExit(f"{source}: {kind} {item[key]!r} is already defined")
            base[kind].append(item)
    grants = fragment.get("runtime_grants")
    if grants:
        by_name = {r["name"]: r for r in base["runtimes"]}
        off = lib.runtimes_off()
        for name in grants["runtimes"]:
            if name in off:
                continue
            if name not in by_name:
                raise SystemExit(f"{source}: runtime_grants names {name!r}, which isn't a runtime")
            for field in ("actions", "audiences"):
                for value in grants.get(field, []):
                    if value not in by_name[name][field]:
                        by_name[name][field].append(value)
    return base


def add_grant(holder, actions, audience, joined=False):
    """Adds actions and audience to holder's "actions" and "audiences", lists or, with joined,
    comma-separated strings. Whether anything was added."""
    added = False
    for field, want in (("actions", actions), ("audiences", [audience])):
        have = holder.get(field, "" if joined else [])
        have = [v for v in have.split(",") if v] if joined else list(have)
        new = [v for v in want if v not in have]
        if new:
            holder[field] = ",".join(have + new) if joined else have + new
            added = True
    return added


def add_route(doc, m):
    """A module's agent as a pool of its own on agent-ti's replicas, so ai-gateway-agent routes
    it by name. Not a `hosts` entry under ti: t10-agent-control's router never places a hosted
    agent. The pool's audience is the agent's own runtime at auth-server, as each pool needs one."""
    agent = m["AGENT"]
    ti = doc["pools"]["ti"]
    doc["pools"][agent] = {"agent": agent, "state": "active", "harness": ti.get("harness", "ti"),
                           "audience": m["AGENT_RUNTIME"], "capabilities": ti["capabilities"],
                           "replicas": {name: url.rsplit("/agents/", 1)[0] + "/agents/" + agent for name, url in ti["replicas"].items()},
                           "tools_via_gateway": True}
    doc["agents"][agent] = {"title": m.get("AGENT_TITLE", agent), "open": True, "routes": [{"pool": agent}]}


def files_under(path, prefix=""):
    """{relative path: (bytes, mode)} for a file, or every file in a folder."""
    path = pathlib.Path(path)
    if path.is_file():
        return {prefix or path.name: (path.read_bytes(), path.stat().st_mode & 0o777)}
    return {str(pathlib.PurePosixPath(prefix, p.relative_to(path))): (p.read_bytes(), p.stat().st_mode & 0o777)
            for p in sorted(path.rglob("*")) if p.is_file() and p.name != ".DS_Store"}


def write(path, data, mode=0o644):
    """Writes only when the content changes, in place, so a bind mount of the file stays live.
    Folders are 755, so a container running as another user can read what's mounted from them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for d in [path.parent, *path.parent.parents]:
        if d == lib.GENERATED:
            break
        d.chmod(0o755)
    if not path.exists() or path.read_bytes() != data:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    path.chmod(mode)


def mirror(files, dest):
    """Makes the folder dest hold exactly files, as files_under returns them."""
    for rel, (data, mode) in files.items():
        write(dest / rel, data, mode)
    if dest.exists():
        for p in sorted(dest.rglob("*"), reverse=True):
            if p.is_file() and str(p.relative_to(dest).as_posix()) not in files:
                p.unlink()
            elif p.is_dir() and not any(p.iterdir()):
                p.rmdir()


def compose_files(names, standard):
    """The Compose files for these names, name by name and part by part, each module's standard
    file (scripts/wiring.py) just before its own, so its own can change anything in it."""
    out = []
    for name in names:
        for part in lib.parts():
            if (part, name) in standard:
                out.append(standard[part, name])
            if (part / "compose" / f"{name}.yml").exists():
                out.append((part / "compose" / f"{name}.yml").relative_to(lib.ROOT).as_posix())
    return out


def compose_script(env_name, standard):
    """generated/<env>/compose.sh. The bundle has the repo's layout, so paths are the same."""
    rel = lambda p: str(p.relative_to(lib.ROOT))
    env_files = ["versions.env", *map(rel, lib.settings_files(env_name)), "secrets.env", "modules.env"]
    files = " ".join(f"-f {f}" for f in compose_files(["base", *lib.layers(env_name)], standard) + ["secrets.yml"])
    lines = ["#!/bin/sh", f"# Written by scripts/render.py for ENV={env_name}. Don't edit.",
             "# docker compose on this bundle: each part's Compose files and settings, the pinned versions,",
             "# the secrets, and what modules add. Runs here, or on the host `make deploy` copies it to.",
             "set -eu", 'cd "$(dirname "$0")"', f"export T10_ENV={env_name} T10_SHAPE={lib.shape(env_name)}",
             f'files="{files}"']
    if lib.shape(env_name) == "local":
        for var, name in (("DEV", "build"), ("SCRIPTED", "scripted")):
            lines += [f'[ -z "${{{var}:-}}" ] || files="$files -f {f}"' for f in compose_files([name], standard)]
    else:
        lines.append('[ -z "${DEV:-}${SCRIPTED:-}" ] || { echo "DEV and SCRIPTED are for local only" >&2; exit 1; }')
    lines += ["# shellcheck disable=SC2086",
              "exec docker compose --project-directory . " + " ".join(f"--env-file {f}" for f in env_files) + ' $files "$@"']
    return "\n".join(lines) + "\n"


def merged_env(sources, merged):
    lines = ["# Written by scripts/render.py from these, later lines winning. Don't edit.",
             *(f"#   {f.relative_to(lib.ROOT)}" for f in sources), *(f"{k}={v}" for k, v in merged.items())]
    return ("\n".join(lines) + "\n").encode()


def service_env(service, env_name):
    """generated/<env>/env/<service>.env: its layers merged, so Compose reads one file."""
    layers = lib.service_layers(service, env_name)
    merged = {}
    for f in layers:
        merged.update(lib.read_env(f))
    return merged_env(layers, merged)


def caddyfile(settings):
    """Caddy's config: a site per public address, proxied to the service behind it. https
    addresses get a certificate (Let's Encrypt, or Caddy's own CA for *.localhost); wss is the
    same site for Caddy. Each address must be a whole host: no path, no two on one host."""
    routes = {}
    for part in lib.parts():
        if (part / "public.json").exists():
            routes.update({k: v for k, v in json.loads((part / "public.json").read_text()).items() if not k.startswith("_")})
    for _, _, m in lib.modules():
        routes[m["PUBLIC_URL_SETTING"]] = f"{m['SERVICE']}:{m['PORT']}"
    lines = ["# Written by scripts/render.py from each part's public addresses. Don't edit."]
    if settings.get("ACME_EMAIL"):
        lines += ["{", f"\temail {settings['ACME_EMAIL']}", "}"]
    seen = {}
    for name, upstream in sorted(routes.items()):
        if settings.get(name) == "TODO":
            lines += ["", f"# {name} is TODO, so it has no site yet."]
            continue
        url = urllib.parse.urlsplit(settings.get(name, ""))
        if url.scheme not in ("http", "https", "ws", "wss") or not url.hostname or url.path not in ("", "/"):
            raise SystemExit(f"{name}={settings.get(name)!r} must be a whole host, such as https://auth.example.com")
        site = ("" if url.scheme in ("https", "wss") else "http://") + url.netloc
        if site in seen:
            raise SystemExit(f"{name} and {seen[site]} are both {site}: give each its own host")
        seen[site] = name
        lines += ["", f"# {name}", f"{site} {{", f"\treverse_proxy {upstream}", "}"]
    return ("\n".join(lines) + "\n").encode()


def main(env_name):
    settings = lib.settings(env_name)
    if settings.get("TARGET", "compose") != "compose":
        raise SystemExit(f"{env_name}: TARGET={settings['TARGET']} isn't built yet, only compose (docs/plan.md)")
    values = {**settings, **lib.secret_values(env_name)}
    raw = lib.secret_values(env_name, raw=True)
    # A server's secrets go in its bundle only while a command needs them (scripts/compose.sh,
    # scripts/deploy.sh); otherwise its bundle holds none, so nothing decrypted stays here.
    with_secrets = lib.shape(env_name) == "local" or os.environ.get("T10_BUNDLE_SECRETS")
    if os.environ.get("SCRIPTED") and not values.get("LLM_API_KEY"):
        values["LLM_API_KEY"] = raw["LLM_API_KEY"] = "scripted"
    out = lib.GENERATED / env_name
    files = {}

    for part in lib.parts():
        rel = part.relative_to(lib.ROOT).as_posix()
        for name in lib.BUNDLED:
            if (part / name).exists():
                files.update(files_under(part / name, f"{rel}/{name}"))
    # A module built from src/ has its pack there; the bundle holds it where every pack is.
    for folder, pack, _ in lib.modules():
        if lib.in_project(folder):
            files.update(files_under(pack, f"{folder.relative_to(lib.ROOT).as_posix()}/pack"))
    for service in lib.services_configured(env_name):
        files[f"env/{service}.env"] = (service_env(service, env_name), 0o644)
    files["versions.env"] = (merged_env(lib.versions_files(), lib.versions()), 0o644)
    if with_secrets and lib.has_secrets(env_name):
        files["secrets.env"] = (lib.secrets_text(env_name).encode(), 0o600)
    # Each service's own secrets, and a Compose file that has it read them after its settings.
    overlay = {}
    for service, text in secret_files(values, raw).items():
        if with_secrets:
            files[f"secrets/{service}.env"] = (text.encode(), 0o600)
        overlay[service] = {"env_file": [{"path": f"./secrets/{service}.env"}]}
    files["secrets.yml"] = (("# Written by scripts/render.py: each service reads its own secrets. Don't edit.\n"
                             + wiring.to_yaml({"services": overlay}) + "\n").encode(), 0o644)

    # Each module's standard wiring, worked out from its module.env (scripts/wiring.py).
    standard = {}
    names = ["base", *lib.layers(env_name)] + (["build"] if lib.shape(env_name) == "local" else [])
    for folder, _, m in lib.modules():
        rel = folder.relative_to(lib.ROOT).as_posix()
        src = lib.source(folder).get("SRC")
        for name in names:
            doc = wiring.compose(m, name, lib.in_project(folder), src, f"env/{m['SERVICE']}.env" in files)
            if doc:
                path = f"{rel}/standard/{name}.yml"
                header = (f"# {m['MODULE_ID']}'s standard {name} wiring, written by scripts/render.py from its module.env\n"
                          f"# (scripts/wiring.py). Don't edit: {rel}/compose/{name}.yml can change anything here.\n")
                files[path] = ((header + wiring.to_yaml(doc) + "\n").encode(), 0o644)
                standard[folder, name] = path
    files["compose.sh"] = (compose_script(env_name, standard).encode(), 0o755)

    perms = files_under(lib.FOUNDATION / "permissions") if (lib.FOUNDATION / "permissions").exists() else {}
    perms = {k: v for k, v in perms.items() if k.endswith(".yaml")}

    clients = json.loads((lib.FOUNDATION / "clients.json").read_text())
    routes = json.loads((lib.FOUNDATION / "agent-routes.json").read_text())
    lists = {k: [] for k in ("GRANT_ACTIONS", "GRANT_AUDIENCES", "TOOL_SERVERS", "TOOL_MODULE_SERVERS",
                             "WORKBENCH_URLS", "APP_URLS")}
    for comp in lib.components():
        if (comp / "clients.json").exists():
            clients = merge_clients(clients, json.loads((comp / "clients.json").read_text()), comp / "clients.json")
        if (comp / "agent-routes.json").exists():
            extra = json.loads((comp / "agent-routes.json").read_text())
            for key in ("pools", "agents"):
                routes[key].update(extra.get(key, {}))
            routes["default_agent"] = extra.get("default_agent", routes["default_agent"])
        for key, value in lib.read_env(comp / "component.env").items():
            if key in lists:
                lists[key] += value.split(",")
    for folder, pack, m in lib.modules():
        mid, service, port = m["MODULE_ID"], m["SERVICE"], m["PORT"]
        actions, audience = lib.grant(pack, m)
        lists["GRANT_ACTIONS"] += actions
        lists["GRANT_AUDIENCES"].append(audience)
        lists["TOOL_SERVERS"].append(f"{mid}={audience}@http://{service}:{port}/mcp")
        lists["TOOL_MODULE_SERVERS"].append(mid)
        lists["WORKBENCH_URLS"].append(f"{mid}=http://{service}:{port}")
        lists["APP_URLS"].append(f"{mid}={settings[m['PUBLIC_URL_SETTING']]}")
        if m.get("AGENT"):
            add_route(routes, m)
            # The agent's own grant gets what its tools need, in the bundle's copy of its agent.json.
            path = f"{folder.relative_to(lib.ROOT).as_posix()}/pack/agents/{m['AGENT']}/agent.json"
            agent = json.loads(files[path][0])
            if "grants" in agent and add_grant(agent["grants"], actions, audience, joined=True):
                files[path] = ((json.dumps(agent, indent=2, ensure_ascii=False) + "\n").encode(), files[path][1])
        for f in sorted((pack / "permissions").glob("*.yaml")):
            if f.name in perms:
                raise SystemExit(f"{f.name} is in two catalogs")
            perms[f.name] = (f.read_bytes(), 0o644)
        fragment = pack / "clients.fragment.json"
        if fragment.exists():
            # Every runtime that runs its tools gets what they need: its own runtimes, and the
            # foundation's it names in runtime_grants.
            extra = json.loads(fragment.read_text())
            for runtime in extra.get("runtimes", []) + ([extra["runtime_grants"]] if "runtime_grants" in extra else []):
                add_grant(runtime, actions, audience)
            clients = merge_clients(clients, extra, fragment)

    files.update({f"permissions/{k}": v for k, v in perms.items()})
    clients = fill(clients, values, "clients")
    files["clients.yaml"] = (("# Written by scripts/render.py. Don't edit. JSON is YAML.\n"
                              + json.dumps(clients, indent=2, ensure_ascii=False) + "\n").encode(), 0o644)
    routes = {k: v for k, v in routes.items() if not k.startswith("_")}
    files["agent-routes.json"] = ((json.dumps(routes, indent=2) + "\n").encode(), 0o644)
    lines = ["# Written by scripts/render.py. Don't edit."]
    lines += [f"MODULE_{k}={','.join(dict.fromkeys(v))}" for k, v in lists.items()]
    # auth-server reads clients.yaml only at start, and Compose doesn't see a mounted file change,
    # so its hash is a variable on auth-server: a new client secret or module recreates it.
    lines.append("T10_CLIENTS_SHA=" + hashlib.sha256(files["clients.yaml"][0]).hexdigest()[:16])
    files["modules.env"] = (("\n".join(lines) + "\n").encode(), 0o644)
    if lib.shape(env_name) != "local":
        files["Caddyfile"] = (caddyfile(settings), 0o644)
    mirror(files, out)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])

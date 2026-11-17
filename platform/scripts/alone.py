#!/usr/bin/env python3
"""`make alone`: one module's service by itself, with its own Postgres and no foundation, so its
contract can be checked before it joins the stack (docs/integration.md, gate 2).

    scripts/alone.py ID up      # build it from src/ and start it; prints its address
    scripts/alone.py ID down    # stop it and delete its data
    scripts/alone.py ID url     # its address

It runs as its own Compose project, <PROJECT_NAME>-alone-<id>, written to generated/alone/<id>/,
on 127.0.0.1 at a port free when it starts (kept in generated/alone/<id>/port, and printed),
so it runs beside the full stack and any other project's. The service gets
T10_STANDALONE=1 and no AUTH_ISSUER: the kit (t10kit/module.NewAccess) then accepts "Bearer
person" as a tenant admin and "Bearer agent" as an agent with the actions its catalog grants.
Its database password is throwaway; nothing here is a real secret.
"""
import json
import os
import pathlib
import socket
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402
import wiring  # noqa: E402

PASSWORD = "alone"
B64_KEY = "YWxvbmUtYWxvbmUtYWxvbmUtYWxvbmUtYWxvbmUtYWw="


def module(mid):
    """(folder, src folder, module.env) for a module whose code is in modules/<id>/src/, here or checked out."""
    folder = lib.MODULES / mid
    if not (folder / "source.env").exists():
        sys.exit(f"modules/{mid}/source.env is missing: make new-module ID={mid}")
    src = lib.src_of(folder)
    if not (src / "module" / "module.env").exists():
        sys.exit(f"{src.relative_to(lib.ROOT)}/module/module.env is missing" + ("" if lib.in_project(folder) else ": make clone"))
    return folder, src, lib.read_env(src / "module" / "module.env")


def port_file(mid):
    return lib.GENERATED / "alone" / mid / "port"


def port(mid, fresh=False):
    """Its port on this machine: the one it last started on, or with fresh, the one it last
    started on if that's still free, else any free one."""
    f = port_file(mid)
    if f.exists() and not fresh:
        return int(f.read_text())
    if f.exists() and free(int(f.read_text())):
        return int(f.read_text())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def free(p):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", p))
            return True
        except OSError:
            return False


def url(mid):
    if not port_file(mid).exists():
        sys.exit(f"{mid} hasn't run alone yet: make alone MODULE={mid}")
    return f"http://127.0.0.1:{port(mid)}"


def write(mid, at=0):
    """generated/alone/<id>/compose.yml, published at port at (0 for the one it last used)."""
    folder, src, m = module(mid)
    # Never started: any port does for `down`, which publishes nothing.
    at = at or (port(mid) if port_file(mid).exists() else 1)
    u, service, db = wiring.upper(mid), m["SERVICE"], mid.replace("-", "_")
    out = lib.GENERATED / "alone" / mid
    out.mkdir(parents=True, exist_ok=True)
    # Its own settings, as the stack would merge them, without the foundation's.
    settings = {}
    for f in (folder / "config" / f"{service}.env", lib.SITE / "config" / f"{service}.env",
              folder / "config" / "local" / f"{service}.env", lib.SITE / "config" / "local" / f"{service}.env"):
        settings.update(lib.read_env(f))
    (out / f"{service}.env").write_text("".join(f"{k}={v}\n" for k, v in settings.items()))
    # Any secrets the module declares in its pack or folder get throwaway values here.
    extra_env = {}
    for sf in (src / "module" / "secrets.json", folder / "secrets.json"):
        if sf.exists():
            for entry in json.loads(sf.read_text()).get("secrets", []):
                val = B64_KEY if entry.get("generate") == "b64key" else PASSWORD
                for k, tpl in entry.get("env", {}).get(service, {}).items():
                    extra_env[k] = tpl.replace(f"${{{entry['name']}}}", val)
    pg = lib.versions()["POSTGRES_IMAGE"]
    services = {
        "postgres": {"image": pg, "tmpfs": ["/var/lib/postgresql/data"],
                     "environment": {"POSTGRES_USER": "t10", "POSTGRES_PASSWORD": PASSWORD, "POSTGRES_DB": "auth"},
                     "healthcheck": {"test": ["CMD-SHELL", "pg_isready -h localhost -U t10 -d auth"], "interval": "2s", "retries": 30}},
        service: {
            "image": f"{service}:dev",
            "build": {"context": str(src), "additional_contexts": {"kit": str(lib.PLATFORM / "kit" / "go")}},
            "env_file": f"./{service}.env",
            "environment": {"T10_STANDALONE": "1", f"{u}_PUBLIC_URL": f"http://127.0.0.1:{at}",
                            f"{u}_SESSION_KEY": B64_KEY, "AUTH_WEB_CLIENT_SECRET": PASSWORD, **extra_env},
            "ports": [f"127.0.0.1:{at}:{m['PORT']}"],
            "read_only": True, "tmpfs": ["/tmp"],
            "healthcheck": {"test": ["CMD", "wget", "-q", "--spider", f"http://127.0.0.1:{m['PORT']}/readyz"],
                            "interval": "2s", "timeout": "3s", "retries": 30},
            "depends_on": {"postgres": {"condition": "service_healthy"}},
        },
    }
    if wiring.has_database(m):
        init = [f"{lib.FOUNDATION / 'module-init-db.sh'}:/init-db.sh:ro"]
        for init_sh in (folder / "init-db.sh", src / "module" / "init-db.sh"):
            if init_sh.exists():
                init.append(f"{init_sh}:/module-init-db.sh:ro")
                break
        services[f"{mid}-db"] = {
            "image": pg, "entrypoint": ["sh", "-c", "sh /init-db.sh && { [ ! -f /module-init-db.sh ] || sh /module-init-db.sh; }"],
            "environment": {"PGHOST": "postgres", "PGUSER": "t10", "PGPASSWORD": PASSWORD, "MODULE_DB": db,
                            "MODULE_DB_PASSWORD": PASSWORD, f"{u}_DB_PASSWORD": PASSWORD},
            "volumes": init, "depends_on": {"postgres": {"condition": "service_healthy"}}}
        services[service]["environment"]["DATABASE_URL"] = f"postgres://{db}:{PASSWORD}@postgres:5432/{db}?sslmode=disable"
        services[service]["depends_on"][f"{mid}-db"] = {"condition": "service_completed_successfully"}
    doc = {"name": f"{lib.settings('local')['PROJECT_NAME']}-alone-{mid}", "services": services}
    (out / "compose.yml").write_text("# Written by scripts/alone.py. Don't edit.\n" + wiring.to_yaml(doc) + "\n")
    return out


def compose(mid, *args, at=0):
    out = write(mid, at)
    flags = [a for a in args if a in ("--progress", "quiet")]
    args = [a for a in args if a not in flags]
    return subprocess.run(["docker", "compose", *flags, "--project-directory", str(out), "-f", str(out / "compose.yml"), *args],
                          cwd=lib.ROOT).returncode


def main(argv):
    if len(argv) != 2 or argv[1] not in ("up", "down", "url"):
        sys.exit(__doc__)
    mid, action = argv
    if action == "url":
        print(url(mid))
    elif action == "up":
        quiet = ["--progress", "quiet"] if os.environ.get("QUIET") else []
        compose(mid, "--progress", "quiet", "down", "--remove-orphans")  # so its last port counts as free
        at = port(mid, fresh=True)
        port_file(mid).parent.mkdir(parents=True, exist_ok=True)
        port_file(mid).write_text(f"{at}\n")
        if compose(mid, *quiet, "up", "-d", "--build", "--wait", "--wait-timeout", "120", "--remove-orphans", at=at) != 0:
            sys.exit(f"{mid} didn't start alone; its logs: docker compose -p {lib.settings('local')['PROJECT_NAME']}-alone-{mid} logs")
        print(f"{mid} runs alone at {url(mid)}: Bearer person and Bearer agent are accepted. make contract MODULE={mid} checks it.")
    else:
        sys.exit(compose(mid, "down", "-v", "--remove-orphans"))


if __name__ == "__main__":
    os.chdir(lib.ROOT)
    main(sys.argv[1:])

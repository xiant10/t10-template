#!/usr/bin/env python3
"""`make alone`: one module's service by itself, with its own Postgres and no foundation, so its
contract can be checked before it joins the stack (docs/integration.md, gate 2).

    scripts/alone.py ID up      # build it from src/ and start it; prints its address
    scripts/alone.py ID down    # stop it and delete its data
    scripts/alone.py ID url     # its address

It runs as its own Compose project, <PROJECT_NAME>-alone-<id>, written to generated/alone/<id>/,
on 127.0.0.1 at its local port + 10000, so it runs beside the full stack. The service gets
T10_STANDALONE=1 and no AUTH_ISSUER: the kit (t10kit/module.NewAccess) then accepts "Bearer
person" as a tenant admin and "Bearer agent" as an agent with the actions its catalog grants.
Its database password is throwaway; nothing here is a real secret.
"""
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402
import wiring  # noqa: E402

PASSWORD = "alone"


def module(mid):
    """(folder, src folder, module.env) for a module whose code is in src/, here or checked out."""
    folder = lib.MODULES / mid
    if not (folder / "source.env").exists():
        sys.exit(f"modules/{mid}/source.env is missing: make new-module ID={mid}")
    src = lib.ROOT / "src" / lib.source(folder)["SRC"]
    if not (src / "module" / "module.env").exists():
        sys.exit(f"{src.relative_to(lib.ROOT)}/module/module.env is missing" + ("" if lib.in_project(folder) else ": make clone"))
    return folder, src, lib.read_env(src / "module" / "module.env")


def port(m):
    return int(lib.settings("local")[wiring.upper(m["MODULE_ID"]) + "_PORT"]) + 10000


def url(mid):
    return f"http://127.0.0.1:{port(module(mid)[2])}"


def write(mid):
    folder, src, m = module(mid)
    u, service, db = wiring.upper(mid), m["SERVICE"], mid.replace("-", "_")
    out = lib.GENERATED / "alone" / mid
    out.mkdir(parents=True, exist_ok=True)
    # Its own settings, as the stack would merge them, without the foundation's.
    settings = {}
    for f in (folder / "config" / f"{service}.env", folder / "config" / "local" / f"{service}.env"):
        settings.update(lib.read_env(f))
    (out / f"{service}.env").write_text("".join(f"{k}={v}\n" for k, v in settings.items()))
    pg = lib.versions()["POSTGRES_IMAGE"]
    services = {
        "postgres": {"image": pg, "tmpfs": ["/var/lib/postgresql/data"],
                     "environment": {"POSTGRES_USER": "t10", "POSTGRES_PASSWORD": PASSWORD, "POSTGRES_DB": "auth"},
                     "healthcheck": {"test": ["CMD-SHELL", "pg_isready -h localhost -U t10 -d auth"], "interval": "2s", "retries": 30}},
        service: {
            "image": f"{service}:dev",
            "build": {"context": str(src), "additional_contexts": {"kit": str(lib.ROOT / "kit" / "go")}},
            "env_file": f"./{service}.env",
            "environment": {"T10_STANDALONE": "1", f"{u}_PUBLIC_URL": f"http://127.0.0.1:{port(m)}",
                            f"{u}_SESSION_KEY": "YWxvbmUtYWxvbmUtYWxvbmUtYWxvbmUtYWxvbmUtYWw=", "AUTH_WEB_CLIENT_SECRET": PASSWORD},
            "ports": [f"127.0.0.1:{port(m)}:{m['PORT']}"],
            "read_only": True, "tmpfs": ["/tmp"],
            "healthcheck": {"test": ["CMD", "wget", "-q", "--spider", f"http://127.0.0.1:{m['PORT']}/readyz"],
                            "interval": "2s", "timeout": "3s", "retries": 30},
            "depends_on": {"postgres": {"condition": "service_healthy"}},
        },
    }
    if wiring.has_database(m):
        init = [f"{lib.FOUNDATION / 'module-init-db.sh'}:/init-db.sh:ro"]
        if (folder / "init-db.sh").exists():
            init.append(f"{folder / 'init-db.sh'}:/module-init-db.sh:ro")
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


def compose(mid, *args):
    out = write(mid)
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
        if compose(mid, *quiet, "up", "-d", "--build", "--wait", "--wait-timeout", "120", "--remove-orphans") != 0:
            sys.exit(f"{mid} didn't start alone; its logs: docker compose -p {lib.settings('local')['PROJECT_NAME']}-alone-{mid} logs")
        print(f"{mid} runs alone at {url(mid)}: Bearer person and Bearer agent are accepted. make contract MODULE={mid} checks it.")
    else:
        sys.exit(compose(mid, "down", "-v", "--remove-orphans"))


if __name__ == "__main__":
    os.chdir(lib.ROOT)
    main(sys.argv[1:])

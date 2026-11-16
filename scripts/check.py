#!/usr/bin/env python3
"""`make check`: what can be checked without a running stack.

1. Each module's folder is named for it, and its pack/ matches the pack in its pinned image
   (skipped if that image has none yet).
2. The environment's secrets are complete, and no prod value is a dev default.
3. No secret's name is set in any part's config/.
4. Grants agree, as the foundation's check-module-agents.py requires: the actions in each
   catalog's agent block are in its module.env, in its agent's own grant, and in every
   runtime clients.yaml gives its tools to.
5. On a server (dev, prod, and any built on them), no setting is left TODO.
6. Compose renders, and the bundle in generated/<env>/ mounts nothing from outside itself, so
   `make deploy` can copy it to a host as it is.
"""
import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402

ENV = os.environ.get("ENV", "local")
failures = []


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"\n     {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def run(*cmd, **env):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=lib.ROOT, env=dict(os.environ, **env))


# 1. Packs. Render first, so clients.yaml below is current.
run(sys.executable, "-I", "-B", "scripts/render.py", ENV)
for folder in sorted(lib.MODULES.iterdir()) if lib.MODULES.exists() else []:
    if folder.is_dir() and not (folder / "pack" / "module.env").exists():
        print(f"skip modules/{folder.name}: no pack yet, so not part of the stack (make sync-module MODULE={folder.name})")
for folder, _, m in lib.modules():
    check(f"modules/{folder.name} is named for its MODULE_ID", folder.name == m.get("MODULE_ID"), m.get("MODULE_ID", "not set"))
    r = run("scripts/sync-module.sh", "--check", MODULE=folder.name)
    if "Could not find the file /module" in r.stderr:
        print(f"skip modules/{folder.name}/pack: its pinned image has no pack yet")
    else:
        check(f"modules/{folder.name}/pack matches its pinned image", r.returncode == 0, (r.stdout + r.stderr).strip()[-400:])

# 2. Secrets.
allow = ["--allow-empty=LLM_API_KEY"] if os.environ.get("SCRIPTED") else []
r = run(sys.executable, "-I", "-B", "scripts/secrets.py", "check", ENV, *allow)
check(f"secrets for {ENV} are complete", r.returncode == 0, r.stderr.strip())

# 3. No secrets among settings.
names = {s["name"] for s in lib.inventory()}
settings_files = [p for part in lib.parts() for p in (part / "config").rglob("*.env")]
leaks = [f"{p.relative_to(lib.ROOT)}: {k}" for p in settings_files for k in lib.read_env(p) if k in names]
check("no secret is set among settings", not leaks, "; ".join(leaks))

# 4. Grants.
clients_file = lib.GENERATED / ENV / "clients.yaml"
runtimes = {r["name"]: r for r in json.loads(clients_file.read_text().split("\n", 1)[1])["runtimes"]} if clients_file.exists() else {}
for folder, pack, m in lib.modules():
    catalog = json.loads((pack / "permissions" / f"{m['MODULE_ID']}.yaml").read_text())
    want, audience = set(catalog["agent"]["actions"]), catalog["agent"]["audience"]
    check(f"{folder.name}: module.env grants what the catalog's agent block needs",
          want <= set(m["GRANT_ACTIONS"].split(",")), f"{sorted(want)} vs {m['GRANT_ACTIONS']}")
    grants = json.loads((pack / "agents" / m["AGENT"] / "agent.json").read_text())["grants"]
    check(f"{folder.name}: its agent's own grant holds them and the audience",
          want <= set(grants["actions"].split(",")) and audience in grants["audiences"].split(","), str(grants))
    fragment = json.loads((pack / "clients.fragment.json").read_text())
    names = [n for n in fragment["runtime_grants"]["runtimes"] if n not in lib.runtimes_off()] + [r["name"] for r in fragment["runtimes"]]
    bad = [n for n in names if n not in runtimes or not want <= set(runtimes[n]["actions"]) or audience not in runtimes[n]["audiences"]]
    check(f"{folder.name}: every runtime that runs its tools holds its grant in clients.yaml", not bad, f"missing in {bad}")

# 5. Prod placeholders.
if lib.shape(ENV) != "local":
    todo = [f"settings: {k}" for k, v in lib.settings(ENV).items() if v == "TODO"]
    todo += [f"{f.stem}: {k}" for f in sorted((lib.GENERATED / ENV / "env").glob("*.env"))
             for k, v in lib.read_env(f).items() if v == "TODO"]
    check(f"no TODO left in {ENV}'s settings (set them in site/config/{ENV}/)", not todo, "; ".join(todo))

# 6. Compose.
r = run("scripts/compose.sh", "config", "--format", "json")
check("Compose renders", r.returncode == 0, r.stderr.strip()[-400:])
if r.returncode == 0:
    bundle = f"{lib.GENERATED / ENV}/"
    outside = sorted({f"{name}: {v['source']}" for name, s in json.loads(r.stdout)["services"].items()
                      for v in s.get("volumes", []) if v.get("type") == "bind" and not v["source"].startswith(bundle)})
    check(f"generated/{ENV}/ mounts nothing from outside itself", not outside, "; ".join(outside))

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)

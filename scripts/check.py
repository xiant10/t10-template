#!/usr/bin/env python3
"""`make check`: what can be checked without a running stack.

1. Each module's folder is named for it, and its pack/ matches the pack in its pinned image
   (skipped if that image has none yet). A module built from src/ has no copy to compare.
2. The environment's secrets are complete, and no prod value is a dev default.
3. No secret's name is set in any part's config/, and no Compose file writes one: each
   service gets its own from the parts' secrets.json (a project's own file only warns).
4. Grants agree, as the foundation's check-module-agents.py requires: the actions in each
   catalog's agent block reached the harnesses, its agent's own grant, and every runtime
   clients.yaml gives its tools to. render.py puts them there; this catches a pack it can't.
5. On a server (dev, prod, and any built on them), no setting or image pin is left TODO: a
   module built from src/ needs `make release` first.
6. Compose renders, and the bundle in generated/<env>/ mounts nothing from outside itself, so
   `make deploy` can copy it to a host as it is. On a server, every service rotates its logs and
   has a memory limit.
7. In a project with a `template` git remote, a warning for each template file it edited,
   since `make template-update` may conflict there. Never a failure.
"""
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402

ENV = os.environ.get("ENV", "local")
check = lib.check


def run(*cmd, **env):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=lib.ROOT, env=dict(os.environ, **env))


# 1. Packs. Render first, so clients.yaml below is current.
run(sys.executable, "-I", "-B", "scripts/render.py", ENV)
for folder in sorted(lib.MODULES.iterdir()) if lib.MODULES.exists() else []:
    if folder.is_dir() and not (lib.pack_of(folder) / "module.env").exists():
        how = f"{lib.pack_of(folder).relative_to(lib.ROOT)}/module.env is missing" if lib.in_project(folder) \
            else f"make sync-module MODULE={folder.name}"
        print(f"skip modules/{folder.name}: no pack yet, so not part of the stack ({how})")
for folder, _, m in lib.modules():
    check(f"modules/{folder.name} is named for its MODULE_ID", folder.name == m.get("MODULE_ID"), m.get("MODULE_ID", "not set"))
    if lib.in_project(folder):
        continue
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

# 3b. No secret written into a Compose file: each service gets its own from secrets.json's
# `env`. A template file fails; a project's warns, since it still works through secrets.env.
written = []
for part in lib.parts():
    for f in sorted((part / "compose").glob("*.yml")) if (part / "compose").exists() else []:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            for ref in re.findall(r"\$\{([A-Z0-9_]+)", line):
                if ref in names and not line.lstrip().startswith("#"):
                    written.append((part, f"{f.relative_to(lib.ROOT)}:{n}: {ref}"))
check("no template Compose file writes a secret", not [w for p, w in written if p.is_relative_to(lib.FOUNDATION)],
      "; ".join(w for p, w in written if p.is_relative_to(lib.FOUNDATION)))
for part, where in written:
    if not part.is_relative_to(lib.FOUNDATION):
        print(f"warn {where} writes a secret into Compose: give it an `env` in that part's secrets.json instead (docs/guide.md#secrets)")

# 4. Grants. A module says what its agent tools need once, in its catalog's agent block, and
# render.py gives it out; this checks that it reached every place in the bundle.
bundle = lib.GENERATED / ENV
clients_file = bundle / "clients.yaml"
runtimes = {r["name"]: r for r in json.loads(clients_file.read_text().split("\n", 1)[1])["runtimes"]} if clients_file.exists() else {}
module_lists = lib.read_env(bundle / "modules.env")
for folder, pack, m in lib.modules():
    actions, audience = lib.grant(pack, m)
    want = set(actions)
    check(f"{folder.name}: the harnesses hold what its tools need",
          want <= set(module_lists.get("MODULE_GRANT_ACTIONS", "").split(","))
          and audience in module_lists.get("MODULE_GRANT_AUDIENCES", "").split(","), f"{sorted(want)}, {audience}")
    if m.get("AGENT"):
        agent = bundle / folder.relative_to(lib.ROOT) / "pack" / "agents" / m["AGENT"] / "agent.json"
        grants = json.loads(agent.read_text()).get("grants", {})
        check(f"{folder.name}: its agent's own grant holds them and the audience",
              want <= set(grants.get("actions", "").split(",")) and audience in grants.get("audiences", "").split(","), str(grants))
    fragment = json.loads((pack / "clients.fragment.json").read_text())
    names = [n for n in fragment.get("runtime_grants", {}).get("runtimes", []) if n not in lib.runtimes_off()]
    names += [r["name"] for r in fragment.get("runtimes", [])]
    bad = [n for n in names if n not in runtimes or not want <= set(runtimes[n]["actions"]) or audience not in runtimes[n]["audiences"]]
    check(f"{folder.name}: every runtime that runs its tools holds its grant in clients.yaml", not bad, f"missing in {bad}")

# 5. Prod placeholders.
if lib.shape(ENV) != "local":
    todo = [f"settings: {k}" for k, v in lib.settings(ENV).items() if v == "TODO"]
    todo += [f"{f.stem}: {k}" for f in sorted((lib.GENERATED / ENV / "env").glob("*.env"))
             for k, v in lib.read_env(f).items() if v == "TODO"]
    check(f"no TODO left in {ENV}'s settings (set them in site/config/{ENV}/)", not todo, "; ".join(todo))
    unpinned = [k for k, v in lib.versions().items() if v == "TODO"]
    check(f"every image {ENV} runs is pinned (make release MODULE=<id> for one built from src/)", not unpinned, ", ".join(unpinned))
    # A module built from src/ runs its released image there, but its pack comes from src/, so
    # both must be the same commit.
    for folder, _, m in lib.modules():
        if not lib.in_project(folder):
            continue
        src = f"src/{lib.source(folder)['SRC']}"
        pin = lib.versions().get("T10_" + m["MODULE_ID"].upper().replace("-", "_"), "")
        tag = re.search(r":sha-([0-9a-f]+)@", pin)
        released = run("git", "rev-parse", "--verify", "-q", f"{tag.group(1)}^{{commit}}").stdout.strip() if tag else ""
        last = run("git", "log", "-1", "--format=%H", "--", src).stdout.strip()
        dirty = run("git", "status", "--porcelain", "--", src).stdout.strip()
        check(f"{m['MODULE_ID']}: its pinned image is {src} as committed", pin == "TODO" or (released == last and not dirty),
              f"{src} changed since its image was released: make release MODULE={m['MODULE_ID']}")

# 6. Compose.
r = run("scripts/compose.sh", "config", "--format", "json")
check("Compose renders", r.returncode == 0, r.stderr.strip()[-400:])
if r.returncode == 0:
    bundle = f"{lib.GENERATED / ENV}/"
    outside = sorted({f"{name}: {v['source']}" for name, s in json.loads(r.stdout)["services"].items()
                      for v in s.get("volumes", []) if v.get("type") == "bind" and not v["source"].startswith(bundle)})
    check(f"generated/{ENV}/ mounts nothing from outside itself", not outside, "; ".join(outside))
    if lib.shape(ENV) != "local":
        bare = sorted(name for name, s in json.loads(r.stdout)["services"].items()
                      if not s.get("mem_limit") or not s.get("logging", {}).get("options", {}).get("max-size"))
        check(f"every service on {ENV} rotates its logs and has a memory limit", not bare,
              "add them in that part's compose/server.yml, as foundation/compose/server.yml does: " + ", ".join(bare))

# 7. Template files edited in this project.
base = run("git", "merge-base", "HEAD", "template/main")
if base.returncode == 0:
    edited = run("git", "diff", "--name-only", base.stdout.strip(), "--", ".", ":!README.md", ":!modules", ":!site", ":!src").stdout.split()
    for f in edited:
        print(f"warn {f} is a template file, edited here, so template updates may conflict: change it in the template instead, or for a setting, override it from site/")

lib.finish()

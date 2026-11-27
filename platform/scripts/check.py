#!/usr/bin/env python3
"""`make check`: what can be checked without a running stack.

1. Each module's folder is named for it, and its pack/ matches the pack in its pinned image
   (skipped if that image has none yet). A module built from modules/<id>/src/ has no copy to compare.
2. The environment's secrets are complete, and no prod value is a dev default.
3. No secret's name is set in any part's config/, and no Compose file writes one: each
   service gets its own from the parts' secrets.json (a project's own file only warns).
4. Grants agree, as the foundation's check-module-agents.py requires: for each module with
   tools, the actions in its catalog's agent block reached the harnesses, each of its agents' own
   grant, and every runtime clients.yaml gives its tools to. render.py puts them there; this
   catches a pack it can't. A module whose pack has an ontology (module/ontology.json, its
   published core descriptor) has generated tools, and each one's grant action is in that
   block: <id>:read for <id>_describe, _search and _get, <id>:propose for <id>_propose, and
   <id>:act for <id>_act, which it has when an action is at tier undoable.
5. On a server (dev, prod, and any built on them), no setting or image pin is left TODO: a
   module built from modules/<id>/src/ needs `make release` first. Every image runs by digest
   there, never a tag such as `latest` that can move under it.
6. Compose renders, and the bundle in generated/<env>/ mounts nothing from outside itself, so
   `make deploy` can copy it to a host as it is. On a server, every service rotates its logs and
   has a memory limit. With TARGET=k8s, its Kubernetes objects build with kustomize, and no
   secret's value is in them (scripts/kube.py).
7. Each part's hooks/check.py, run in here with check, ENV, bundle and run, and as `module`
   its module.env for a module's; or hooks/check.sh, one check that passes when it exits 0.
1b. A warning for each module whose go.mod requires an older t10-modkit than the template pins
   (T10_MODKIT in platform/foundation/versions.env). Never a failure.
8. In a project with a `template` git remote, a warning for each template file it edited
   (anything outside lib.OWNED), since `make template-update` may conflict there. Never a failure.
"""
import json
import os
import pathlib
import re
import runpy
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402
import wiring  # noqa: E402

ENV = os.environ.get("ENV", "local")
check = lib.check


def run(*cmd, **env):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=lib.ROOT, env=dict(os.environ, **env))


# 1. Packs. Render first, so clients.yaml below is current; nothing else can be checked without it.
r = run(sys.executable, "-I", "-B", "platform/scripts/render.py", ENV)
hint = "\n     (a new module's secrets are made by make up, or make secrets-init)" if "is not set" in r.stderr else ""
check(f"the bundle for {ENV} renders", r.returncode == 0, r.stderr.strip()[-400:] + hint)
if r.returncode != 0:
    lib.finish()
for folder in sorted(lib.MODULES.iterdir()) if lib.MODULES.exists() else []:
    if folder.is_dir() and not (lib.pack_of(folder) / "module.env").exists():
        how = f"{lib.pack_of(folder).relative_to(lib.ROOT)}/module.env is missing" if lib.in_project(folder) \
            else f"make sync-module MODULE={folder.name}"
        print(f"skip modules/{folder.name}: no pack yet, so not part of the stack ({how})")
for folder, pack, m in lib.modules():
    check(f"modules/{folder.name} is named for its MODULE_ID", folder.name == m.get("MODULE_ID"), m.get("MODULE_ID", "not set"))
    # Its <id>-db runs one init-db.sh, the folder's before the pack's, so a second is never run.
    if (folder / "init-db.sh").exists() and (pack / "init-db.sh").exists():
        print(f"warn modules/{folder.name}/init-db.sh replaces its pack's, which never runs: keep one (platform/docs/module.md#its-pack-or-its-folder)")
    if lib.in_project(folder):
        continue
    r = run("platform/scripts/sync-module.sh", "--check", MODULE=folder.name)
    if "Could not find the file /module" in r.stderr:
        print(f"skip modules/{folder.name}/pack: its pinned image has no pack yet")
    else:
        check(f"modules/{folder.name}/pack matches its pinned image", r.returncode == 0, (r.stdout + r.stderr).strip()[-400:])

# 1b. t10-modkit. A module behind the template's tag still builds, so this only warns.
def semver(tag):
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag or "")
    return tuple(int(x) for x in m.groups()) if m else None


pinned = lib.read_env(lib.PLATFORM / "foundation" / "versions.env").get("T10_MODKIT", "")
for folder in sorted(lib.MODULES.iterdir()) if lib.MODULES.exists() else []:
    gomod = folder / lib.read_env(folder / "source.env").get("SRC", "src") / "go.mod"
    if not gomod.exists():
        continue
    found = re.search(r"^\s*(?:require\s+)?github\.com/xiant10/t10-modkit\s+(\S+)", gomod.read_text(), re.M)
    have = found.group(1) if found else ""
    if semver(have) and semver(pinned) and semver(have) < semver(pinned):
        print(f"warn modules/{folder.name} requires t10-modkit {have}, older than the template's {pinned}: "
              f"cd {gomod.parent.relative_to(lib.ROOT)} && go get github.com/xiant10/t10-modkit@{pinned} && go mod tidy")

# 2. Secrets.
allow = ["--allow-empty=LLM_API_KEY"] if os.environ.get("SCRIPTED") else []
r = run(sys.executable, "-I", "-B", "platform/scripts/secrets.py", "check", ENV, *allow)
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

def generated_tools(pack, mid):
    """(tool, grant action) for each tool the module's ontology generates, from its pinned core."""
    core = pack / "ontology.json"
    if not core.exists():
        return []
    try:
        actions = json.loads(core.read_text()).get("action_types", {})
    except ValueError:
        check(f"{mid}: its module/ontology.json is JSON", False)
        return []
    tools = [(f"{mid}_{t}", f"{mid}:read") for t in ("describe", "search", "get")] + [(f"{mid}_propose", f"{mid}:propose")]
    if any(a.get("agent") == "undoable" for a in actions.values()):
        tools.append((f"{mid}_act", f"{mid}:act"))
    return tools


# 4. Grants. A module says what its agent tools need once, in its catalog's agent block, and
# render.py gives it out; this checks that it reached every place in the bundle.
bundle = lib.GENERATED / ENV
clients_file = bundle / "clients.yaml"
runtimes = {r["name"]: r for r in json.loads(clients_file.read_text().split("\n", 1)[1])["runtimes"]} if clients_file.exists() else {}
module_lists = lib.read_env(bundle / "modules.env")
for folder, pack, m in lib.modules():
    if not wiring.has(m, "tools"):
        continue
    actions, audience = lib.grant(pack, m)
    for tool, action in generated_tools(pack, m["MODULE_ID"]):
        check(f"{folder.name}: its generated tool {tool} needs {action}, in its catalog's agent block", action in actions,
              f"add {action} to the agent block of {folder.name}'s permissions catalog")
    auds = set(lib.audiences(pack, m))
    want = set(actions)
    scoped = {a["runtime"]: set(a["actions"]) for a in wiring.agents(m) if a.get("actions") is not None}
    check(f"{folder.name}: the harnesses hold what its tools need",
          want <= set(module_lists.get("MODULE_GRANT_ACTIONS", "").split(","))
          and auds <= set(module_lists.get("MODULE_GRANT_AUDIENCES", "").split(",")), f"{sorted(want)}, {sorted(auds)}")
    for a in wiring.agents(m):
        agent = bundle / folder.relative_to(lib.ROOT) / "pack" / "agents" / a["name"] / "agent.json"
        grants = json.loads(agent.read_text()).get("grants", {})
        want_a = set(a["actions"]) if a.get("actions") is not None else want
        check(f"{folder.name}: its agent {a['name']}'s own grant holds them and the audience",
              want_a <= set(grants.get("actions", "").split(",")) and auds <= set(grants.get("audiences", "").split(",")), str(grants))
    sources = [wiring.clients(m)] + ([json.loads((pack / "clients.fragment.json").read_text())] if (pack / "clients.fragment.json").exists() else [])
    names = list(dict.fromkeys([n for s in sources for n in s.get("runtime_grants", {}).get("runtimes", []) if n not in lib.runtimes_off()]
                               + [r["name"] for s in sources for r in s.get("runtimes", [])]))
    bad = [n for n in names if n not in runtimes or not scoped.get(n, want) <= set(runtimes[n]["actions"]) or not auds <= set(runtimes[n]["audiences"])]
    check(f"{folder.name}: every runtime that runs its tools holds its grant in clients.yaml", not bad, f"missing in {bad}")

# 5. Prod placeholders.
if lib.shape(ENV) != "local":
    todo = [f"settings: {k}" for k, v in lib.settings(ENV).items() if v == "TODO"]
    todo += [f"{f.stem}: {k}" for f in sorted((lib.GENERATED / ENV / "env").glob("*.env"))
             for k, v in lib.read_env(f).items() if v == "TODO"]
    check(f"no TODO left in {ENV}'s settings (set them in site/config/{ENV}/)", not todo, "; ".join(todo))
    unpinned = [k for k, v in lib.versions(ENV).items() if v == "TODO"]
    check(f"every image {ENV} runs is pinned (make release MODULE=<id> for one built from modules/<id>/src/)", not unpinned, ", ".join(unpinned))
    # A tag can move under a server, so it runs each image by digest: `latest` is for local only.
    floating = [f"{k}={v}" for k, v in lib.versions(ENV).items() if v != "TODO" and "@sha256:" not in v]
    check(f"every image {ENV} runs is pinned by digest (make pin ENV={ENV} WRITE=1, or a config/server/versions.env line)",
          not floating, ", ".join(floating))
    # A module built from modules/<id>/src/ runs its released image there, but its pack comes from there, so
    # both must be the same commit.
    for folder, _, m in lib.modules():
        if not lib.in_project(folder):
            continue
        src = f"modules/{folder.name}/src"
        pin = lib.versions(ENV).get("T10_" + m["MODULE_ID"].upper().replace("-", "_"), "")
        tag = re.search(r":sha-([0-9a-f]+)@", pin)
        released = run("git", "rev-parse", "--verify", "-q", f"{tag.group(1)}^{{commit}}").stdout.strip() if tag else ""
        last = run("git", "log", "-1", "--format=%H", "--", src).stdout.strip()
        dirty = run("git", "status", "--porcelain", "--", src).stdout.strip()
        check(f"{m['MODULE_ID']}: its pinned image is {src} as committed", pin == "TODO" or (released == last and not dirty),
              f"{src} changed since its image was released: make release MODULE={m['MODULE_ID']}")

# 6. Compose.
r = run("platform/scripts/compose.sh", "config", "--format", "json")
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

if lib.target(ENV) == "k8s":
    r = run("kubectl", "kustomize", f"generated/{ENV}") if shutil.which("kubectl") else None
    check("the Kubernetes objects build", r is not None and r.returncode == 0,
          "needs kubectl" if r is None else r.stderr.strip()[-400:])
    if r is not None and r.returncode == 0:
        leaked = sorted(k for k, v in lib.secret_values(ENV).items() if len(v) >= 8 and v in r.stdout)
        check("no secret's value is in them", not leaked, ", ".join(leaked))

# 7. Each part's own checks.
for part, hook in lib.hooks("check"):
    where = hook.relative_to(lib.ROOT)
    if hook.suffix == ".py":
        runpy.run_path(str(hook), init_globals=dict(check=check, ENV=ENV, bundle=lib.GENERATED / ENV, run=run, module=lib.module_of(part)))
    else:
        r = run("sh", str(where), ENV=ENV, T10_PART=str(part.relative_to(lib.ROOT)), T10_MODULE=(lib.module_of(part) or {}).get("MODULE_ID", ""))
        check(str(where), r.returncode == 0, (r.stdout + r.stderr).strip()[-400:])

# 8. Template files edited in this project.
base = run("git", "merge-base", "HEAD", "template/main")
if base.returncode == 0:
    edited = run("git", "diff", "--name-only", base.stdout.strip(), "--", ".", *(f":!{p}" for p in lib.OWNED)).stdout.split()
    for f in edited:
        print(f"warn {f} is a template file, edited here, so template updates may conflict: change it in the template instead, or for a setting, override it from site/")

lib.finish()

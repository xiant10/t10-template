"""Shared by the scripts: where things live, and reading KEY=value files.

A project is made of parts, layered in this order, later ones winning: foundation/, its
components that are on (FOUNDATION), each modules/<id>/, then site/. Each module's standard
wiring and secrets (wiring.py) come just before its own folder's. Inside each part, config/
and compose/ are layered by environment: local, or server then dev or prod, or what an
environment's SHAPE names, then the environment's own. docs/guide.md describes the layout; this
file is the code that finds it.

A module's code is in the project, src/<SRC>/ with its pack in src/<SRC>/module/, when its
source.env has SRC and no REPO; else in its own repo, with its pack copied to modules/<id>/pack/.

Scripts run with `python3 -I`, so each puts this folder on sys.path itself before importing.
Shell scripts ask it for settings instead:

    scripts/lib.py setting ENV NAME     # one value from the parts' settings.env files
    scripts/lib.py shape ENV            # local, dev or prod: the template environment ENV is built on
    scripts/lib.py version NAME         # one image from the parts' versions.env files
    scripts/lib.py sources              # each module in its own repo: "SRC REPO", one per line
    scripts/lib.py built [ID]           # each module built from src/: "ID SRC SERVICE", one per line
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wiring  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
FOUNDATION = ROOT / "foundation"
COMPONENTS = FOUNDATION / "components"
MODULES = ROOT / "modules"
SITE = ROOT / "site"
GENERATED = ROOT / "generated"
SECRETS = SITE / "secrets"


def read_env(path):
    """KEY=value lines; blank lines and # comments are skipped. A missing file is empty."""
    out = {}
    path = pathlib.Path(path)
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                out[key.strip()] = value.strip().strip('"')
    return out


def source(folder):
    """A module folder's source.env: SRC, and REPO when its code is in a repo of its own."""
    return read_env(folder / "source.env")


def in_project(folder):
    """Whether a module's code is in this project, src/<SRC>/, rather than a repo of its own."""
    src = source(folder)
    return bool(src.get("SRC")) and not src.get("REPO")


def pack_of(folder):
    """Where a module's pack is: src/<SRC>/module/ for one in the project, else the copy from
    its image in modules/<id>/pack/."""
    return ROOT / "src" / source(folder)["SRC"] / "module" if in_project(folder) else folder / "pack"


def modules():
    """Each module, as (its folder, its pack folder, the pack's module.env). A folder whose
    pack has no module.env yet isn't part of the stack."""
    found = []
    for d in sorted(MODULES.iterdir()) if MODULES.exists() else []:
        if d.is_dir() and (pack_of(d) / "module.env").exists():
            found.append((d, pack_of(d), read_env(pack_of(d) / "module.env")))
    return found


def components(off=False):
    """The foundation's optional components this project runs, from foundation/components/: those
    FOUNDATION names in site/config/settings.env, or else in foundation/config/settings.env, the
    template's list. With off=True, the ones it leaves out. A component's component.env can name
    others it needs in REQUIRES."""
    have = sorted(d for d in COMPONENTS.iterdir() if d.is_dir()) if COMPONENTS.exists() else []
    chosen = read_env(SITE / "config" / "settings.env").get("FOUNDATION")
    if chosen is None:
        chosen = read_env(FOUNDATION / "config" / "settings.env").get("FOUNDATION", "")
    on = {n.strip() for n in chosen.split(",") if n.strip()}
    unknown = on - {d.name for d in have}
    if unknown:
        sys.exit(f"FOUNDATION names {', '.join(sorted(unknown))}: the components are {', '.join(d.name for d in have)}")
    for d in have:
        needs = [n for n in read_env(d / "component.env").get("REQUIRES", "").split(",") if n]
        if d.name in on and not on.issuperset(needs):
            sys.exit(f"the {d.name} component needs {', '.join(sorted(set(needs) - on))}: add it to FOUNDATION, or drop {d.name}")
    return [d for d in have if (d.name in on) != off]


def runtimes_off():
    """The auth-server runtimes of the components this project doesn't run, so a module's grant
    for one of them is left out instead of failing."""
    names = set()
    for d in components(off=True):
        if (d / "clients.json").exists():
            names |= {r["name"] for r in json.loads((d / "clients.json").read_text()).get("runtimes", [])}
    return names


def parts():
    """foundation/, its components that are on, each module's folder, then site/, as Compose and
    settings layer them."""
    return [FOUNDATION] + components() + [d for d, _, _ in modules()] + ([SITE] if SITE.exists() else [])


SHAPES = ("local", "dev", "prod")


def shape(env):
    """The template environment env is built on: itself for local, dev and prod, else its SHAPE."""
    if env in SHAPES:
        return env
    value = read_env(SITE / "config" / env / "settings.env").get("SHAPE")
    if value not in SHAPES:
        sys.exit(f"{env}: set SHAPE to one of {', '.join(SHAPES)} in site/config/{env}/settings.env")
    return value


def layers(env):
    """The names layered over every environment's files, in order: config/<name>/, compose/<name>.yml."""
    names = {"local": ["local"], "dev": ["server", "dev"], "prod": ["server", "prod"]}[shape(env)]
    return names + ([env] if env not in names else [])


def settings_files(env):
    """Values Compose interpolates and scripts read, in order: every part's config/settings.env,
    then every part's config/<layer>/settings.env, layer by layer."""
    files = [part / "config" / "settings.env" for part in parts()]
    files += [part / "config" / name / "settings.env" for name in layers(env) for part in parts()]
    return [f for f in files if f.exists()]


def settings(env):
    out = {}
    for f in settings_files(env):
        out.update(read_env(f))
    return out


def service_layers(service, env):
    """The settings files merged into a service's generated/<env>/env/<service>.env, lowest
    first: every part's config/<service>.env, then every part's config/<layer>/<service>.env."""
    files = [part / "config" / f"{service}.env" for part in parts()]
    files += [part / "config" / name / f"{service}.env" for name in layers(env) for part in parts()]
    return [p for p in files if p.exists()]


def services_configured(env):
    """Every service with a settings file in some part."""
    dirs = [part / "config" / name for part in parts() for name in ["", *layers(env)]]
    return sorted({p.stem for d in dirs for p in d.glob("*.env") if p.name != "settings.env"})


def secrets_file(env):
    """An environment's secrets in plain text, site/secrets/<env>.env: the only place they're
    read from. Never committed. For a server environment it will be decrypted from
    <env>.enc.env for as long as a command needs it (docs/plan.md, C2)."""
    return SECRETS / f"{env}.env"


def versions_files():
    """Every part's versions.env, in order: foundation's pins, each module's image, site's overrides."""
    return [p / "versions.env" for p in parts() if (p / "versions.env").exists()]


def versions():
    out = {}
    for f in versions_files():
        out.update(read_env(f))
    return out


def sources():
    """Each module in a repo of its own: SRC, its folder under src/, and REPO, what `make clone`
    fetches. A folder that isn't part of the stack yet counts, so its repo can be cloned first."""
    folders = sorted(d for d in MODULES.iterdir() if d.is_dir()) if MODULES.exists() else []
    return [source(d) for d in folders if source(d).get("REPO")]


def built(only=None):
    """Each module built from its source in this project, as (MODULE_ID, SRC, SERVICE); only=ID
    picks one, and fails if it isn't one."""
    found = [(m["MODULE_ID"], source(d)["SRC"], m["SERVICE"]) for d, _, m in modules() if in_project(d)]
    if only:
        found = [b for b in found if b[0] == only]
        if not found:
            sys.exit(f"{only} isn't a module built from src/ (modules/<id>/source.env with SRC and no REPO)")
    return found


def inventory():
    """Every secret, from each part's secrets.json: the foundation's, its components' that run,
    each module's standard ones (scripts/wiring.py) then its own, and site's. A later entry with
    the same name replaces an earlier one."""
    out = {}
    standard = {d: m for d, _, m in modules()}
    for part in parts():
        if part in standard:
            out.update({s["name"]: s for s in wiring.secrets(standard[part])})
        f = part / "secrets.json"
        if f.exists():
            out.update({s["name"]: s for s in json.loads(f.read_text())["secrets"]})
    return list(out.values())


def grant(pack, m):
    """What a module's agent tools need, as (actions, audience): its catalog's agent block, the
    one place a module says it. module.env's GRANT_ACTIONS and GRANT_AUDIENCE may add to it.
    scripts/render.py gives it to the module's agent, its runtimes and the harnesses."""
    agent = json.loads((pack / "permissions" / f"{m['MODULE_ID']}.yaml").read_text()).get("agent", {})
    actions = list(dict.fromkeys(agent.get("actions", []) + [a for a in m.get("GRANT_ACTIONS", "").split(",") if a]))
    return actions, agent.get("audience") or m.get("GRANT_AUDIENCE") or m["SERVICE"]


def secrets_off():
    """The secrets of the components this project doesn't run. Their values may stay in
    site/secrets/, unused, so switching a component back on keeps them."""
    return {s["name"] for d in components(off=True) if (d / "secrets.json").exists()
            for s in json.loads((d / "secrets.json").read_text())["secrets"]}


def compose_files(*names):
    """Each part's compose/<name>.yml that exists, name by name: compose_files("base", env) is
    every part's base.yml, then every part's <env>.yml."""
    return [p / "compose" / f"{name}.yml" for name in names for p in parts() if (p / "compose" / f"{name}.yml").exists()]


_failures = []


def check(name, ok, detail=""):
    """One line of `make check` or `make smoke`: ok, or FAIL with why."""
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"\n     {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


def finish(note=""):
    """The summary after the checks, and the exit status: 1 if any failed."""
    print(f"\n{len(_failures)} failed" if _failures else f"\nall passed{note}")
    sys.exit(1 if _failures else 0)


# What the deployment bundle copies from each part, beside what scripts/render.py writes.
BUNDLED = ("compose", "config", "scripted", "pack", "init-db.sh", "module-init-db.sh")


if __name__ == "__main__":
    if sys.argv[1:2] == ["shape"] and len(sys.argv) == 3:
        print(shape(sys.argv[2]))
    elif sys.argv[1:2] == ["version"] and len(sys.argv) == 3:
        value = versions().get(sys.argv[2])
        sys.exit(f"no part's versions.env has {sys.argv[2]}") if value is None else print(value)
    elif sys.argv[1:] == ["sources"]:
        for s in sources():
            print(s["SRC"], s["REPO"])
    elif sys.argv[1:2] == ["built"] and len(sys.argv) <= 3:
        for b in built(sys.argv[2] if len(sys.argv) == 3 else None):
            print(*b)
    elif sys.argv[1:2] == ["setting"] and len(sys.argv) == 4:
        value = settings(sys.argv[2]).get(sys.argv[3])
        sys.exit(f"{sys.argv[3]} is not set for {sys.argv[2]}") if value is None else print(value)
    else:
        sys.exit(__doc__)

#!/usr/bin/env python3
"""Make a new business module, shaped like the contract in docs/module.md.

    scripts/new-module.py ID [SERVICE] [PORT] [REPO]
    scripts/new-module.py crm                                             # code in modules/crm/src/
    scripts/new-module.py crm t10-crm 18076 https://github.com/x/t10-crm.git   # its own repo

ID is the module's MODULE_ID. SERVICE, its Compose service and auth-server account, is t10-<ID>
unless given; PORT, the port it listens on in its container, is the next one no module uses from
18100. Every other name follows from these: its image is T10_<ID>, its settings and secrets
start with <ID>_, its agent is <id> on agent-ti with the account agent-ti-<id>, and it's
published locally on PORT + 20000 (on k8s-local, PORT + 18000).

How it plugs into the foundation isn't written here: scripts/render.py works that out from its
module.env on every run (scripts/wiring.py), so a template update reaches every module. Its
folder holds only what's particular to it: its image pin, its settings, and any change it needs.

Without REPO, its code is in this project: modules/<ID>/src/ gets a small working service from
scripts/scaffold/<SCAFFOLD>/, with its pack in module/. SCAFFOLD (in the environment, `make
new-module SCAFFOLD=…`) picks the language; go, the default, is the one there is. Another is a
folder beside it with the same tokens (__id__, __ID__, __Id__, __service__, __port__), a
Dockerfile with a `test` stage, and a service that keeps the contract in docs/module.md. It runs
with the next `make up` and passes `make smoke` as it is.

With REPO, its code is in that repo, and modules/<id>/ does nothing until `make sync-module
MODULE=<id>` copies the pack out of its image: a module without a pack isn't part of the stack.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402

FILES = {
    "README.md": """\
# {Id}

The {id} module's deployment in this project: {where} How it plugs into the foundation is the
template's standard wiring, worked out from its pack's `module.env`; this folder holds only
what's particular to it ([`platform/docs/module.md`](../../platform/docs/module.md)).

| Path | Holds |
| --- | --- |
| `source.env`, `versions.env` | Where its code is, and its image on servers, `T10_{U}` |
| `config/{service}.env` | Its service's settings; `config/local/`, `config/k8s-local/` and `config/server/` per layer |
{rows}""",
    "versions.env": """\
{versions_comment}
T10_{U}=TODO
""",
    "source.env": """\
{source}""",
    "config/{service}.env": """\
# {service}'s settings in every environment. Secrets never go here: the standard ones are made for
# it, and any more go in secrets.json in this folder (platform/docs/module.md).
LISTEN_ADDR=:{port}
""",
    "config/local/settings.env": """\
# {Id} in the local environment.
{U}_PUBLIC_URL=http://127.0.0.1:{local_port}
{U}_PORT={local_port}
""",
    "config/k8s-local/settings.env": """\
# {Id} on k8s-local, this machine's Kubernetes, beside local.
{U}_PUBLIC_URL=http://127.0.0.1:{k8s_port}
{U}_PORT={k8s_port}
""",
    "config/server/settings.env": """\
# {Id} on a server (dev, prod). `make check` fails while any value is TODO: set it in
# site/config/<env>/settings.env.
{U}_PUBLIC_URL=TODO
""",
}


# What differs between a module whose code is in this project and one in a repo of its own.
IN_PROJECT = {
    "where": "its code is [`src/`](src/), in this folder.",
    "rows": """\
| `src/` | Its service's code, tests, Dockerfile and pack (`src/module/`) |
""",
    "versions_comment": "# The {id} module's image on servers: `make release MODULE={id}` builds it from modules/{id}/src/,\n"
                        "# pushes it and pins it here. Local runs build it from modules/{id}/src/ instead.",
    "source": """\
# The {id} module's code is in this folder, modules/{id}/src/. No REPO: it has no repo of its own.
SRC=src
""",
}
OWN_REPO = {
    "where": "its code is in its own repo, which `make clone` checks out into `modules/{id}/src/`.",
    "rows": """\
| `pack/` | The module pack from its image, from `make sync-module MODULE={id}`. Never edited here |
""",
    "versions_comment": "# The {id} module's image. Pin it to sha-<commit>@<digest> once its image ships a pack at /module.",
    "source": """\
# The {id} module's repo: `make clone` fetches it into modules/{id}/src/, which DEV=1 builds from.
SRC=src
REPO={repo}
""",
}
SCAFFOLDS = pathlib.Path(__file__).resolve().parent / "scaffold"
FIRST_PORT = 18100


def modkit_version():
    """The t10-modkit tag the template pins, T10_MODKIT in platform/foundation/versions.env."""
    version = lib.read_env(lib.PLATFORM / "foundation" / "versions.env").get("T10_MODKIT", "")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        sys.exit(f"platform/foundation/versions.env: T10_MODKIT={version!r} isn't a release tag such as v0.1.0")
    return version


def scaffold_src(dest, names, scaffold):
    """modules/<id>/src/ from platform/scripts/scaffold/<scaffold>/, with __id__ and the like in names and files filled in."""
    tokens = {"__service__": names["service"], "__ID__": names["U"], "__Id__": names["Id"], "__id__": names["id"],
              "__port__": str(names["port"]), "__modkit__": modkit_version()}

    def sub(text):
        for k, v in tokens.items():
            text = text.replace(k, v)
        return text

    for f in sorted(scaffold.rglob("*")):
        if f.is_file() and f.name != ".DS_Store":
            out = dest / sub(str(f.relative_to(scaffold)))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(sub(f.read_text()))


def free_port():
    """The first port from FIRST_PORT that no module listens on, nor publishes 20000 or 18000 above."""
    used = set()
    for folder in sorted(lib.MODULES.iterdir()) if lib.MODULES.exists() else []:
        used.add(lib.read_env(lib.pack_of(folder) / "module.env").get("PORT", ""))
        for layer in ("local", "k8s-local"):
            used |= {v for k, v in lib.read_env(folder / "config" / layer / "settings.env").items() if k.endswith("_PORT")}
    port = FIRST_PORT
    while str(port) in used or str(port + 20000) in used or str(port + 18000) in used:
        port += 1
    return str(port)


def main(argv):
    if not 1 <= len(argv) <= 4 or not argv[0]:
        sys.exit(__doc__.strip().split("\n\n")[1])
    mid = argv[0]
    service = argv[1] if len(argv) > 1 and argv[1] else f"t10-{mid}"
    port = argv[2] if len(argv) > 2 and argv[2] else free_port()
    repo = argv[3] if len(argv) > 3 else ""
    if not re.fullmatch(r"[a-z][a-z0-9-]*", mid):
        sys.exit(f"{mid}: an ID is lowercase letters, digits and dashes, starting with a letter")
    if not port.isdigit():
        sys.exit(f"{port}: PORT is the number the service listens on in its container")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", service):
        sys.exit(f"{service}: a SERVICE is lowercase letters, digits and dashes, starting with a letter")
    in_project = not repo
    if in_project and "-" in mid:
        sys.exit(f"{mid}: the scaffold serves an ontology, whose module name and action prefix are the ID, "
                 "and those take no dashes: use letters and digits only")
    scaffold = SCAFFOLDS / (os.environ.get("SCAFFOLD") or "go")
    if in_project and not (scaffold / "module" / "module.env").exists():
        have = sorted(d.name for d in SCAFFOLDS.iterdir() if (d / "module" / "module.env").exists())
        sys.exit(f"SCAFFOLD={scaffold.name}: there's no platform/scripts/scaffold/{scaffold.name}/; the scaffolds are {', '.join(have)}")
    folder = lib.MODULES / mid
    src = folder / "src"
    if folder.exists():
        sys.exit(f"modules/{mid} already exists")
    u = mid.upper().replace("-", "_")
    names = dict(id=mid, Id=mid.replace("-", " ").title(), U=u, service=service, port=port,
                 local_port=int(port) + 20000, k8s_port=int(port) + 18000, src="src", repo=repo)
    names.update({k: v.format(**names) for k, v in (IN_PROJECT if in_project else OWN_REPO).items()})
    for path, text in FILES.items():
        f = folder / path.format(**names)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text.format(**names))
    if in_project:
        scaffold_src(src, names, scaffold)
        print(f"""made modules/{mid}/, its deployment and code in modules/{mid}/src/ ({service}, port {port}). Next:
  1. make test MODULE={mid} && make up && make smoke: it runs as it is.
  2. Make it yours: its records and actions in modules/{mid}/src/ontology.go, its tools in tools.go, its permissions in src/module/ (platform/docs/module.md).
  3. After each change, make reload MODULE={mid}; before a server, make release MODULE={mid}.""")
    else:
        print(f"""made modules/{mid}/ ({service}, port {port}). Next:
  1. Give its image a pack at /module (platform/docs/module.md), and pin it as T10_{u} in modules/{mid}/versions.env.
  2. make sync-module MODULE={mid}, which makes it part of the stack.
  3. Set its server address (modules/{mid}/config/server/), then make secrets-init, make up and make check.""")


if __name__ == "__main__":
    main(sys.argv[1:])

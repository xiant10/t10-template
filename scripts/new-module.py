#!/usr/bin/env python3
"""Make modules/<id>/ for a new business module, shaped like the contract in docs/module.md.

    scripts/new-module.py ID SERVICE PORT [REPO]
    scripts/new-module.py crm t10-crm 18076 https://github.com/xiant10/t10-crm.git

ID is the module's MODULE_ID, SERVICE its Compose service and auth-server account, PORT the
port it listens on in its container. Every other name follows from these: its image is T10_<ID>,
its settings and secrets start with <ID>_, its agent is <id> on agent-ti with the account
agent-ti-<id>, and it's published locally on PORT + 20000.

The folder does nothing until `make sync-module MODULE=<id>` copies the pack out of its image:
a folder under modules/ without pack/module.env isn't a module yet. Then fill in each TODO.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402

FILES = {
    "README.md": """\
# {Id}

Everything the {id} module adds to the foundation, in the shape `../../docs/module.md` describes.
The module's source is `src/{src}/` (`make clone`), its own repo; this folder deploys it.

| Path | Holds |
| --- | --- |
| `versions.env`, `source.env` | Its image, `T10_{U}`, and its repo |
| `compose/base.yml` | `{service}`, its service accounts and database, and its agent for `t10-agents` |
| `compose/local.yml` | `local`: `{service}` published on 127.0.0.1 |
| `compose/build.yml` | `DEV=1`: `{service}` built from `src/{src}/` |
| `init-db.sh` | Its database, with its own login |
| `secrets.json` | Every secret it adds |
| `config/` | `{service}.env` for its service, `settings.env` for values foundation services need, a folder per layer |
| `k8s/` | Its Kubernetes component (a skeleton until Kubernetes is built) |
| `pack/` | The module pack from its image, from `make sync-module MODULE={id}`. Never edited here |
""",
    "versions.env": """\
# The {id} module's image. Pin it to sha-<commit>@<digest> once its image ships a pack at /module.
T10_{U}=TODO
""",
    "source.env": """\
# The {id} module's repo: `make clone` fetches it into src/$SRC, which DEV=1 builds from.
SRC={src}
REPO={repo}
""",
    "compose/base.yml": """\
# The {id} module on top of foundation/compose/base.yml. Its grants, tool server, agent route
# and workbench entry reach the foundation through scripts/render.py, from its pack/, so this
# file only adds its own services and the few foundation settings only it needs.
# Paths are relative to the deployment bundle, generated/<env>/, which has the repo's layout.

services:
  postgres:
    environment:
      {U}_DB_PASSWORD: ${{{U}_DB_PASSWORD}}
    volumes:
      - ./modules/{id}/init-db.sh:/docker-entrypoint-initdb.d/20-{id}.sh:ro

  # One-shot: its service accounts in auth-server, SERVICE_ACCOUNTS in pack/module.env
  # (upstream U2).
  {id}-seed:
    image: ${{T10_AUTH_SERVER}}
    entrypoint:
      - /bin/sh
      - -c
      - |
        set -eu
        AUTHCTL_SERVICE_SECRET="$${SU}_SECRET" authctl service-add --if-missing --name={service}
        AUTHCTL_SERVICE_SECRET="$$AGENT_TI_{U}_SECRET" authctl service-add --if-missing --name=agent-ti-{id}
    environment:
      DATABASE_URL: postgres://t10:${{POSTGRES_PASSWORD}}@postgres:5432/auth?sslmode=disable
      {SU}_SECRET: ${{{SU}_SECRET}}
      AGENT_TI_{U}_SECRET: ${{AGENT_TI_{U}_SECRET}}
    depends_on:
      seed: {{condition: service_completed_successfully}}

  auth-server:
    depends_on:
      {id}-seed: {{condition: service_completed_successfully}}

  # This pack's agent, which t10-agents copies into agent-ti's agents volume.
  t10-agents:
    volumes:
      - ./modules/{id}/pack/agents/{id}:/module-agents/{id}:ro

  agent-ti:
    environment:
      # Its agent's own runtime account. TODO: the name its pack's agent.json reads.
      {U}_AUTH_CLIENT_SECRET: ${{AGENT_TI_{U}_SECRET}}

  {service}:
    image: ${{T10_{U}}}
    restart: unless-stopped
    env_file: ./env/{service}.env
    environment:
      DATABASE_URL: postgres://{db}:${{{U}_DB_PASSWORD}}@postgres:5432/{db}?sslmode=disable
      AUTH_ISSUER: ${{AUTH_PUBLIC_URL}}
      AUTH_URL: http://auth-server:8081
      AUTH_CLIENT_SECRET: ${{{SU}_SECRET}}
      AUTH_WEB_CLIENT_SECRET: ${{{U}_WEB_CLIENT_SECRET}}
      {U}_PUBLIC_URL: ${{{U}_PUBLIC_URL}}
      {U}_SESSION_KEY: ${{{U}_SESSION_KEY}}
      # Turns go through ai-gateway-agent, which routes Agent-Name: {id} to agent-ti.
      AGENT_URL: http://ai-gateway-agent:18090/agent
    read_only: true
    tmpfs: [/tmp]
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://127.0.0.1:{port}/readyz"]
      interval: 5s
      timeout: 3s
      retries: 12
    depends_on:
      auth-server: {{condition: service_healthy}}

  # The tools gateway lists its /mcp for harnesses; workbench reads its manifest.
  ai-gateway-tools:
    depends_on:
      {service}: {{condition: service_healthy}}
  workbench:
    depends_on:
      {service}: {{condition: service_healthy}}
""",
    "compose/local.yml": """\
# {Id} on one machine, over compose/base.yml: published on 127.0.0.1.

services:
  {service}:
    ports:
      - "127.0.0.1:${{{U}_PORT}}:{port}"
""",
    "compose/build.yml": """\
# DEV=1: builds {service} from its checkout in src/{src} (`make clone`, from ../source.env),
# instead of pulling the pinned image.
services:
  {service}:
    image: {service}:dev
    # From the bundle, generated/local/, the checkout is two folders up. DEV=1 is local only.
    build: ../../src/{src}
""",
    "init-db.sh": """\
#!/bin/sh
# Runs once, when the Postgres volume is new, after the foundation's script. {Id} gets its own
# login, which owns only its own database.
set -eu
psql -v ON_ERROR_STOP=1 -U t10 -d auth <<SQL
CREATE ROLE {db} LOGIN PASSWORD '${{{U}_DB_PASSWORD}}';
CREATE DATABASE {db} OWNER {db};
REVOKE ALL ON DATABASE {db} FROM PUBLIC;
SQL
""",
    "secrets.json": """\
{{
 "_comment": "Every secret the {id} module adds, in the same form as foundation/secrets.json.",
 "secrets": [
  {{
   "name": "{U}_DB_PASSWORD",
   "generate": "hex32",
   "consumers": ["{service}", "postgres role {db}"],
   "rotate": "ALTER ROLE {db} PASSWORD …, change the value, then roll {service}."
  }},
  {{
   "name": "{SU}_SECRET",
   "generate": "hex32",
   "consumers": ["{service}", "auth-server account {service}"],
   "rotate": "authctl service-rotate --name={service}, roll, then service-finish."
  }},
  {{
   "name": "AGENT_TI_{U}_SECRET",
   "generate": "hex32",
   "consumers": ["agent-ti ({id} agent)", "auth-server account agent-ti-{id}"],
   "rotate": "authctl service-rotate --name=agent-ti-{id}, roll agent-ti, then service-finish."
  }},
  {{
   "name": "{U}_WEB_CLIENT_SECRET",
   "generate": "hex32",
   "consumers": ["{service} (AUTH_WEB_CLIENT_SECRET)", "secret_sha256 in clients.yaml"],
   "rotate": "Change, re-render clients.yaml, roll auth-server and {service} together."
  }},
  {{
   "name": "{U}_SESSION_KEY",
   "generate": "b64key",
   "consumers": ["{service}"],
   "rotate": "Change and roll {service}. Everyone signs in again."
  }}
 ]
}}
""",
    "config/{service}.env": """\
# {service}'s settings in every environment. Secrets never go here: they're in secrets.json.
LISTEN_ADDR=:{port}
""",
    "config/settings.env": """\
# Values foundation services or scripts need from {id}, in every environment.
""",
    "config/local/settings.env": """\
# {Id} in the local environment.
{U}_PUBLIC_URL=http://127.0.0.1:{local_port}
{U}_PORT={local_port}
""",
    "config/server/settings.env": """\
# {Id} on a server (dev, prod). `make check` fails while any value is TODO: set it in
# site/config/<env>/settings.env.
{U}_PUBLIC_URL=TODO
""",
    "k8s/kustomization.yaml": """\
# Component: {id} on Kubernetes, the counterpart of ../compose/base.yml. A skeleton until
# phase E (docs/plan.md).
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component
resources: []
""",
}


def main(argv):
    if len(argv) not in (3, 4) or not all(argv[:3]):
        sys.exit(__doc__.strip().split("\n\n")[1])
    mid, service, port = argv[:3]
    if not re.fullmatch(r"[a-z][a-z0-9-]*", mid):
        sys.exit(f"{mid}: an ID is lowercase letters, digits and dashes, starting with a letter")
    if not port.isdigit():
        sys.exit(f"{port}: PORT is the number the service listens on in its container")
    folder = lib.MODULES / mid
    if folder.exists():
        sys.exit(f"modules/{mid} already exists")
    u = mid.upper().replace("-", "_")
    names = dict(id=mid, Id=mid.replace("-", " ").title(), U=u, SU=service.upper().replace("-", "_"), service=service,
                 port=port, local_port=int(port) + 20000, db=mid.replace("-", "_"), src=service,
                 repo=argv[3] if len(argv) == 4 else "TODO")
    for path, text in FILES.items():
        f = folder / path.format(**names)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text.format(**names))
    (folder / "init-db.sh").chmod(0o755)
    print(f"""made modules/{mid}/. Next:
  1. Give its image a pack at /module (docs/module.md), and pin it as T10_{u} in modules/{mid}/versions.env.
  2. make sync-module MODULE={mid}, which makes it part of the stack.
  3. Fill in each TODO (grep -rn TODO modules/{mid}), then make secrets-init, make up and make check.""")


if __name__ == "__main__":
    main(sys.argv[1:])

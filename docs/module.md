# The module contract

What a business module provides so a project can run it on the foundation, and where its parts live in a project. `make new-module` writes a module in this shape.

A module's code is in one of two places:

| | Code in the project (the default) | Code in a repo of its own |
| --- | --- | --- |
| Made with | `make new-module ID= SERVICE= PORT=` | `make new-module ID= SERVICE= PORT= REPO=<url>` |
| Its code | `src/<service>/`, committed in the project | Its repo, cloned into `src/<service>/` by `make clone`, kept out of the project's git |
| Its pack | `src/<service>/module/`, read as it is | `modules/<id>/pack/`, copied from its pinned image by `make sync-module` |
| On local | Always built from `src/` by `make up` | Its pinned image; built from `src/` with `DEV=1` |
| On a server | Its image from `make release`, pinned in `modules/<id>/versions.env` | Its image as its own CI publishes it, pinned the same way |
| Tests | `make test`, then the whole stack with `make smoke` | Its own repo's CI, then `make smoke` |

Code in the project suits a module built for this project: one commit changes the code, its permissions and its deployment together, and nothing needs publishing to try it. A repo of its own suits a module several projects share, such as `t10-property`, whose repo's `module/` folder is a worked pack.

## Its image

The module's service image ships a **pack** at `/module`, so the deployment always matches the service's version:

| Path in the image | Holds | Used by |
| --- | --- | --- |
| `/module/module.env` | Facts a deployment needs, below. Nothing secret, nothing per environment | `scripts/render.py`, `check.py`, `smoke.py` |
| `/module/permissions/<id>.yaml` | Its permission catalog, with an `agent` block naming the `actions` and `audience` its agent tools need | auth-server's `AUTH_PERMISSIONS_DIR` |
| `/module/agents/<AGENT>/` | Its agent folder for agent-ti; `agent.json` reads its runtime secret from `${<ID>_AUTH_CLIENT_SECRET}` | `t10-agents`, which copies it into agent-ti's agents |
| `/module/clients.fragment.json` | Its OAuth clients, its runtimes, and `runtime_grants`: the foundation runtimes that get its grant | Merged into auth-server's `clients.yaml` |

A module with code in the project has the same files in `src/<service>/module/`, and its Dockerfile copies that folder to `/module`.

`module.env` sets each of these:

| Key | Means |
| --- | --- |
| `MODULE_ID` | The ID: the folder name in `modules/`, the action prefix, and `T10_<ID>` for its image |
| `SERVICE`, `PORT` | Its Compose service and the port it listens on |
| `GRANT_ACTIONS`, `GRANT_AUDIENCE` | What the foundation's harnesses need to call its tools; at least the catalog's `agent` block |
| `SERVICE_ACCOUNTS` | Its accounts in auth-server: itself and its agent's runtime |
| `AGENT`, `AGENT_TITLE`, `AGENT_RUNTIME` | Its agent folder, its name in the picker, and its runtime account |
| `PUBLIC_URL_SETTING` | The setting holding its web app's public address, such as `CRM_PUBLIC_URL` |

## Its service

- `GET /readyz` answers 200 when it's ready.
- `GET /v1/module` returns its manifest, with `action_prefix` equal to `MODULE_ID`. Workbench reads it.
- `GET /v1/access` tells a signed-in user what they may do; a tenant admin gets `tenant_admin: true`.
- `/mcp` serves its tools, which `ai-gateway-tools` lists for the harnesses.
- It sends assistant turns to `AGENT_URL` (ai-gateway-agent) with `Agent-Name: <AGENT>`.

`make smoke` checks each of these for every module, and that its agent answers a turn. With `SCRIPTED=1` and a `compose/scripted.yml`, it also checks that the turn's tool call reached the module.

The service `make new-module` writes in `src/<service>/` does all of this, in Go with no framework: a person's token and an agent's delegated token are checked with auth-server's verifier, then the person's live standing is read from auth-server on every request. Its one tool, `<id>_whoami`, is there to be replaced. Its `README.md` says which file does what.

## Its folder: `modules/<id>/`

The module's deployment, whichever place its code is in.

| Path | Required | Holds |
| --- | --- | --- |
| `source.env` | Yes | `SRC`, its folder in `src/`; and `REPO` only when it has a repo of its own |
| `versions.env` | Yes | `T10_<ID>`, its image, pinned to `sha-<commit>@<digest>`. For code in the project, `TODO` until `make release`; local runs don't use it |
| `compose/base.yml` | Yes | Its service; a one-shot `<id>-db` running its `init-db.sh`; a one-shot `<id>-seed` adding its service accounts; its agent folder mounted into `t10-agents` at `/module-agents/<AGENT>`; its agent's runtime secret on `agent-ti`; and `ai-gateway-tools` and `workbench` waiting for it |
| `compose/local.yml` | Yes | Its port published on 127.0.0.1; for code in the project, also its `build:` from `src/<service>/` |
| `secrets.json` | Yes | Every secret it adds, in the form of `foundation/secrets.json` |
| `config/` | Yes | `<service>.env`, its service's settings; `settings.env`, values foundation services need from it; and a folder per layer: `local/` with its address and port, `server/` with `TODO` where a project must decide |
| `pack/` | Own repo only | The pack, copied from the pinned image by `make sync-module MODULE=<id>`. Never edited here. A module without `pack/module.env` isn't part of the stack yet |
| `compose/build.yml` | Own repo, for `DEV=1` | Its service built from `src/<service>/` |
| `init-db.sh` | With a database | Its database and its own login, made if missing by its one-shot `<id>-db` on every start, so a module joins a stack whose database already exists |
| `compose/scripted.yml` | Optional | `SCRIPTED_TOOL_<ID>`: the tool the scripted model calls, so `make smoke` sees a tool call reach it |
| `hooks/seed-demo.sh` | Optional | Its demo data, after the foundation's, from `make seed-demo` |
| `hooks/smoke.py` | Optional | Its own checks, after the shared ones (`scripts/smoke.py` says what it's given) |
| `k8s/` | Later | Its Kubernetes component (phase E) |
| `README.md`, `docs/` | | What it is, and what to know before deploying it |

Names follow from the ID, so nothing outside the folder and `src/` needs to know them: settings and secrets start with `<ID>_` (`CRM_PUBLIC_URL`, `CRM_DB_PASSWORD`), its service account's secret is `<SERVICE>_SECRET`, and its agent's is `AGENT_TI_<ID>_SECRET`.

## Adding one with its code in the project

```sh
make new-module ID=crm SERVICE=t10-crm PORT=18076
make test MODULE=crm              # vet and its tests, in Docker
make up && make smoke             # built from src/t10-crm/, run with the foundation, checked end to end
```

Then make it the module you need, checking as you go:

| Change | Where | Then |
| --- | --- | --- |
| A tool | `src/<service>/tools.go`, with a test in `server_test.go` | `make test MODULE=<id>`, `make reload MODULE=<id>` |
| An API or the web app | `src/<service>/server.go` and new files | The same |
| A permission, role or action | `src/<service>/module/permissions/<id>.yaml`; a new action also in `module.env`, the agent's `grants` and the runtimes in `clients.fragment.json` | `make check` names any place it's missing; `make reload` restarts what reads the pack |
| Its agent's instructions | `src/<service>/module/agents/<id>/` | `make reload MODULE=<id>` |
| A setting | `modules/<id>/config/<service>.env`; a secret in `modules/<id>/secrets.json` | `make up` |
| Its database schema | Migrations in its code, run at start | `make reload`, or `make down-all && make up` for a fresh database |

`make verify` runs everything from empty volumes: the tests, `down-all`, `up`, `seed-demo`, `check` and `smoke`.

For a server, set `IMAGE_REGISTRY` (such as `ghcr.io/<owner>`) in `site/config/settings.env`, commit, and run `make release MODULE=<id>`: it builds the image from `src/<service>/` as committed, pushes it, and pins it in `modules/<id>/versions.env`. `make check ENV=<env>` fails while the pin is `TODO`, or when `src/<service>/` has changed since the pinned release, since a server would run old code with a newer pack.

## Adding one that has its own repo

```sh
make new-module ID=crm SERVICE=t10-crm PORT=18076 REPO=https://github.com/xiant10/t10-crm.git
# give its image a pack, pin it in modules/crm/versions.env
make sync-module MODULE=crm
grep -rn TODO modules/crm          # fill each in, and add what only this module needs
make up && make check && make smoke
```

To work on its code here, `make clone`, then `DEV=1 make up` builds it from `src/`. Its pack still comes from `modules/<id>/pack/`, so after changing the catalog, agent or clients, build its image and copy the pack from it: `IMAGE=t10-crm:dev make sync-module MODULE=crm`. A change in both places is a commit in the module's repo, then one in the project that pins the new image and its pack.

Either way, its grants, tool server, agent route, workbench entry, catalog, clients and secrets reach the foundation from its folder and its pack, with no change anywhere else. Locally, `make up` adds its generated secrets to `site/secrets/local.env`; a server needs `make secrets-init ENV=<env>`.

To remove a module, delete `modules/<id>/` and its code in `src/`, and its values from each `site/secrets/<env>.env`: `make check` refuses a secret that's no longer in any inventory, so a misspelled name can't hide.

`make new-module` writes what every module has. What's particular to one, such as an extra sign-in method or a key that encrypts its data, is added by hand. Tested Nov 16: `t10-property` scaffolded with its own repo, plus its own additions, matched its hand-written folder line for line; a module scaffolded with its code in the project passed `make verify` as it was.

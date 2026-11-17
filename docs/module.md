# Building a module

A module is the business part of a project: a service with its own database, web app, tools and agent, plugged into the foundation. This is what a module provides, where each part lives, and how to work on one. Where things live in a project overall is [`guide.md`](guide.md).

## In short

```sh
make new-module ID=crm            # code in src/crm/, deployment in modules/crm/
make test MODULE=crm              # its tests, in Docker
make up && make smoke             # built from src/crm/, run with the foundation, checked end to end
```

It runs as it is. Then make it yours:

| Change | Where | Then |
| --- | --- | --- |
| A tool | `src/<id>/tools.go`, with a test in `server_test.go` | `make test MODULE=<id>`, `make reload MODULE=<id>` |
| An API or the web app | `src/<id>/server.go` and files beside it | The same |
| A permission, role or action | `src/<id>/module/permissions/<id>.yaml`. An action a tool uses goes in its `agent` block, and nowhere else | `make reload MODULE=<id>`, which restarts what reads the pack |
| Its agent's instructions | `src/<id>/module/agents/<id>/` | `make reload MODULE=<id>` |
| Its data | Migrations in its code, run at start, against the database it's given | `make reload`, or `make down-all && make up` for a fresh database |
| A setting | `modules/<id>/config/<service>.env` | `make up` |
| A secret beyond the standard ones | `modules/<id>/secrets.json`, in the form of `foundation/secrets.json`, with an `env` naming the service and variable that get it ([`guide.md`](guide.md#secrets)) | `make up` |
| Its demo data, extra checks | `modules/<id>/hooks/seed-demo.sh`, `hooks/smoke.py` | `make seed-demo`, `make smoke` |

Commit `src/<id>/` and `modules/<id>/` together: one commit is one change to the module. Before calling it done, `make verify` runs everything from empty volumes.

## What the template gives every module

A module's own folders hold only what's particular to it. The rest is the template's, so a fix there reaches every module with `make template-update`:

- **Its wiring** (`scripts/wiring.py`). On every command, `scripts/render.py` writes from its `module.env`, into the bundle: a one-shot `<id>-db` that makes its database and login (on every start, so a module joins a running stack); a one-shot `<id>-seed` that adds its accounts to auth-server; its agent, copied into agent-ti, with its runtime's secret; its service, with the standard settings below, a read-only filesystem and a healthcheck on `/readyz`; and `ai-gateway-tools` and `workbench` waiting for it. On local, its port on `127.0.0.1`, and for code in the project, its build from `src/<id>/`.
- **Its standard secrets**: `<ID>_DB_PASSWORD`, each account's `<ACCOUNT>_SECRET` (such as `T10_CRM_SECRET` and `AGENT_TI_CRM_SECRET`), `<ID>_WEB_CLIENT_SECRET` and `<ID>_SESSION_KEY`.
- **Its place in the foundation**: its grants on the harnesses, its tool server on `ai-gateway-tools`, its workbench entry, its app on auth-server's landing page, its agent's route, its catalog and its OAuth clients, all from its pack.
- **Its service's common code** (`kit/go/`, for a module written in Go): the token verifier, a person's and an agent's access checked against auth-server, the MCP server for its tools, and the routes every module answers. Its own code is its tools, its web app, and its tests.

Its folder can change any of the wiring: `modules/<id>/compose/base.yml` (or `local.yml`, …) is read after the standard file for the same name and merged over it by Compose. Set `DATABASE=false` in `module.env` for a module without a database, and leave `AGENT` empty for one without an agent.

## Where its code is

| | In the project (the default) | In a repo of its own |
| --- | --- | --- |
| Made with | `make new-module ID=<id>` | `make new-module ID=<id> SERVICE=<service> PORT=<port> REPO=<url>` |
| Its code | `src/<id>/`, committed in the project | Its repo, cloned into `src/<service>/` by `make clone`, kept out of the project's git |
| Its pack | `src/<id>/module/`, read as it is | `modules/<id>/pack/`, copied from its pinned image by `make sync-module` |
| On local | Always built from `src/` by `make up` | Its pinned image; built from `src/` with `DEV=1` |
| On a server | Its image from `make release`, pinned in `modules/<id>/versions.env` | Its image as its own CI publishes it, pinned the same way |
| Tests | `make test`, then the whole stack with `make smoke` | Its own repo's CI, then `make smoke` |

Code in the project suits a module built for this project: one commit changes its code, its permissions and its deployment, and nothing needs publishing to try it. A repo of its own suits a module several projects share, such as `t10-property`. A module can move from one to the other by moving its code and changing `source.env`.

## Its image and pack

The service's image ships a **pack** at `/module`, so its deployment always matches the service's version. For code in the project the pack is `src/<id>/module/`, which the Dockerfile copies to `/module`.

| Path | Holds | Used by |
| --- | --- | --- |
| `module.env` | Facts a deployment needs, below. Nothing secret, nothing per environment | The scripts, and its standard wiring |
| `permissions/<id>.yaml` | Its permission catalog, with an `agent` block naming the `actions` and `audience` its agent tools need: the one place that's said | auth-server, and the scripts, which give it to every place below |
| `agents/<AGENT>/` | Its agent folder for agent-ti; `agent.json` reads its runtime secret from `${<ID>_AUTH_CLIENT_SECRET}` | `t10-agents`, which copies it into agent-ti |
| `clients.fragment.json` | Its OAuth clients, its runtimes, and in `runtime_grants.runtimes` the foundation runtimes that may run its tools | Merged into auth-server's `clients.yaml` |

What its tools need, from the catalog's `agent` block, is added to its agent's own grant, to each of its runtimes and those `runtime_grants` names, and to the harnesses' `GRANT_ACTIONS` and `GRANT_AUDIENCES`. `make check` confirms it reached each one.

`module.env` sets:

| Key | Means |
| --- | --- |
| `MODULE_ID` | The ID: the folder name in `modules/`, the action prefix, and `T10_<ID>` for its image |
| `SERVICE`, `PORT` | Its Compose service and auth-server account, and the port it listens on |
| `SERVICE_ACCOUNTS` | Its accounts in auth-server: itself and its agent's runtime |
| `AGENT`, `AGENT_TITLE`, `AGENT_RUNTIME` | Its agent folder, its name in the picker, and its runtime account; `AGENT` empty for none |
| `PUBLIC_URL_SETTING` | The setting holding its web app's public address, such as `CRM_PUBLIC_URL` |
| `DATABASE` | Optional: `false` for no database |
| `GRANT_ACTIONS`, `GRANT_AUDIENCE` | Optional: more than the catalog's `agent` block says |

## Its service

What a project expects of every module's service, which `make smoke` checks:

- `GET /readyz` answers 200 when it's ready.
- `GET /v1/module` returns its manifest, with `action_prefix` equal to `MODULE_ID`. Workbench reads it.
- `GET /v1/access` tells a signed-in person what they may do; a tenant admin gets `tenant_admin: true`.
- `/mcp` serves its tools, which `ai-gateway-tools` lists for the harnesses. Calling one needs an agent's delegated token for the person it acts for.
- It sends assistant turns to `AGENT_URL` (ai-gateway-agent) with `Agent-Name: <AGENT>`, and its agent answers one.

The standard wiring gives it these settings: `AUTH_ISSUER`, `AUTH_URL`, `AUTH_CLIENT_SECRET` (its account's), `AUTH_WEB_CLIENT_SECRET`, `<ID>_PUBLIC_URL`, `<ID>_SESSION_KEY`, `AGENT_URL`, and `DATABASE_URL` unless it has no database; its own `config/<service>.env` adds `LISTEN_ADDR` and anything else.

In Go, `t10kit/module` answers all of the routes: a module fills in a `module.Module` (its ID, label, access and tools) and registers it on its mux, beside its own routes. `module.Fake` stands in for auth-server in its tests. The kit's own tests cover what every module answers, so a module's tests cover only its tools and API. A module in another language answers the same routes itself; the kit is the reference.

## Its folder: `modules/<id>/`

| Path | Holds |
| --- | --- |
| `source.env` | `SRC`, its folder in `src/`; `REPO` only when it has a repo of its own |
| `versions.env` | `T10_<ID>`, its image on servers, pinned to `sha-<commit>@<digest>`. For code in the project, `TODO` until `make release`; local runs don't use it |
| `config/<service>.env` | Its service's settings |
| `config/local/settings.env` | Its address and port on this machine, `<ID>_PUBLIC_URL` and `<ID>_PORT` |
| `config/server/settings.env` | `<ID>_PUBLIC_URL=TODO`, which each server environment sets in `site/config/<env>/` |
| `compose/scripted.yml` | `SCRIPTED_TOOL_<ID>`: the tool the scripted model calls, so `make smoke` sees a turn reach it |
| `compose/<name>.yml` | Optional: changes to its standard wiring for that name, such as a setting it needs on auth-server or its own secret on its service |
| `secrets.json`, `init-db.sh` | Optional: secrets beyond the standard ones; database setup after its database and login exist |
| `hooks/seed-demo.sh`, `hooks/smoke.py` | Optional: its demo data, after the foundation's; its own checks, after the shared ones (`scripts/smoke.py` says what it's given) |
| `pack/` | Own repo only: the pack, copied by `make sync-module`. Never edited here. A module without `pack/module.env` isn't part of the stack yet |
| `README.md`, `docs/` | What it is, and what to know before deploying it |

Names follow from the ID, so nothing outside its folders needs to know them: its settings and secrets start with `<ID>_` (`CRM_PUBLIC_URL`, `CRM_DB_PASSWORD`), its image is `T10_<ID>`, an account's secret is the account's name in capitals with `_SECRET`.

## On a server

Set `IMAGE_REGISTRY` (such as `ghcr.io/<owner>`) in `site/config/settings.env`, commit, and run `make release MODULE=<id>`: it builds the image from `src/<id>/` as committed, pushes it, and pins it in `modules/<id>/versions.env`. `make check ENV=<env>` fails while the pin is `TODO`, or when `src/<id>/` has changed since the pinned release, since a server would run old code with a newer pack. Each server environment sets the module's address in `site/config/<env>/settings.env`, and `make secrets-init ENV=<env>` adds its secrets.

## A module in its own repo

```sh
make new-module ID=crm SERVICE=t10-crm PORT=18076 REPO=https://github.com/xiant10/t10-crm.git
# give its image a pack, pin it in modules/crm/versions.env
make sync-module MODULE=crm
make up && make check && make smoke
```

To work on its code here, `make clone`, then `DEV=1 make up` builds it from `src/`. Its pack still comes from `modules/<id>/pack/`, so after changing the catalog, agent or clients, build its image and copy the pack from it: `IMAGE=t10-crm:dev make sync-module MODULE=crm`. A change in both places is a commit in the module's repo, then one in the project that pins the new image and its pack.

## Removing one

Delete `modules/<id>/` and `src/<id>/`, and its values from each `site/secrets/<env>.env`: `make check` refuses a secret that's no longer in any inventory, so a misspelled name can't hide.

t10-agent-control keeps routing a removed module's agent pool, and refuses a route document without it until it's retired, which `agentctl` can't do yet (upstream U17). `make up` warns when that happens. On local, `make down-all && make up` starts afresh; on a server, keep the module's agent until the foundation can retire its pool.

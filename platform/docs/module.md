# Building a module

A module is the business part of a project: a service with, as it needs them, its own database, web app, tools and agents, plugged into the foundation. This is what a module provides, where each part lives, and how to work on one. Where things live in a project overall is [`guide.md`](guide.md).

## In short

```sh
make new-module ID=crm            # deployment in modules/crm/, code in modules/crm/src/
make test MODULE=crm              # its tests, in Docker
make up && make smoke             # built from modules/crm/src/, run with the foundation, checked end to end
```

It runs as it is. Then make it yours:

| Change | Where | Then |
| --- | --- | --- |
| A tool | `modules/<id>/src/tools.go`, with a test in `server_test.go` | `make test MODULE=<id>`, `make reload MODULE=<id>` |
| An API or the web app | `modules/<id>/src/server.go` and files beside it | The same |
| A permission, role or action | `modules/<id>/src/module/permissions/<id>.yaml`. An action a tool uses goes in its `agent` block, and nowhere else | `make reload MODULE=<id>`, which restarts what reads the pack |
| Its agent's instructions | `modules/<id>/src/module/agents/<id>/` | `make reload MODULE=<id>` |
| Its data | Migrations in its code, run at start, against the database it's given | `make reload`, or `make down-all && make up` for a fresh database |
| A setting | `modules/<id>/config/<service>.env` | `make up` |
| A secret beyond the standard ones | `modules/<id>/secrets.json` (or `src/module/secrets.json`), in the form of `platform/foundation/secrets.json`, with an `env` naming the service and variable that get it ([`guide.md`](guide.md#secrets)) | `make up` |
| What it has: a web app, tools, agents, a database | `CAPABILITIES` in `modules/<id>/src/module/module.env` ([below](#what-it-has)) | `make contract MODULE=<id>`, `make up` |
| Another agent, or a worker beside its service | `AGENTS`, `SERVICES` in `module.env` ([below](#what-it-has)) | `make reload MODULE=<id>` |
| Its demo data, extra checks, steps around a command | `modules/<id>/hooks/<event>.sh` or `.py` (or `src/module/hooks/`), such as `seed-demo.sh` and `smoke.py` ([`guide.md`](guide.md#hooks)) | `make seed-demo`, `make smoke` |
| Commands of its own | `modules/<id>/module.mk`, included by the Makefile | `make help` lists them |

Commit `modules/<id>/` as one change to the module. Before calling it done, `make verify` runs everything from empty volumes.

A module is proven alone before it meets the foundation: `make test` (its code), then `make contract MODULE=<id>` (it keeps the contract, run by itself with its own Postgres and auth-server stood in for), then `make up && make smoke` (it plugs in). The gates, and what each proves, are [`integration.md`](integration.md).

## What the template gives every module

A module's own folders hold only what's particular to it. The rest is the template's, so a fix there reaches every module with `make template-update`:

- **Its wiring** (`scripts/wiring.py`). On every command, `scripts/render.py` writes from its `module.env`, into the bundle: a one-shot `<id>-db` that makes its database and login (on every start, so a module joins a running stack); a one-shot `<id>-seed` that adds its accounts to auth-server; its agents, copied into agent-ti, with their runtimes' secrets; its service, with the standard settings below, a read-only filesystem and a healthcheck on `/readyz`, and any more services it lists; and `ai-gateway-tools` and `workbench` waiting for it. On local, its port on `127.0.0.1`, and for code in the project, its build from `modules/<id>/src/`.
- **Its standard secrets**: `<ID>_DB_PASSWORD`, each account's `<ACCOUNT>_SECRET` (such as `T10_CRM_SECRET` and `AGENT_TI_CRM_SECRET`), `<ID>_WEB_CLIENT_SECRET` and `<ID>_SESSION_KEY`.
- **Its place in the foundation**: its grants on the harnesses, its tool server on `ai-gateway-tools`, its workbench entry, its app on auth-server's landing page, its agents' routes, its catalog and its OAuth clients, all from its pack.

Each comes only with the capability that needs it ([below](#what-it-has)).
- **Its service's common code** (`kit/go/`, for a module written in Go): the token verifier, a person's and an agent's access checked against auth-server, the MCP server for its tools, and the routes every module answers. Its own code is its tools, its web app, and its tests.

Its folder can change any of the wiring: `modules/<id>/compose/base.yml` (or `local.yml`, …) is read after the standard file for the same name and merged over it by Compose. It can add to the foundation's inputs as any part can (`clients.json`, `agent-routes.json`, `permissions/`, `part.env`: [`guide.md`](guide.md#what-a-part-adds)), after what its pack adds.

## What it has

`CAPABILITIES` in `module.env` says which of these a module has, and each brings its own wiring, secrets, checks and smoke steps, and nothing for what it doesn't have:

| Capability | Brings | Its pack then needs |
| --- | --- | --- |
| `web` | A public address (`PUBLIC_URL_SETTING`) and Caddy site on a server, `<ID>_WEB_CLIENT_SECRET`, `<ID>_SESSION_KEY` and its web OAuth client (`<service>-web`), its workbench entry and its app on auth-server's landing page, and a browser sign-in in `make smoke` | Its app's home at `/t/<tenant>/` ([below](#its-web-app)); in Go, `t10kit/module` serves sign-in, sign-out and the frame |
| `tools` | Its MCP server on `ai-gateway-tools`, `SCRIPTED_TOOL_<ID>` for the scripted model, and its catalog's `agent` block given to the harnesses, its agents and the runtimes that run its tools | An `agent` block in its catalog naming its actions, with its service as the audience; tools named `<id>_…` at `/mcp` |
| `agent` | Each agent in `AGENTS`: its folder copied into agent-ti, its route and pool, its runtime account and OAuth runtime (`agent-ti-<agent>`) and secret on agent-ti, and a turn with it in `make smoke` | `agents/<agent>/` for each |
| `database` | `<id>-db`, its database and login, and `DATABASE_URL` | Migrations in its code (or `init-db.sh` in its pack) |

Every module keeps the HTTP contract on `SERVICE` ([below](#its-service)): `/readyz`, `/v1/module` and `/v1/access`, and `/mcp` with `tools`. One without `web` is published only on this machine, at its local port, where `make smoke` and `make contract` reach it.

**Agents.** `AGENTS=crm,crm-intake` gives a module two agents, each a folder in `agents/`. Each one's runtime account is `agent-ti-<agent>` unless `AGENT_RUNTIME_<AGENT>` says otherwise, and its name in the picker `AGENT_TITLE_<AGENT>`. The first agent's `agent.json` reads its runtime's secret from `${<ID>_AUTH_CLIENT_SECRET}`, any other's from `${<AGENT>_AUTH_CLIENT_SECRET}` (`CRM_INTAKE_AUTH_CLIENT_SECRET`). Every agent gets what the catalog's `agent` block says its tools need, unless `AGENT_ACTIONS_<AGENT>` restricts that agent to a subset of actions.

**More services.** `SERVICES=t10-crm-worker` adds services that run the module's image beside `SERVICE`, with the same standard settings, `DATABASE_URL`, `AUTH_CLIENT_SECRET` (`SERVICE`'s account), read-only filesystem and server limits, but no port or healthcheck. Give each its command and anything else in `modules/<id>/compose/base.yml`, and its settings in `modules/<id>/config/<service>.env`.

**What it needs.** `REQUIRES=livekit,crm` names foundation components or other modules it can't run without. Every command refuses a project where one is missing, naming it.

## Where its code is

| | In the project (the default) | In a repo of its own |
| --- | --- | --- |
| Made with | `make new-module ID=<id>` | `make new-module ID=<id> SERVICE=<service> PORT=<port> REPO=<url>` |
| Its code | `modules/<id>/src/`, committed in the project | Its repo, cloned into `modules/<id>/src/` by `make clone`, kept out of the project's git |
| Its pack | `modules/<id>/src/module/`, read as it is | `modules/<id>/pack/`, copied from its pinned image by `make sync-module` |
| On local | Always built from `modules/<id>/src/` by `make up` | Its pinned image; built from `modules/<id>/src/` with `DEV=1` |
| On a server | Its image from `make release`, pinned in `modules/<id>/versions.env` | Its image as its own CI publishes it, pinned the same way |
| Tests | `make test`, then the whole stack with `make smoke` | Its own repo's CI, then `make smoke` |

Code in the project suits a module built for this project: one commit changes its code, its permissions and its deployment, and nothing needs publishing to try it. A repo of its own suits a module several projects share, such as `t10-property`. A module can move from one to the other by moving its code and changing `source.env`.

## Its image and pack

The service's image ships a **pack** at `/module`, so its deployment always matches the service's version. For code in the project the pack is `modules/<id>/src/module/`, which the Dockerfile copies to `/module`.

| Path | Holds | Used by |
| --- | --- | --- |
| `module.env` | Facts a deployment needs, below. Nothing secret, nothing per environment | The scripts, and its standard wiring |
| `permissions/<id>.yaml` | Its permission catalog (JSON, which auth-server reads as YAML), with an `agent` block naming the `actions` and `audience` its agent tools need: the one place that's said | auth-server, and the scripts, which give it to every place below |
| `agents/<agent>/` | An agent folder for agent-ti, for each of `AGENTS`; `agent.json` reads its runtime secret as [above](#what-it-has) | `t10-agents`, which copies it into agent-ti |
| `secrets.json`, `init-db.sh`, `hooks/`, `clients.fragment.json` | Optional: secrets, database setup, hooks or extra OAuth clients/runtimes that travel with the module's image | Merged before `modules/<id>/`'s own |

What its tools need, from the catalog's `agent` block, is added to each agent's own grant, to each of its runtimes and the foundation runtimes that run module tools, and to the harnesses' `GRANT_ACTIONS` and `GRANT_AUDIENCES`. `make check` confirms it reached each one.

`module.env` sets:

| Key | Means |
| --- | --- |
| `PACK_VERSION` | The pack format it's written in, `1`. The template reads the versions in `PACK_VERSIONS` (`scripts/wiring.py`) and refuses any other, so a module released for a newer template can't be misread by an older one, or the reverse |
| `MODULE_ID` | The ID: the folder name in `modules/`, the action prefix, and `T10_<ID>` for its image |
| `SERVICE`, `PORT` | Its Compose service and auth-server account, and the port it listens on |
| `CAPABILITIES` | What it has, of `web`, `tools`, `agent` and `database` ([above](#what-it-has)) |
| `AGENTS` | With `agent`: its agents, each a folder in `agents/`; `AGENT_TITLE_<AGENT>`, `AGENT_RUNTIME_<AGENT>` and `AGENT_ACTIONS_<AGENT>` optional for each |
| `PUBLIC_URL_SETTING` | With `web`: the setting holding its web app's public address, `<ID>_PUBLIC_URL` |
| `SERVICE_ACCOUNTS` | Optional: accounts in auth-server beyond `SERVICE` and each agent's runtime |
| `SERVICES` | Optional: more services from its image, such as a worker |
| `REQUIRES` | Optional: components or modules it needs |
| `SCRIPTED_TOOL` | Optional, with `tools`: the tool `SCRIPTED=1` calls (default `<id>_whoami`, or `none`) |
| `GRANT_ACTIONS`, `GRANT_AUDIENCE`, `GRANT_AUDIENCES` | Optional: more than the catalog's `agent` block says |

A pack written before v0.6.0 has no `PACK_VERSION` or `CAPABILITIES`. It reads as version 1 with `web`, `tools`, `database` unless `DATABASE=false`, and `agent` when `AGENT` names one, with `AGENT_TITLE` and `AGENT_RUNTIME` for it; `make contract` asks for the new keys.

## Its service

What a project expects of every module's service, which `make smoke` checks:

- `GET /readyz` answers 200 when it's ready.
- `GET /v1/module` returns its manifest, with `action_prefix` equal to `MODULE_ID`. Workbench reads it.
- `GET /v1/access` tells a signed-in person what they may do; a tenant admin gets `tenant_admin: true`.
- `GET /v1/notifications` answers Workbench's bell, which polls it every 30 seconds for each open tab: `{"notifications": [...], "cursor": "..."}`, empty when it has none, and `POST /v1/notifications/read` takes `{"ids": [...]}`.
- With `web`, `GET /v1/me/nav` lists the person's sections of its app, and `GET /t/<tenant>/` is its app's home ([below](#its-web-app)).
- With `tools`, `/mcp` serves its tools, which `ai-gateway-tools` lists for the harnesses. Calling one needs an agent's delegated token for the person it acts for.
- With `agent`, it sends assistant turns to `AGENT_URL` (ai-gateway-agent) with `Agent-Name: <agent>`, and each agent answers one.

The standard wiring gives it these settings: `AUTH_ISSUER`, `AUTH_URL`, `AUTH_CLIENT_SECRET` (its account's), `AGENT_URL`, with `web` `AUTH_WEB_CLIENT_SECRET`, `<ID>_PUBLIC_URL` and `<ID>_SESSION_KEY`, and with `database` `DATABASE_URL`; its own `config/<service>.env` adds `LISTEN_ADDR` and anything else.

In Go, `t10kit/module` answers all of the routes: a module fills in a `module.Module` (its ID, labels, sections, access and tools, and a `Notifier` once it has notifications) and registers it on its mux, beside its own routes. For `web`, it also serves sign-in, sign-out and the frame ([below](#its-web-app)), and `m.Person` checks either a Bearer token or the encrypted session cookie. `module.Fake` stands in for auth-server in its tests (`Bearer person`, `Bearer person:<perms>`, `Bearer agent`, `Bearer agent:<perms>`). What the module does as itself, rather than for a person, goes through `module.Service`, which both `Auth` and `Fake` are (`svc := access.(module.Service)`): `svc.ServiceToken(ctx)` is its own token, cached and renewed, for any client that calls auth-server or another service as the module, and `svc.Members(ctx, tenant)` is a tenant's active members with their org units, for addressing people. `Fake`'s members are its `Caller` alone. The kit's own tests cover what every module answers, so a module's tests cover only its tools and API. A module in another language answers the same routes itself; the kit is the reference. `make new-module SCAFFOLD=<lang>` starts one from `platform/scripts/scaffold/<lang>/`, of which `go` is the only one yet: another is a folder there with the same tokens (`__id__`, `__ID__`, `__Id__`, `__service__`, `__port__`), a `module/` pack, and a Dockerfile with a `test` stage that `make test` builds, and runs beside a Postgres when it's labelled `t10.test=run` ([integration.md](integration.md)).

## Its web app

A module with `web` has an app of its own at `<ID>_PUBLIC_URL`, which Workbench links to and auth-server lists in every app's Apps list. What a project expects of it:

- **Its address.** Workbench and the Apps list open it at `<ID>_PUBLIC_URL/t/<tenant>/`, so that's its home, and every page of it is a path under it. A page refuses a tenant that isn't the signed-in person's. Its bare address can send them to their tenant's home.
- **Its sections.** `GET /v1/me/nav` lists the sections this person may open, as `{"sections": [{"key", "to", "label", "label_zh", "group"}]}`, where `to` is a path under `/t/<tenant>/` and `group` is `daily`, `records` or `setup`. The manifest's `app.nav` lists every section, and `app.label_zh` its Chinese name; Workbench shows the person's under the app's entry.
- **Who sees it.** auth-server lists an app only for a person who holds one of its module's permissions (or administers the tenant). A module whose app every member uses still needs one: the scaffold's catalog has `<id>:use` and a `member` template that grants it, which a tenant admin gives its users. Without it, the app is missing from their Apps list though they could use it (upstream U18).
- **Sign-in and sign-out.** `GET /auth/login?next=<path>&tenant=<tenant>` signs in through auth-server's `/v1/authorize`; `POST /auth/logout` ends the app's session, then auth-server's sign-in and every other t10 app's in that browser, and auth-server returns the browser to `GET /signed-out`.
- **Looking like Workbench.** Its pages wear the frame every t10 app does: the rail with its sections, the same Apps list, and the account menu with language, theme, Account and Sign out, in Workbench's tokens, light and dark.

In Go, the kit does all of it. A page's handler starts with `c, ok := s.PersonPage(w, r)`, which sends a browser that isn't signed in to sign-in and back, and one signed in to another tenant to this one, once; an API keeps `s.Person`, which answers 401. `s.View(r, c)` reads the person's language, theme, name and Apps list from auth-server, and `s.Page(w, r, v, module.Page{Title, Section, Body})` draws the page's body in the frame, with `module.Styles` (cards, rows, buttons, inputs, notices) available to it. `Module.Sections` lists the sections, each with its `Allowed` check; the account menu posts to `/frame/language` and `/frame/theme`, which save the choice with auth-server for every app. `s.Token(r)` is the person's own token, to call auth-server or another service as them. The scaffold's `server.go` does all of this for its placeholder page. A module whose app is React uses the web kit in Workbench's `web/src/kit/` instead, and answers the same routes.

## Its folder: `modules/<id>/`

| Path | Holds |
| --- | --- |
| `source.env` | `SRC=src`, its code's folder, `modules/<id>/src/`; `REPO` only when it has a repo of its own |
| `versions.env` | `T10_<ID>`, its image on servers, pinned to `sha-<commit>@<digest>`. For code in the project, `TODO` until `make release`; local runs don't use it |
| `config/<service>.env` | Its service's settings |
| `config/local/settings.env` | Its address and port on this machine, `<ID>_PUBLIC_URL` and `<ID>_PORT` |
| `config/k8s-local/settings.env` | Its address and port on this machine's Kubernetes |
| `config/server/settings.env` | `<ID>_PUBLIC_URL=TODO`, which each server environment sets in `site/config/<env>/` |
| `compose/<name>.yml` | Optional: changes to its standard wiring for that name (`base`, `local`, `server`, `build`, `scripted`), such as a setting it needs on auth-server or its own secret on its service |
| `secrets.json`, `init-db.sh` | Optional: secrets beyond the standard ones; database setup after its database and login exist (or in its pack: [below](#its-pack-or-its-folder)) |
| `hooks/<event>.sh` or `.py` | Optional: such as `seed-demo.sh`, its demo data, after the foundation's, and `smoke.py`, its own checks, after the shared ones ([`guide.md`](guide.md#hooks) lists the events and what each is given; or in its pack: [below](#its-pack-or-its-folder)) |
| `clients.json`, `agent-routes.json`, `permissions/`, `part.env` | Optional: additions or changes to the foundation's inputs, after what its pack adds ([`guide.md`](guide.md#what-a-part-adds)) |
| `module.mk` | Optional: make targets of its own |
| `pack/` | Own repo only: the pack, copied by `make sync-module`. Never edited here. A module without `pack/module.env` isn't part of the stack yet |
| `README.md`, `docs/` | What it is, and what to know before deploying it |

## Its pack or its folder

`secrets.json`, `init-db.sh`, `hooks/` and the foundation additions can go in either place. The rule: **the pack holds what the module needs wherever it runs; its folder holds what this project changes about it.**

- In the pack (`modules/<id>/src/module/`, or the image's `/module`): what travels with its code and version, such as a secret its service reads, the tables its migrations expect, its demo data and its own smoke checks. A project that pulls its image gets them with no copying.
- In its folder (`modules/<id>/`): this project's choices about it, such as a secret given to another service, extra setup for this project's data, or a redirect URI for its domain.

Both are read, the pack's first: `secrets.json` entries and additions merge, the folder's winning; both folders' hooks run. `init-db.sh` is the exception: `<id>-db` runs one, so a folder's replaces the pack's, and `make check` warns when both exist. For a module whose code is in the project, put everything in the pack unless it's truly about this project only: then a move to a repo of its own takes nothing extra.

Names follow from the ID, so nothing outside its folders needs to know them: its settings and secrets start with `<ID>_` (`CRM_PUBLIC_URL`, `CRM_DB_PASSWORD`), its image is `T10_<ID>`, an account's secret is the account's name in capitals with `_SECRET`.

## On a server

Set `IMAGE_REGISTRY` (such as `ghcr.io/<owner>`) in `site/config/settings.env`, commit, and run `make release MODULE=<id>`: it builds the image from `modules/<id>/src/` as committed, pushes it, and pins it in `modules/<id>/versions.env`. `make check ENV=<env>` fails while the pin is `TODO`, or when `modules/<id>/src/` has changed since the pinned release, since a server would run old code with a newer pack. Each server environment sets the module's address in `site/config/<env>/settings.env`, and `make secrets-init ENV=<env>` adds its secrets.

## A module in its own repo

```sh
make new-module ID=crm SERVICE=t10-crm PORT=18076 REPO=https://github.com/xiant10/t10-crm.git
# give its image a pack, pin it in modules/crm/versions.env
make sync-module MODULE=crm
make up && make check && make smoke
```

To work on its code here, `make clone`, then `DEV=1 make up` builds it from `modules/<id>/src/`. Its pack still comes from `modules/<id>/pack/`, so after changing the catalog, agent or clients, build its image and copy the pack from it: `IMAGE=t10-crm:dev make sync-module MODULE=crm`. A change in both places is a commit in the module's repo, then one in the project that pins the new image and its pack.

## Removing one

Delete `modules/<id>/`, and its values from each `site/secrets/<env>.env`: `make check` refuses a secret that's no longer in any inventory, so a misspelled name can't hide.

t10-agent-control keeps routing a removed module's agent pool, and refuses a route document without it until it's retired, which `agentctl` can't do yet (upstream U17). `make up` warns when that happens. On local, `make down-all && make up` starts afresh; on a server, keep the module's agent until the foundation can retire its pool.

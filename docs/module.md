# The module contract

What a business module provides so a project can run it on the foundation, and what its folder in a project holds. `make new-module` writes a folder in this shape. The first module built this way is `t10-property`: its repo's `module/` folder is a worked pack.

## Its image

The module's service image ships a **pack** at `/module`, so the deployment always matches the service's version:

| Path in the image | Holds | Used by |
| --- | --- | --- |
| `/module/module.env` | Facts a deployment needs, below. Nothing secret, nothing per environment | `scripts/render.py`, `check.py`, `smoke.py` |
| `/module/permissions/<id>.yaml` | Its permission catalog, with an `agent` block naming the `actions` and `audience` its agent tools need | auth-server's `AUTH_PERMISSIONS_DIR` |
| `/module/agents/<AGENT>/` | Its agent folder for agent-ti; `agent.json` reads its runtime secret from `${<ID>_AUTH_CLIENT_SECRET}` | `t10-agents`, which copies it into agent-ti's agents |
| `/module/clients.fragment.json` | Its OAuth clients, its runtimes, and `runtime_grants`: the foundation runtimes that get its grant | Merged into auth-server's `clients.yaml` |

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

`make smoke` checks each of these for every module.

## Its folder: `modules/<id>/`

| Path | Required | Holds |
| --- | --- | --- |
| `pack/` | Yes | The pack, copied from the pinned image by `make sync-module MODULE=<id>`. Never edited here. A folder without `pack/module.env` isn't part of the stack yet |
| `versions.env` | Yes | `T10_<ID>`, its image, pinned to `sha-<commit>@<digest>` |
| `compose/base.yml` | Yes | Its service; its database login (`postgres`); a one-shot `<id>-seed` adding its service accounts; its agent folder mounted into `t10-agents` at `/module-agents/<AGENT>`; its agent's runtime secret on `agent-ti`; and `ai-gateway-tools` and `workbench` waiting for it |
| `compose/local.yml` | Yes | Its port published on 127.0.0.1 |
| `secrets.json` | Yes | Every secret it adds, in the form of `foundation/secrets.json` |
| `config/` | Yes | `<service>.env`, its service's settings; `settings.env`, values foundation services need from it; and a folder per layer: `local/` with its address and port, `server/` with `TODO` where a project must decide |
| `source.env` | For `DEV=1` | `SRC` and `REPO`: `make clone` fetches it into `src/<SRC>/` |
| `compose/build.yml` | For `DEV=1` | Its service built from `src/<SRC>/` |
| `init-db.sh` | With a database | Its database and its own login, run once when the Postgres volume is new |
| `compose/scripted.yml` | Optional | `SCRIPTED_TOOL_<ID>`: the tool the scripted model calls, so `make smoke` sees a tool call reach it |
| `hooks/seed-demo.sh` | Optional | Its demo data, after the foundation's, from `make seed-demo` |
| `hooks/smoke.py` | Optional | Its own checks, after the shared ones (`scripts/smoke.py` says what it's given) |
| `k8s/` | Later | Its Kubernetes component (phase E) |
| `README.md`, `docs/` | | What it is, and what to know before deploying it |

Names follow from the ID, so nothing outside the folder needs to know them: settings and secrets start with `<ID>_` (`CRM_PUBLIC_URL`, `CRM_DB_PASSWORD`), its service account's secret is `<SERVICE>_SECRET`, and its agent's is `AGENT_TI_<ID>_SECRET`.

## Adding one

```sh
make new-module ID=crm SERVICE=t10-crm PORT=18076 REPO=https://github.com/xiant10/t10-crm.git
# give its image a pack, pin it in modules/crm/versions.env
make sync-module MODULE=crm
grep -rn TODO modules/crm          # fill each in, and add what only this module needs
make up && make check && make smoke
```

Its grants, tool server, agent route, workbench entry, catalog, clients and secrets reach the foundation from its folder, with no change anywhere else. Locally, `make up` adds its generated secrets to `site/secrets/local.env`; a server needs `make secrets-init ENV=<env>`.

`make new-module` writes what every module has. What's particular to one, such as an extra sign-in method or a key that encrypts its data, is added by hand. Tested Nov 16: `t10-property` scaffolded this way, plus its own additions, matched its hand-written folder line for line.

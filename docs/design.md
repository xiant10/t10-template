# Business modules on the published t10 foundation

Nov 15, 2026 · Revised Nov 16 to describe what's built: the Compose stack, which passes `make check` and `make smoke`, and the split into a template any project can reuse. Kubernetes and prod aren't built yet. They're in [`plan.md`](plan.md). Day-to-day use is in [`guide.md`](guide.md).

A project made from this template deploys one or more business modules on the t10 foundation. It uses the foundation only through its published images and the configuration those images read. It changes no foundation source, builds no foundation image and needs no foundation checkout. The first such project deploys `t10-property`; the examples below use a module `<id>` with service `<service>`, and `crm` where a name helps.

**Decided Nov 15–16:**

- All traffic goes through `ai-gateway`: `agent` for turns, `llm` for model calls and `tools` for tool calls. No profile runs without it.
- No image pull secret for now. There's room to add one (see `plan.md`).
- Production secrets: SOPS with age, with the operator's key and an offline break-glass key. See `plan.md`.
- A project's root repo can stay local; module repos keep their remotes, since their CI publishes the images.
- What we learn goes back to the foundation through a tracked list, [`upstream.md`](upstream.md).
- This repo is a template: nothing outside `modules/` and `site/` names a module or a project.

## Goals

- **Foundation as images.** Every foundation service comes from `ghcr.io/xiant10/*` at a pinned tag. Upgrading the foundation means changing a version file.
- **The module owns its integration.** A module's permissions, OAuth clients, agent, tool routes and database live in its image and its folder. They aren't stored in `t10-agents`, the workspace's `deploy/k8s/catalog/` or `auth-setup`.
- **One description, two targets.** Docker Compose for development, demos and a small team's prod, and Kubernetes (kustomize) for real clusters. Both use the same images and the same module files. Compose is built; Kubernetes is planned.
- **Repeatable.** A new module adds a `modules/<id>/` folder and gets the same commands. A new project starts from the template and adds its modules and `site/`.

Not a goal: changing how the foundation works. If something can't be done through configuration, it goes on `upstream.md` instead of being patched.

## How a module plugs into the foundation

The foundation already exposes everything a module needs as configuration. Each extension point was checked against the foundation's source. What a module supplies:

| Foundation image | Extension point | What a module supplies |
| --- | --- | --- |
| `auth-server` | `AUTH_PERMISSIONS_DIR`: a folder of module catalogs | `<id>.yaml`, its permissions, role templates, and its `app` and `agent` blocks |
| `auth-server` | `AUTH_CLIENTS_FILE`: OAuth clients and runtimes | Its web client, its runtimes, and its actions (such as `crm:read`) on every runtime that calls its tools |
| `auth-server` | `AUTH_APP_URLS` | `<id>=<public URL of the app>` for the landing page |
| `auth-server` (contains `authctl`) | `authctl service-add` | Service accounts `<service>` and `agent-ti-<id>`, created by its own seed step instead of `auth-setup`'s fixed list |
| `workbench` | `MODULE_URLS` | `<id>=http://<service>:<port>` |
| `agent-ti` + `t10-agents` | The agents folder `/etc/agent-ti/agents`, and `${VAR}` substitution in `agent.json` | Its agent folder, and `<ID>_AUTH_CLIENT_SECRET` |
| `agent-ti`, `agent-pi` | `GRANT_ACTIONS` and `GRANT_AUDIENCES` | Its actions, and its service as an audience |
| `ai-gateway` (tools role) | `TOOL_SERVERS` and `TOOL_MODULE_SERVERS` | `<id>=<service>@http://<service>:<port>/mcp`, listed under `/mcp/modules` |
| `postgres` | Init scripts | Its own database and login |
| `t10-knowledge` | None. Used as is | Nothing; its agent can call `knowledge_search` |

**This needs no foundation change.** `agent-ti` reads its agents from a folder and substitutes environment variables into `agent.json`. `auth-server` reads catalogs from a folder and clients from a file. The gateway reads its tool list from environment variables. A module is therefore files and environment variables, and the design gives them one place to live.

## Repository layout

The layout and who owns each part are in [`guide.md`](guide.md#who-owns-what). In short: `foundation/`, `modules/<id>/` and `site/` are parts shaped alike, layered in that order. `scripts/lib.py` finds every `modules/<id>/` with a `pack/module.env`, and every script treats the parts the same way, so no script, Compose file or foundation setting names a module. What a module provides is the contract in [`module.md`](module.md).

`site/` exists so a project never edits the template. Anything a project decides (its Compose project name, ports, public addresses, the deploy host, a token lifetime) overrides the template's defaults from `site/`, and `foundation/` keeps a `TODO` where there's no sensible default, which `make check ENV=prod` refuses.

### Why the template is a repo, not a tool

A project is made by copying the template repo and keeps it as a git remote. Template changes arrive by merging that remote. Because a project edits only `modules/`, `site/` and `README.md`, and overrides the template from `site/` rather than editing it, those merges don't conflict. Submodules or a generator such as copier would add a tool and a second place to look for little gain.

### Why separate repos for modules

A module keeps its GitHub remote, because its CI publishes the image every environment pulls. It builds and tests on its own, as every foundation sub project does. The project decides what runs together, at which versions and with which secrets. Keeping them apart means:

- a module release doesn't redeploy anything,
- one deployment can hold several modules,
- environments (local, staging, a customer's host) differ only in the project repo.

Both are worked on from the project's folder: module repos are cloned into `src/`, which the project ignores. A change that touches both, such as a new permission plus its role in the clients file, is one commit in each, and the project's commit pins the new image.

## The module pack

Some facts only the module knows: its permissions, its agent, the actions its tools need. Those stay in the module's repo and ship in its image, so the pack always matches the service version.

1. The module repo's `module/` holds `module.env`, `agents/<agent>/` and `clients.fragment.json`. Its Dockerfile copies the folder to `/module`, with its permission catalog at `/module/permissions/<id>.yaml`.
2. `make sync-module MODULE=<id>` copies `/module` out of the pinned image with `docker create` and `docker cp` into `modules/<id>/pack/`. It commits nothing on its own.
3. `make check` fails if `modules/<id>/pack/` differs from the image pinned as `T10_<ID>`. It skips the check while the pinned image has no pack.

`module.env` holds the facts the project's scripts need: `MODULE_ID`, `SERVICE`, `PORT`, `GRANT_ACTIONS`, `GRANT_AUDIENCE`, `SERVICE_ACCOUNTS`, `AGENT`, `AGENT_TITLE`, `AGENT_RUNTIME` and `PUBLIC_URL_SETTING`.

The project keeps a copy, rather than reading the image at deploy time, because the clients file is a reviewed security file whose changes should show in a diff, and because kustomize will need files when it builds manifests.

## Configuration that several modules add to

Some foundation inputs are single values that each module adds to. `scripts/render.py` builds them from each pack on every run, into `generated/<env>/`:

- **`clients.yaml`**: `foundation/clients.json` merged with each pack's `clients.fragment.json`. For existing runtimes it unions the actions and audiences. `${VAR}`, `"${sha256:VAR}"` and `"${bool:VAR}"` are filled from settings and secrets, so a web client's secret and its hash can't disagree. The files are JSON, which auth-server reads as YAML, so the scripts need nothing beyond Python's standard library.
- **`permissions/`**: `foundation/permissions/` plus each pack's catalogs.
- **`agent-routes.json`**: `foundation/agent-routes.json` plus a pool for each module's agent.
- **`modules.env`**: `MODULE_GRANT_ACTIONS`, `MODULE_GRANT_AUDIENCES`, `MODULE_TOOL_SERVERS`, `MODULE_TOOL_MODULE_SERVERS`, `MODULE_WORKBENCH_URLS` and `MODULE_APP_URLS`. `foundation/compose/base.yml` appends each to its own list, so a module's Compose files hold only the module's own services.

`make check` reproduces the foundation's `check-module-agents.py` rule. Every action in a catalog's `agent` block must be in the pack's `module.env`, in its agent's own grant, and in every runtime in `clients.yaml` that runs its tools.

## Versions

Every image is pinned as `tag@digest`, in layers like everything else:

```sh
# foundation/versions.env: the template's set, tested together
T10_AUTH_SERVER=ghcr.io/xiant10/auth-server:sha-acc963b@sha256:7fa5…
# … one per foundation image, then third-party images
# modules/<id>/versions.env: the module's own image
T10_CRM=ghcr.io/xiant10/t10-crm:…
# site/versions.env, optional: a pin this project needs to differ, such as a foundation fix
```

`render.py` merges them into the bundle's `versions.env`, later ones winning. The foundation's pins belong to the template because they're the set it was tested with; a project that must run another version says so in `site/versions.env`, where it shows as a deliberate exception.

- Never `latest`. The foundation repos have no release tags, but CI publishes `sha-<short>` tags, so we pin those, and the digest makes sure that's what's pulled. The tag also names the repo commit, so the Kubernetes work can take each repo's manifests at its own image's commit.
- A module is pinned once its image has a pack. Until then it may stay on `latest`, and `make check` skips its pack comparison.
- To upgrade: `make pin` shows what each public image's `latest` is, and `make pin WRITE=1` writes it into the `versions.env` that wins for it: `foundation/`'s in the template, or `site/`'s where a project overrides one. Then `make sync-module`, `make check`, `make up` and `make smoke`. One commit records the set of versions that worked together.
- The foundation should tag releases, so that a pin means something to people (U1).

## Environments and targets

Three things are kept apart:

- **The target** runs an environment: Docker Compose (built) or Kubernetes (planned). It's `TARGET` in the settings.
- **The environment** is a name (`local`, `dev`, `prod`, later `uat`…) with its own values and secrets. The project owns it, in `site/config/<env>/`.
- **The layers** are what the template ships for kinds of environment, in each part's `config/` and `compose/`: `local` for this machine, `server` for every server, and `dev` and `prod` on top of `server`. An environment named `local`, `dev` or `prod` uses those; any other names one as `SHAPE` and adds its own layer.

| | `local` | `dev`, `prod` (and `uat`…) |
| --- | --- | --- |
| **Compose** | Built. Ports on `127.0.0.1`, dev mode | Built. One host per environment (or several, one Compose project each), Caddy with TLS in front, Postgres in Compose; `make deploy` copies the bundle there |
| **Kubernetes** | Planned: Docker Desktop, to test the manifests | Planned: a remote cluster, ingress with cert-manager, Postgres in the cluster |

What an environment runs is the same across targets: the merged `env/<service>.env`, the secrets, and what's merged from the packs. Only the wiring differs, and each target is checked by the same `make check` and `make smoke`. The target-neutral parts, and what still has to move out of Compose before Kubernetes, are in `plan.md`.

**Dev mode is localhost only.** auth-server refuses `AUTH_DEV_MODE` unless its issuer is `localhost`, so `dev` runs auth exactly as `prod` does: signing keys required, no password grant, no sample accounts, no WeChat demo login. `dev` exists as its own layer so a shared server can differ from prod where that's safe, and so `prod`'s secret checks (no dev defaults, nothing equal to local) stay strict. U14 asks the foundation for a server-safe sign-in for checks and demo data.

## Docker Compose

**The bundle.** Compose never runs from the checkout. `scripts/compose.sh` checks the secrets, then `scripts/render.py` writes `generated/<env>/`, which holds everything that environment needs and nothing that points back into the checkout:

- each part's `compose/`, `config/`, `scripted/`, `pack/` and `init-db.sh`, copied with the repo's layout, so paths in the Compose files read the same in both places,
- `env/<service>.env`, each service's settings merged from every part (see "Layers"),
- `versions.env`, every part's merged, and the secrets as `secrets.env` (mode 600, copied from `site/secrets/<env>.env`),
- what's merged from the packs: `clients.yaml`, `permissions/`, `agent-routes.json`, `modules.env`,
- on a server, the `Caddyfile`: one site per public address, from each part's `public.json` and each module's `PUBLIC_URL_SETTING`, proxied to the service behind it,
- `compose.sh`, which runs `docker compose --project-directory .` on the bundle with its env files and Compose files in order, as Compose project `<PROJECT_NAME>-<env>`.

`scripts/compose.sh` then runs the bundle's `compose.sh`, so `make up`, `ps`, `logs` and the rest go through it. Missing secrets stop only commands that start containers. Files are rewritten in place and folders kept, so running containers see changes through their bind mounts; anything else in the folder is removed. `make check` fails if any bind mount comes from outside the bundle.

`make deploy ENV=prod` runs `make check`, copies the bundle with `rsync --inplace` (so running containers' bind mounts see new files) to `DEPLOY_DIR` on `DEPLOY_HOST` (set in `site/config/<env>/settings.env`), runs its `compose.sh up` there, and reloads Caddy. The host needs only Docker with Compose 2.24 or later, rsync, and `docker login ghcr.io`. A bundle for any environment but local refuses `DEV=1` and `SCRIPTED=1`.

**Each part's Compose files.** `compose/base.yml` holds what every environment runs, and nothing that differs by environment. `compose.sh` adds each part's `compose/<layer>.yml` for the environment's layers, then `compose/build.yml` for `DEV=1` and `compose/scripted.yml` for `SCRIPTED=1` from whichever parts have one. `local.yml` publishes the services on `127.0.0.1` and runs LiveKit in dev mode. `server.yml` publishes nothing but Caddy (80, 443) and LiveKit's media ports, and runs LiveKit with its keys and the host's public IP. Neither undoes the other: `base.yml` publishes nothing.

**`foundation/compose/base.yml`** runs the core, with every `image:` read from `versions.env`: postgres, auth-server, t10-agent-control and its one-shot route publisher, ai-gateway (`llm`, `tools`, `agent`), t10-collab, t10-knowledge, agent-ti with t10-agents, and workbench. The rest of quickstart's `compose.all.yml` is in components, `foundation/components/<name>/`, each a part like a module: `assistant` (agent-pi), `voice` (LiveKit and t10-livekit-agent), `console` and `automations`. They're all on unless a project lists them in `FOUNDATION_OFF`, which drops the part, so its services, settings, secrets and clients go with it. agent-sales isn't run (removed Nov 16). Whatever runs, every path goes through a gateway.

- **Turns.** `workbench`, `t10-automations` and modules call `ai-gateway-agent`, which takes its routes from `t10-agent-control`. The route document is the rendered `agent-routes.json`. A module's agent gets a pool on agent-ti's replicas at `/agents/<agent>`, with its own runtime as audience. It isn't a `hosts` entry under `ti`, because t10-agent-control's router never places a hosted agent. A module sends `Agent-Name: <agent>`.
- **Models.** Harnesses use `ai-gateway-llm`. Provider keys exist only there.
- **Tools.** Harnesses use `ai-gateway-tools`: `/mcp/collab`, `/mcp/knowledge`, and `/mcp/modules` for modules. `AUTH_TOOL_GATEWAY=true` on `auth-server`, so harness tokens work only at the tools gateway. The tools gateway gets no `AGENT_CONTROL_URL` for now, because that turns on tenant policy, and then every tool call is refused until a platform admin publishes one.
- **Routes.** The route publisher (`agent-routes`) only publishes when no revision exists. After a module adds or changes an agent, `make routes-publish` publishes the new document (U12).

**A module's `compose/base.yml`** contains:

- its service, with `AGENT_URL` pointing at `ai-gateway-agent`, read-only with a tmpfs `/tmp`; its `local.yml` publishes it on `127.0.0.1`;
- a one-shot seed using the `auth-server` image that runs `authctl service-add --if-missing` for its service accounts, after `seed` and before `auth-server` (U2);
- the few foundation settings only it needs, such as a sign-in setting on auth-server, its agent's client secret on agent-ti, and its pack's agent folder, mounted into `t10-agents` at `/module-agents/<agent>` so it's copied into the agents volume (U4);
- its database and login, made by its `init-db.sh` beside the foundation's own script.

**Two switches.** `DEV=1` adds each module's `compose/build.yml`, which builds it from `src/<SRC>`, the folder its `source.env` names; module images are the only ones ever built, and the only thing the bundle reads from the checkout. `SCRIPTED=1` adds `foundation/compose/scripted.yml`, which points `ai-gateway-llm` at a scripted model (`foundation/scripted/fake-model.mjs`), so `make up` and `make smoke` work with no `LLM_API_KEY`. A module's own `compose/scripted.yml` names, in `SCRIPTED_TOOL_<ID>`, a tool the scripted model calls, so a turn reaches the module through `ai-gateway-tools`.

**Hooks.** `make seed-demo` adds auth-server's sample accounts, then runs each `modules/<id>/hooks/seed-demo.sh`, which typically runs the module's own seed scripts from `src/` through `scripts/compose.sh`. Local only, because the sample password is published. `make smoke` runs each `modules/<id>/hooks/smoke.py` after its generic checks, such as an assistant turn that follows its tool call.

## Configuring containers

We change a service's settings, such as a token lifetime, a rate limit, a model alias or log level, without editing the foundation's source or any Compose file.

### Layers

From lowest to highest precedence:

| Layer | Where | Who changes it |
| --- | --- | --- |
| 1. Image defaults | The image, and wiring in `compose/base.yml` | Nobody here. They change only when a pin is bumped |
| 2. Settings for every environment | `config/<service>.env` in `foundation/`, then each module, then `site/`; files in `config/<service>/` | The template, the module's folder, the project |
| 3. Module additions | `modules/<id>/pack/`, through `generated/<env>/`: grants, tool servers, agent routes, clients | The module, through its image |
| 4. Settings for some environments | `config/<layer>/<service>.env` for each of the environment's layers in turn (`server`, then `prod`, then `uat`), each in the same part order | As in 2 |
| 5. Secrets | `site/secrets/<env>.env` (when built, decrypted from `site/secrets/<env>.enc.env` only while a command runs) | The project |

`scripts/render.py` merges 2 and 4 into `generated/<env>/env/<service>.env`, which is the service's only `env_file:`. `config/settings.env` and `config/<layer>/settings.env` in each part hold values Compose interpolates and scripts read, such as public URLs, ports, `TARGET` and `PROJECT_NAME`, layered the same way. `T10_ENV` and `T10_SHAPE` come from the bundle's `compose.sh`.

```text
foundation/config/
├── auth-server.env              AUTH_TOOL_GATEWAY=true, where the mounted files are
├── ai-gateway-llm.env           provider base URL, model names
├── ai-gateway-llm/config.yaml   model aliases, fallback, quotas (from quickstart's ai-gateway.yaml)
├── agent-pi.env  agent-ti.env  workbench.env  …
├── settings.env                 TARGET=compose
├── local/
│   ├── settings.env             public URLs and published ports on this machine (defaults)
│   └── auth-server.env          AUTH_DEV_MODE=true
└── server/
    ├── settings.env             TODO where every server must decide: addresses, deploy host, LiveKit's IP
    └── auth-server.env          AUTH_TRUST_PROXY=true, behind Caddy
modules/<id>/config/
├── <service>.env                its service's settings, such as LISTEN_ADDR
├── settings.env                 values foundation services need from it
├── local/settings.env           <ID>_PUBLIC_URL, <ID>_PORT
└── server/settings.env          <ID>_PUBLIC_URL=TODO
site/config/
├── settings.env                 PROJECT_NAME
└── <env>/settings.env           this project's values per environment; SHAPE for any beyond local, dev, prod
```

Because `environment:` would override every env file, it keeps only wiring: service addresses on the Compose network, values built from secrets, and the `MODULE_*` additions. Settings shared by many services' wiring, such as how to reach auth-server and the gateways, are YAML anchors at the top of `foundation/compose/base.yml`. Files in `config/<svc>/` are bind-mounted read-only. `make up` recreates only the containers whose settings changed.

`make config-show SVC=<service>` prints a service's effective settings and the layer each came from, with secret values masked. `make check` refuses a secret's name found among settings.

## Secrets

Each part's `secrets.json` (`foundation/`, each module, and `site/` if it adds any) is the inventory: each secret's name, its consumers, how to generate it (`hex32`, `b64key`, or `provided` by an outside party) and how to rotate it. They never hold values.

The values live in `site/secrets/<env>.env`, the only place any command reads them from, and are copied into the bundle as `secrets.env`. They were once kept in `generated/<env>/` for server environments, which made the output folder the only copy of prod's secrets; now `generated/` is always derived.

- `make secrets-init` (`ENV=` for a server) writes `site/secrets/<env>.env`, filling in random values for any that are missing and keeping existing ones. It's per checkout and not committed, since it holds `LLM_API_KEY`. `provided` values are left empty to paste in.
- `make check` fails when a required secret is missing, when the file holds a name not in the inventory, and, for `prod`, when a value is a known dev default or equals its local value.
- `make rotate NAME=…` prints the inventory's rotation steps for one secret. It doesn't run them.

Production secrets (SOPS with age) are planned; see `plan.md`.

## Feeding back to the foundation

A project is where we learn what a business module needs from the foundation. That learning goes back upstream on purpose, never as quiet edits to foundation repos.

- **[`upstream.md`](upstream.md)** lists each item: what's awkward, our workaround here, the change we'd propose and which foundation repo it belongs to, and its status.
- **Every workaround names its item**, in a comment such as `# upstream U3: …`. When the foundation fix arrives in a pinned image, `grep -rn 'upstream U3'` finds everything to remove.
- **Proposing a fix is a separate step.** It happens in `~/projects/t10` as a normal foundation change. A project picks it up only by bumping a pin.

## Checks

| Command | Checks |
| --- | --- |
| `make check` | Needs no running stack: each module's folder is named for it and its pack matches its pinned image, the environment's secrets are complete, no secret is set among settings, the grants agree, no `TODO` is left on a server, Compose renders, and the bundle mounts nothing from outside itself |
| `make smoke` | On local, after `make up`: every published service and module answers, the admin signs in, each module answers `/v1/module` and `/v1/access`, the landing page lists each module's app, every routed agent answers by name through `ai-gateway-agent`, then each module's `hooks/smoke.py`. With `SCRIPTED=1`, no identity header reached the model. On a server: every public address answers through Caddy, and auth-server serves its signing key there (U14) |
| Module CI | In the module's repo: its own tests and image publish |

Before reporting a change as done: `make down-all && make up`, then `make seed-demo`, `make check` and `make smoke`.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Put the deployment in the module's repo (`<module>/deploy`) | Ties every environment change to module releases, and a second module would have nowhere to go |
| Fork quickstart or the workspace and edit it | That changes foundation files, and upgrades become merges |
| Read the pack from the image at deploy time | The clients file's changes should be reviewed in a diff, and kustomize needs files at build time |
| Build foundation images from source | Not what was asked, and it breaks "same image everywhere" |
| A generator (copier, cookiecutter) or submodule for the template | Another tool to install and learn; a git remote and a clear ownership rule do the same |
| Remote kustomize bases, or a Helm chart for the platform | See `plan.md` |

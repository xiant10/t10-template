# Business modules on the published t10 foundation

Nov 15, 2026 · Revised Nov 16 (v0.1.0, and v0.6.0 for extending it) to describe what's built: the Compose stack, which passes `make check` and `make smoke`, and the split into a template any project can reuse. Kubernetes and prod aren't built yet. They're in [`plan.md`](plan.md). Day-to-day use is in [`guide.md`](guide.md).

A project made from this template deploys one or more business modules on the t10 foundation. It uses the foundation only through its published images and the configuration those images read. It changes no foundation source, builds no foundation image and needs no foundation checkout. The first such project deploys `t10-property`; the examples below use a module `<id>` with service `<service>`, and `crm` where a name helps.

**Decided Nov 15–16:**

- All traffic goes through `ai-gateway`: `agent` for turns, `llm` for model calls and `tools` for tool calls. No profile runs without it.
- No image pull secret for now. There's room to add one (see `plan.md`).
- Production secrets: SOPS with age, with the operator's key and an offline break-glass key. See `plan.md`.
- A project's root repo can stay local; module repos keep their remotes, since their CI publishes the images.
- What we learn goes back to the foundation through a tracked list, [`upstream.md`](upstream.md).
- This repo is a template: nothing outside `modules/`, `site/` and `src/` names a module or a project.
- A module's code lives in the project's `src/` by default, or in a repo of its own when several projects share it (Nov 16).
- What every module shares is the template's, not copied into each module: its wiring into the foundation, its standard secrets, the single place its grants are said, and the Go code every module's service needs (Nov 16, v0.1.0).
- A project extends the template without editing it: every part adds to the foundation's inputs the same way, a module says which capabilities it has, and a project has its own hooks and make targets (Nov 16, v0.6.0; [below](#extending-without-editing-the-template)).

## Goals

- **Foundation as images.** Every foundation service comes from `ghcr.io/xiant10/*` at a pinned tag. Upgrading the foundation means changing a version file.
- **The module owns its integration.** A module's permissions, OAuth clients, agent, tool routes and database live in its image and its folder. They aren't stored in `t10-agents`, the workspace's `deploy/k8s/catalog/` or `auth-setup`.
- **One description, two targets.** Docker Compose for development, demos and a small team's prod, and Kubernetes for real clusters. Kubernetes is made from Compose's resolved config (`scripts/kube.py`), so both run the same images, settings, secrets and module files. Both are built on this machine; a server cluster is planned.
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

### What a module shares is the template's

`make new-module` once wrote everything a module needs into the module's own folders: about 90 lines of Compose wiring, five secrets, a database script, and 700 lines of Go for auth, MCP and the token verifier. Those folders are the project's, which `make template-update` never touches, so each copy was frozen the day it was made. A change in how the foundation takes a module (an `authctl` flag, the agents mount, the verifier) meant the same hand edit in every module of every project.

So what's the same for every module is now worked out or imported, never copied:

- **Wiring.** `scripts/render.py` writes each module's standard Compose wiring from its `module.env` on every command (`scripts/wiring.py`), into the bundle, just before the module's own Compose files, which can change anything in it. The standard secrets come from the same place. A module's folder holds what's particular to it: its settings, its address and port, its image pin, and any changes.
- **Grants.** What a module's tools need is said once, in its catalog's `agent` block, which auth-server already reads. `render.py` gives it to the harnesses' lists, its agent's grant and the runtimes in `clients.yaml`; `make check` confirms it got there. It used to be written in four places that `make check` compared.
- **Code.** `kit/go/` is a Go module, `t10kit`, which every module's `go.mod` reaches with `replace t10kit => ../../kit/go`, and which its Docker build gets as a named build context. A module's code is its tools, its web app and their tests; the kit has the tests of what every module answers.

This keeps the rule that modules are only files and environment variables: the files a module would have written by hand are now written for it on every run, the same way `clients.yaml` and `modules.env` always were.

### Where a module's code lives

A module's code is either in the project, `src/<id>/`, or in a repo of its own. `make new-module` puts it in the project unless given a `REPO`. Decided Nov 16, revising the Nov 15 choice of separate repos for every module.

**In the project, by default.** Most modules are built for one project, and there a second repo costs more than it gives: a change to a tool, its permission and its deployment was a commit in each repo, and nothing could run until the module's CI had published an image with a pack. With the code in `src/`:

- local runs build it from `src/` and read its pack from `src/<id>/module/`, so a change is tried with `make reload`, with no image to publish and nothing to copy,
- `make test` runs its own tests in Docker, and `make smoke` checks it with the rest of the stack, in the same checkout,
- one commit holds a change to its code, its permissions and its deployment,
- servers still run a pinned image: `make release` builds it from `src/` as committed, pushes it and pins it, and `make check` fails on a server whose pin is behind `src/`.

**A repo of its own, for a module several projects share**, such as `t10-property`. Its CI publishes the image every project pulls, it builds and tests on its own as every foundation sub-project does, and each project decides which version runs with which secrets, so a module release redeploys nothing. It's worked on from the project's folder too: `make clone` checks it out into `src/`, kept out of the project's git, and a change that touches both is one commit in each, the project's pinning the new image.

A module can move from one to the other by moving its code and changing `source.env`; its `modules/<id>/` folder is the same apart from `source.env` and `pack/`.

## The module pack

Some facts only the module knows: its permissions, its agent, the actions its tools need. Those stay with the module's code and ship in its image, so the pack always matches the service version.

1. The module's `module/` folder holds `module.env`, `agents/<agent>/`, `clients.fragment.json` and `permissions/<id>.yaml`. Its Dockerfile copies the folder to `/module`.
2. For a module with its code in the project, that folder is `src/<id>/module/`, and the scripts read it there. There's no copy, so nothing can drift on local; on a server, `make check` makes sure the pinned image was built from the same commit.
3. For a module in its own repo, `make sync-module MODULE=<id>` copies `/module` out of the pinned image with `docker create` and `docker cp` into `modules/<id>/pack/`. It commits nothing on its own. `make check` fails if `modules/<id>/pack/` differs from the image pinned as `T10_<ID>`, and skips the check while the pinned image has no pack.

`module.env` holds the facts the project's scripts and the standard wiring need; its keys are listed in [`module.md`](module.md#its-image-and-pack).

The project keeps a copy, rather than reading the image at deploy time, because the clients file is a reviewed security file whose changes should show in a diff, and because kustomize will need files when it builds manifests.

## Extending without editing the template

The ownership rule only works if a project never needs to edit a template file. Up to v0.5.0 several things pushed it to: an OAuth client or catalog of the project's own could only come from a module's pack, a module had to be one service with a web app, tools, a database and at most one agent, a step around a command meant editing a script, and a command of its own meant editing the Makefile. v0.6.0 makes each of them a place the project owns:

- **Every part adds the same way.** The inputs many parts add to (clients, routes, catalogs, the foundation's lists, public addresses) are read from the same files in every part, in part order, with a module's worked-out additions just before its own folder's. `site/` adds a client like a module does, and changes one with `"_merge": true` ([`guide.md`](guide.md#what-a-part-adds)). One code path also means one place to change when auth-server takes a folder of client files (U3).
- **Capabilities, not one module shape.** `CAPABILITIES` in `module.env` (`web`, `tools`, `agent`, `database`) switches each one's wiring, secrets, checks and smoke steps, so a tools-only service or a module without a web app is first class; `AGENTS` and `SERVICES` cover several agents and a worker ([`module.md`](module.md#what-it-has)). Flat `KEY=value` lists were enough, so the pack stays a `.env` file the scripts read without a YAML library.
- **A versioned pack.** Packs in their own repos ship in images that outlive template releases. `PACK_VERSION` lets the template refuse a format it doesn't read rather than misread it; a new format adds a number and keeps reading the old ones.
- **Hooks and commands.** `hooks/<event>` in any part, and `site/project.mk` and `modules/<id>/module.mk` included by the Makefile ([`guide.md`](guide.md#hooks)).
- **Environments with their own layers,** `LAYERS`, so a `staging` layer several environments share needs no new shape.

What stays the template's: the order of the parts, the gates, and the module contract, since those are what make a template update safe to take.

## Configuration that several parts add to

Some foundation inputs are single values that each part adds to. `scripts/render.py` builds them from each part, and each module's pack, on every run, into `generated/<env>/`:

- **`clients.yaml`**: `foundation/clients.json` merged with each part's `clients.json` and each pack's `clients.fragment.json`. A second definition is refused unless it says `"_merge": true`, which adds to its lists and replaces the rest; `runtime_grants` union actions and audiences into runtimes once every part is in. `${VAR}`, `"${sha256:VAR}"` and `"${bool:VAR}"` are filled from settings and secrets, so a web client's secret and its hash can't disagree. The files are JSON, which auth-server reads as YAML, so the scripts need nothing beyond Python's standard library.
- **`permissions/`**: each part's `permissions/` plus each pack's catalogs.
- **`agent-routes.json`**: `foundation/agent-routes.json`, each part's, plus a pool for each module agent.
- **Each agent's `agent.json`**, in the bundle's copy of its pack: its grant, with what its tools need added.
- **`modules.env`**: `MODULE_GRANT_ACTIONS`, `MODULE_GRANT_AUDIENCES`, `MODULE_TOOL_SERVERS`, `MODULE_TOOL_MODULE_SERVERS`, `MODULE_WORKBENCH_URLS` and `MODULE_APP_URLS`, from each part's `part.env` and each module's pack. `foundation/compose/base.yml` appends each to its own list, so a module's Compose files hold only the module's own services.

What a module's tools need comes from its catalog's `agent` block, and is added to the harnesses' lists, its agent's grant, its own runtimes and the foundation runtimes its fragment's `runtime_grants` names. `make check` reproduces the foundation's `check-module-agents.py` rule on the result: every action in a catalog's `agent` block reached each of them.

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

- **The target** runs an environment: Docker Compose, or Kubernetes made from the same Compose bundle. It's `TARGET` in the settings.
- **The environment** is a name (`local`, `dev`, `prod`, later `uat`…) with its own values and secrets. The project owns it, in `site/config/<env>/`.
- **The layers** are what the template ships for kinds of environment, in each part's `config/` and `compose/`: `local` for this machine, `server` for every server, and `dev` and `prod` on top of `server`. An environment named `local`, `dev` or `prod` uses those; any other names one as `SHAPE` and adds its own layer.

| | `local` | `dev`, `prod` (and `uat`…) |
| --- | --- | --- |
| **Compose** | Built. Ports on `127.0.0.1`, dev mode | Built. One host per environment (or several, one Compose project each), Caddy with TLS in front, Postgres in Compose; `make deploy` copies the bundle there |
| **Kubernetes** | Built: `k8s-local`, on Docker Desktop, in a namespace of its own | Planned: a remote cluster, ingress with cert-manager, Postgres in the cluster (`plan.md` E5) |

What an environment runs is the same across targets: the merged `env/<service>.env`, the secrets, and what's merged from the packs. Only the wiring differs, and Kubernetes' is made from Compose's, so each target is checked by the same `make check` and `make smoke`. What a server cluster still needs is in `plan.md`.

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

**`foundation/compose/base.yml`** runs the core, with every `image:` read from `versions.env`: postgres, auth-server, t10-agent-control and its one-shot route publisher, ai-gateway (`llm`, `tools`, `agent`), t10-collab, t10-knowledge, agent-ti with t10-agents, and workbench. The rest of quickstart's `compose.all.yml` is in components, `foundation/components/<name>/`, each a part like a module: `assistant` (agent-pi), `livekit` (LiveKit and t10-livekit-agent), `console` and `automations`. `FOUNDATION` lists the ones that run, the template's list naming all four; one left out isn't a part, so its services, settings, secrets and clients go with it. Every image, a component's too, is pinned in `foundation/versions.env`. agent-sales isn't run (removed Nov 16). Whatever runs, every path goes through a gateway.

- **Turns.** `workbench`, `t10-automations` and modules call `ai-gateway-agent`, which takes its routes from `t10-agent-control`. The route document is the rendered `agent-routes.json`. A module's agent gets a pool on agent-ti's replicas at `/agents/<agent>`, with its own runtime as audience. It isn't a `hosts` entry under `ti`, because t10-agent-control's router never places a hosted agent. A module sends `Agent-Name: <agent>`.
- **Models.** Harnesses use `ai-gateway-llm`. Provider keys exist only there.
- **Tools.** Harnesses use `ai-gateway-tools`: `/mcp/collab`, `/mcp/knowledge`, and `/mcp/modules` for modules. `AUTH_TOOL_GATEWAY=true` on `auth-server`, so harness tokens work only at the tools gateway. The tools gateway gets no `AGENT_CONTROL_URL` for now, because that turns on tenant policy, and then every tool call is refused until a platform admin publishes one.
- **Routes.** The route publisher (`agent-routes`) only publishes when no revision exists. After a module adds or changes an agent, `make routes-publish` publishes the new document (U12).

**A module's standard wiring** (`scripts/wiring.py`, written into the bundle as `modules/<id>/standard/<name>.yml`) adds:

- its service, with the standard settings, `AGENT_URL` pointing at `ai-gateway-agent`, read-only with a tmpfs `/tmp`, and on local published on `127.0.0.1`;
- a one-shot seed using the `auth-server` image that runs `authctl service-add --if-missing` for its service accounts, after `seed` and before `auth-server` (U2);
- its pack's agent folder, mounted into `t10-agents` at `/module-agents/<agent>` so it's copied into the agents volume (U4), and its agent's client secret on agent-ti;
- its database and login, made if missing by a one-shot `<id>-db` that runs `foundation/module-init-db.sh` (then its own `init-db.sh`, if it has one) on every start, so a module added to a running stack needs no reset, and setting the password each time makes rotating it a restart.

Its own `compose/base.yml` holds only the few things particular to it, such as a sign-in setting on auth-server or a secret of its own on its service.

**Building modules.** Module images are the only ones ever built, and their source is the only thing the local bundle reads from the checkout. A module with its code in the project gets `build:` in its standard local wiring, with the template's `kit/go/` as a named build context, so every local `make up` builds it from `src/<SRC>`; servers pull its released image. A module in its own repo is pulled, unless `DEV=1` adds its standard build wiring, which builds it from its checkout in `src/<SRC>`.

**Two switches.** `DEV=1`, above, and `SCRIPTED=1`, which `make` turns on by itself on local while there's no `LLM_API_KEY`. `SCRIPTED=1` adds `foundation/compose/scripted.yml`, which points `ai-gateway-llm` at a scripted model (`foundation/scripted/fake-model.mjs`), so `make up` and `make smoke` work with no `LLM_API_KEY`. A module's own `compose/scripted.yml` names, in `SCRIPTED_TOOL_<ID>`, a tool the scripted model calls, so a turn reaches the module through `ai-gateway-tools`.

**Hooks.** Any part's `hooks/<event>.sh` or `.py` runs at that point of a command, in part order: `post-up`, `seed-demo`, `smoke`, `check`, `pre-deploy`, `post-deploy` ([`guide.md`](guide.md#hooks)). `make seed-demo` adds auth-server's sample accounts, then runs each part's `seed-demo` hook, which for a module typically runs its own seed scripts from `src/` through `scripts/compose.sh`. Local only, because the sample password is published. `make smoke` runs each `smoke` hook after its generic checks, such as an assistant turn that follows a module's tool call.

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

Where each kind of setting goes, and the layout of `config/`, are in [`guide.md`](guide.md#changing-a-setting).

Because `environment:` would override every env file, it keeps only wiring: service addresses on the Compose network, values built from secrets, and the `MODULE_*` additions. Settings shared by many services' wiring, such as how to reach auth-server and the gateways, are YAML anchors at the top of `foundation/compose/base.yml`. Files in `config/<svc>/` are bind-mounted read-only. `make up` recreates only the containers whose settings changed.

`make config-show SVC=<service>` prints a service's effective settings and the layer each came from, with secret values masked. `make check` refuses a secret's name found among settings.

## Secrets

How to work with them is in [`guide.md`](guide.md#secrets); why they're built this way:

- **Each service sees only its own.** A secret's `env` in the inventory names the services that get it and the variable, so `render.py` writes one `secrets/<service>.env` per service, and Compose files hold only wiring. On Kubernetes, the same values become one `Secret` per service, made in memory.
- **SOPS with age, in the repo** (decided Nov 15): one encrypted file per server environment, committed, which works offline, needs no service, and feeds Compose now and Kubernetes later. Whoever deploys needs an age key, and there's no automatic rotation. External Secrets would replace it once there's a cloud secret manager, keeping the same names.
- **Decrypted only in memory.** Commands read a server's values through `sops decrypt` into memory (`lib.secrets_text`); its bundle holds them only while Compose runs here or `make deploy` copies it, so the host is the only place they're on disk.
- **Rotation is described per secret** (`rotation`), so `make rotate APPLY=1` does the safe kinds (a new value, auth-server's two-phase account secrets, the signing key's `NEXT`) and prints the steps for the rest, such as a provider's key or the Postgres password.

`make check` fails when a required secret is missing, a name isn't in the inventory, a server's values are in plain text, or, for `prod`, a value is a known dev default or equals its local value.

## Feeding back to the foundation

A project is where we learn what a business module needs from the foundation. That learning goes back upstream on purpose, never as quiet edits to foundation repos.

- **[`upstream.md`](upstream.md)** lists each item: what's awkward, our workaround here, the change we'd propose and which foundation repo it belongs to, and its status.
- **Every workaround names its item**, in a comment such as `# upstream U3: …`. When the foundation fix arrives in a pinned image, `grep -rn 'upstream U3'` finds everything to remove.
- **Proposing a fix is a separate step.** It happens in `~/projects/t10` as a normal foundation change. A project picks it up only by bumping a pin.

## Checks

Three levels, each needing more than the one before: `make test-template` and `make lint` check the template's own scripts and kit with no stack; `make test` and `make check` check each module and the rendered bundle with no stack; `make smoke` checks a running stack end to end. `make verify` runs the last two from empty volumes, and CI runs all three. What each command covers is in [`guide.md`](guide.md#commands). A module in its own repo also has its own repo's CI.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Put the deployment in the module's repo (`<module>/deploy`) | Ties every environment change to module releases, and a second module would have nowhere to go |
| Fork quickstart or the workspace and edit it | That changes foundation files, and upgrades become merges |
| Read the pack from the image at deploy time | The clients file's changes should be reviewed in a diff, and kustomize needs files at build time |
| Build foundation images from source | Not what was asked, and it breaks "same image everywhere" |
| A generator (copier, cookiecutter) or submodule for the template | Another tool to install and learn; a git remote and a clear ownership rule do the same |
| Copy what every module shares into each module (as before v0.1.0) | A template update can't reach the copies, so a foundation change means the same hand edit in every module |
| A YAML or JSON module manifest in place of `module.env` | Lists in `KEY=value` say all a module needs (capabilities, agents, services); a manifest would need a parser the scripts don't have and a second format beside the settings files |
| Plugins in Python that a project registers with the scripts | Code a template update can't see and a project would have to keep working across releases; files and hooks with a fixed interface keep the boundary where `make template-update` can respect it |
| Publish the Go kit as a Go module in its own repo | A second repo and release cycle to keep in step with the template; the template is private, so every build would need credentials. It moves to the foundation once U16 is done |
| Remote kustomize bases, or a Helm chart for the platform | See `plan.md` |

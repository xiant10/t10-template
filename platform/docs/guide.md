# Working in a project

The reference for a project made from this template: who owns what, where everything lives, the commands, and how settings, secrets and Compose files are put together. Starting a project is [`new-project.md`](new-project.md); building a module is [`module.md`](module.md); why it's built this way is [`design.md`](design.md). This is the one place the layout is described; the other docs link here.

## Who owns what

One rule: **the root and `platform/` belong to the template; `README.md`, `modules/`, `site/` and `.github/workflows/ci.yml` belong to the project; `generated/` is never committed.**

A project changes only its own paths (`lib.OWNED` in `platform/scripts/lib.py`, which `make template-update` and `make check` both read). Everything else comes from the template and is changed there, so every project gets the change and `make template-update` merges cleanly. A project that needs a different value overrides it from `site/`; it never edits a template file. What it adds goes in `site/` too: clients, catalogs, agent routes and list entries ([What a part adds](#what-a-part-adds)), steps around its commands ([Hooks](#hooks)), and commands of its own ([below](#a-projects-own-commands)). `make check` warns about any template file a project edited.

What a module shares with every other module (how it plugs into the foundation, and the Go code every module's service needs) is the template's too: `platform/scripts/wiring.py` and `platform/kit/go/`. A module's own folders hold only what's particular to it, so a fix to what they share reaches every module with a template update.

## Layout

```text
<project>/
├── README.md                    the project: what it is, how to reach it                     project
├── LICENSE                      Apache 2.0, for the template's files                         template
├── Makefile                     the commands (`make help`)                                    template
├── .gitignore                   what's never committed; a project's own rules go in site/.gitignore   template
├── .github/workflows/
│   ├── t10-template.yml         the checks: lint, the template's tests, `make verify`         template
│   └── ci.yml                   the project's CI, which calls them, plus its own jobs          project
├── platform/                    the template engine, foundation and SDK                      template
│   ├── CHANGELOG.md             the template's releases, and what a project does for each
│   ├── scripts/                 what the commands run; lib.py finds the parts
│   │   ├── wiring.py            the standard wiring every module gets, from its module.env
│   │   ├── hook.py              runs each part's hooks/<event>
│   │   └── scaffold/<lang>/     what `make new-module` writes into modules/<id>/src/: go
│   ├── kit/go/                  the Go kit every module's service imports: auth, MCP, routes
│   ├── tests/                   the template's own tests (`make test-template`)
│   ├── docs/                    how the template works
│   └── foundation/              the foundation's images and defaults
│       ├── versions.env         the foundation's images (latest, for local) and third-party pins
│       ├── compose/             base.yml: every core service; local.yml: published ports;
│       │                        server.yml: Caddy and LiveKit on a server; scripted.yml: SCRIPTED=1
│       ├── config/              <service>.env for every environment, local/ and server/ for some, <service>/ for files;
│       │                        server/versions.env pins every foundation image by digest for servers
│       ├── components/<name>/   optional pieces a project picks in FOUNDATION: assistant, livekit, console, automations;
│       │                        each a part, with part.env for what it REQUIRES and adds to the lists
│       ├── scripted/            the scripted model SCRIPTED=1 runs
│       └── …                    public.json (Caddy's sites), clients.json, agent-routes.json, permissions/,
│                                secrets.json, init-db.sh, module-init-db.sh (each module's database)
├── modules/<id>/                one business module: its deployment and its code             project
│   ├── source.env               where its code is: SRC=src, and REPO for a repo of its own
│   ├── versions.env             its image on servers, T10_<ID>
│   ├── config/                  <service>.env, and a folder per layer: local/ (its port), server/ (its address)
│   ├── src/                     its code, tests, Dockerfile and pack (src/module/);
│   │                            for a module in its own repo: a checkout from `make clone`, not committed
│   ├── compose/                 optional: changes to its standard wiring, per layer
│   ├── secrets.json             optional: secrets beyond its standard ones (may also live in its pack)
│   ├── init-db.sh               optional: more database setup (may also live in its pack)
│   ├── hooks/                   optional: hooks/<event>.sh or .py (may also live in its pack)
│   ├── module.mk                optional: its own make targets
│   └── pack/                    own repo only: its pack, copied from its image by `make sync-module`
├── site/                        this project's choices, applied last                         project
│   ├── config/                  settings.env (PROJECT_NAME, FOUNDATION), <env>/settings.env, any <service>.env
│   ├── secrets/                 the secret values: local.env, and each server's <env>.enc.env, encrypted
│   ├── versions.env             optional: a pin this project needs to differ from the template's
│   ├── clients.json, agent-routes.json, permissions/, part.env
│   │                            optional: what it adds to the foundation (#what-a-part-adds)
│   ├── hooks/                   optional: steps around its commands (#hooks)
│   ├── project.mk               optional: its own make targets
│   └── docs/                    the project's own plan and open questions
└── generated/<env>/             the bundle that runs, rewritten on every command                not committed
```

### Parts and layers

`foundation/`, each component that's on, each `modules/<id>/` and `site/` are **parts**, layered in that order, later ones winning. Each part can hold the same things: `versions.env`, `secrets.json`, `config/`, `compose/`, what it adds to the foundation ([below](#what-a-part-adds)) and `hooks/`. A module's standard wiring, secrets and additions come just before its own folder's, so its folder, and `site/` after it, can change anything in them.

Inside each part, `config/` and `compose/` are layered by **environment** (below): every environment's files, then each of its layers in turn.

### What a part adds

Some of the foundation's inputs are one file or list that many parts add to. Any part adds to them the same way, in part order:

| File in a part | Adds | Into |
| --- | --- | --- |
| `clients.json` | OAuth `clients` and `runtimes`, in the form of a pack's `clients.fragment.json`; `runtime_grants` gives actions and audiences to runtimes defined elsewhere | auth-server's `clients.yaml` |
| `agent-routes.json` | `pools`, `agents`, and `default_agent` for the picker | the route document published to t10-agent-control |
| `permissions/*.yaml` | Permission catalogs | auth-server's catalogs |
| `public.json` | `{"<SETTING>": "<service>:<port>"}`: a public address and the service behind it | Caddy's sites, on a server |
| `part.env` | `WORKBENCH_URLS`, `APP_URLS`, `GRANT_ACTIONS`, `GRANT_AUDIENCES`, `TOOL_SERVERS`, `TOOL_MODULE_SERVERS`, comma lists; and for a component, `REQUIRES` | the foundation's lists, through `modules.env` |

A client or runtime that's already defined is refused, so a typo can't replace one. To change one, give its `id` (or a runtime's `name`) with `"_merge": true`: a list gains the values it lacks, and anything else is replaced. So a project adds a redirect URI for its own domain with this in `site/clients.json`:

```json
{"clients": [{"id": "t10-workbench", "_merge": true, "redirect_uris": ["https://work.example.com/auth/callback"]}]}
```

`foundation/clients.json` and `foundation/agent-routes.json` are where the others start. A module's additions are worked out from its pack ([`module.md`](module.md#what-the-template-gives-every-module)) and come just before its own folder's.

### Foundation components

`foundation/` is a core every project runs, plus components in `foundation/components/`: `assistant` (agent-pi), `livekit` (LiveKit and the voice worker, which needs `assistant`), `console` and `automations`. `FOUNDATION` in `site/config/settings.env` lists the ones that run, such as `FOUNDATION=assistant,livekit`; empty runs the core alone. A component left out takes its services, settings, secrets, addresses, clients and routes with it. What each holds is in [`foundation/components/README.md`](../foundation/components/README.md).

## Environments

An environment is a name the commands take as `ENV=`. The template ships three:

| Environment | Where | What it adds |
| --- | --- | --- |
| `local` (default) | This machine | Every service on `127.0.0.1` (ports in `config/local/settings.env`), auth-server's dev mode, LiveKit in dev mode, `DEV=1` and `SCRIPTED=1`, `make seed-demo` |
| `dev` | A shared server, reached with `make deploy ENV=dev` | Caddy in front with TLS, nothing else published; auth as in prod, since auth-server allows dev mode only on localhost |
| `prod` | A server, reached with `make deploy ENV=prod` | As `dev`, with prod's stricter secret checks |
| `k8s-local` | This machine's Kubernetes, such as Docker Desktop's | `local` on Kubernetes instead of Compose, in a namespace of its own on ports 36xxx and 35xxx, so it runs beside `local`: [below](#kubernetes-on-this-machine) |

`dev` and `prod` build on a shared `server` layer (`config/server/`, `compose/server.yml`): Caddy, LiveKit for real, `AUTH_TRUST_PROXY`, and the `TODO`s every server must fill in. Another environment, such as `uat`, needs only `site/config/uat/settings.env` with `SHAPE=prod` (or `dev`) and its own values; it gets that shape's layers, then its own (`config/uat/`, `compose/uat.yml`) in any part. `LAYERS` there picks other layers instead, such as `LAYERS=server,staging` for settings several environments share in `config/staging/`; it must keep `server` (or `local`, for a local shape), and the environment's own layer comes last as always. Each environment is its own Compose project, `<PROJECT_NAME>-<env>`, so two can share a host. `TARGET` says what runs it: `compose`, or `k8s` for an environment on this machine's cluster, such as `k8s-local` (a server cluster is [`plan.md`](plan.md) E5).

## Commands

`make help` lists them all. `ENV=` picks the environment (default `local`).

| Command | Does |
| --- | --- |
| `make doctor` | Whether this machine can run the project: Docker, Compose 2.24+, Python, free ports, and for `k8s-local`, kubectl reaching its cluster |
| `make up` / `down` / `down-all` | Start (building each module from `modules/<id>/src/`), stop, or stop and delete data |
| `make seed-demo` | The foundation's sample accounts, then each part's `hooks/seed-demo` (local only) |
| `make smoke` | Checks the running stack: every service, sign-in, each module's contract and app, every agent route and a turn with each module agent, then each part's `hooks/smoke` |
| `make check` | Checks that need no running stack: packs match their images, secrets are complete, grants reached every place, Compose renders, the bundle mounts nothing from outside itself, and on a server, no `TODO` is left and each module from `modules/<id>/src/` is released as committed |
| `make test` | Each module's own tests from `modules/<id>/src/`, in Docker beside a throwaway Postgres, `TEST_DATABASE_URL` (`MODULE=<id>` for one) |
| `make contract MODULE=<id>` | One module alone, with its own Postgres and no foundation: its pack and the contract its service must keep ([`integration.md`](integration.md)); `make alone` keeps it running |
| `make reload MODULE=<id>` | After changing a module in `modules/<id>/src/`: rebuild and restart it, and what reads its pack if that changed |
| `make verify` | Every gate from empty volumes: `test`, each module's `contract`, then `down-all`, `up`, `seed-demo`, `check`, `smoke`. Run it before calling a change done |
| `make new-module ID=<id>` | A new module: its deployment in `modules/<id>/` and its code in `modules/<id>/src/` ([`module.md`](module.md)); `SCAFFOLD=` picks the language of its code, `go` by default |
| `make release MODULE=<id>` | Build a module from `modules/<id>/src/`, push it to `IMAGE_REGISTRY` and pin it, for servers |
| `make config-show SVC=<service>` | A service's settings, and which file each came from |
| `make deploy ENV=<env>` | Copy the environment's bundle to its host over SSH and start it there, after `make check` |
| `make secrets-key`, `secrets-init`, `secrets-set`, `secrets-edit`, `rotate` | An environment's secrets: [below](#secrets) |
| `make template-update` | Merge the template's latest release (`REF=` for another), keeping the project's paths, and print its changelog; `NO_COMMIT=1` leaves the merge staged |
| `make pin ENV=prod` (`WRITE=1`) | What each foundation image's `latest` is, and optionally pin a server's images to it, in the `versions.env` that wins for each; lines that follow `latest` are left alone |
| `make sync-module MODULE=<id>` | For a module in its own repo: copy its pack out of its pinned image into `modules/<id>/pack/` |
| `make clone` / `make status` | Clone each module that has its own repo into `modules/<id>/src/`; show this repo's and their changes |
| `make routes-publish` | Publish the route document again after an agent changes (`make up` does it) |
| `make lint` / `make test-template` | The template's own checks: ruff and shellcheck, and `tests/` and `kit/go/`'s tests |

Two switches, both local only:

- **`SCRIPTED=1`** uses a scripted model, so nothing needs `LLM_API_KEY`. `make` turns it on by itself while `site/secrets/local.env` has no `LLM_API_KEY`, and says so on `make up`; `SCRIPTED=` (empty) turns it off.
- **`DEV=1`** builds each module that has its own repo from its checkout in `modules/<id>/src/`, instead of pulling its image. A module whose code is in the project is always built from there on local.

On a server, `make smoke` checks only what Caddy publishes.

## Hooks

A part's `hooks/<event>.sh` or `hooks/<event>.py` runs at that point in a command, in part order: the foundation's, its components', each module's, then `site/`'s. So a project's step, such as a data import after `make up` or a notice after a deploy, goes in `site/hooks/`, never in a template script.

| Event | Runs | A failure |
| --- | --- | --- |
| `post-up` | After `make up`, once the stack is healthy and its routes are published | Fails `make up` |
| `seed-demo` | In `make seed-demo`, after the foundation's sample accounts (local only) | Fails it |
| `smoke` | At the end of `make smoke`'s own checks, on local | Is a failed check |
| `check` | At the end of `make check`'s own checks | Is a failed check |
| `pre-deploy`, `post-deploy` | Here, in `make deploy`: after `make check` and before the copy; once the host is up | Stops the deploy |

Each runs from the project's root with `ENV`, `T10_PART` (its part, such as `site` or `modules/crm`), `T10_MODULE` (a module's ID, else empty) and `T10_COMPOSE` (`platform/scripts/compose.sh`, to `exec` into a container). A `.sh` hook runs with `sh`, a `.py` one with `python3 -I -B`. A `smoke.py` or `check.py` hook instead runs inside `make smoke` or `make check`, with their helpers: `check(name, ok, detail)`, and for `smoke`, `http`, `compose`, `agent`, `open_session`, `turn`, `tool_calls`, `token`, `cfg`, `SCRIPTED`, and for a module's, `module` (its `module.env`) and `url`; for `check`, `ENV`, `bundle` and `run`. `seed-demo` hooks also get `AUTH_URL` and `T10_PG_USER`.

## A project's own commands

The Makefile includes `site/project.mk` and each `modules/<id>/module.mk` if they exist. Both are the project's, so a project's own targets live there rather than in the template's Makefile, and `make help` lists any with a `## ` comment:

```make
import-contacts: ## Load a contacts export into the crm module
	@platform/scripts/compose.sh exec -T t10-crm /usr/local/bin/t10-crm import /data/contacts.csv
```

## Changing a setting

Every service reads one file, `generated/<env>/env/<service>.env`, merged from every part's `config/<service>.env`, then every part's `config/<layer>/<service>.env` for each of the environment's layers (such as `server`, then `prod`), parts in order. So:

| For | File |
| --- | --- |
| A template default | `platform/foundation/config/` (in the template) |
| A module's own service | `modules/<id>/config/<service>.env` |
| This project, one service, every environment | `site/config/<service>.env` |
| This project, one service, one environment | `site/config/<env>/<service>.env` |
| Ports, public addresses, deploy host, `PROJECT_NAME` | `settings.env` in the same places: values Compose interpolates and scripts read |
| A different image than the template pins | `site/config/server/versions.env` (servers), `site/config/<env>/versions.env` (one environment) or `site/config/local/versions.env` (this machine), as a deliberate exception. `site/versions.env` comes before every layer, so it can't change a foundation image on a server |

Then `make up`, which recreates only the containers whose settings changed. `make config-show SVC=<service>` shows where each value came from.

Never edit a Compose file for a setting: they hold only wiring. Never put a secret among settings: `make check` refuses it.

## Secrets

### Which exist, and who gets each

The inventory is each part's `secrets.json`, plus each module's standard secrets, made from its `module.env` (`scripts/wiring.py`). An entry never holds a value. It says:

| Field | Means |
| --- | --- |
| `name` | The secret, such as `WORKBENCH_SESSION_KEY` |
| `generate` | How a new value is made: `hex32`, `b64key`, `es256` (a signing key from auth-server's `authctl gen-key`), or `provided` (pasted in) |
| `env` | Which services get it, under which variable: `{"workbench": {"AUTH_CLIENT_SECRET": "${WORKBENCH_CLIENT_SECRET}"}}`. A value can build on it, such as `postgres://t10:${POSTGRES_PASSWORD}@postgres:5432/auth`, and `${NAME:-default}` gives a fallback |
| `rotate`, `rotation` | How to rotate it, and what `make rotate APPLY=1` does: `replace`, `account:<name>`, `signing-key`, or nothing when it's done by hand |
| `envs`, `optional`, `consumers` | Which environments need it, whether it may be empty, and who uses it, for people |

Entries with the same name are merged, later parts winning, with `env` merged service by service. An entry with no `generate` is a *use*: it gives one more service a secret declared elsewhere. So a module or the project adds a secret, or gives an existing one to one of its services, in its own `secrets.json`, never in a Compose file. `make check` fails on a secret written into a template Compose file, and warns about one in a project's.

`scripts/render.py` writes each service's secrets into the bundle as `secrets/<service>.env` (mode 600), which the service reads after its settings. A service sees only its own.

### Where the values are

| File | Holds | In git |
| --- | --- | --- |
| `site/secrets/local.env` | This checkout's values, made by every local command, plus `LLM_API_KEY` by hand | No |
| `site/secrets/.sops.yaml` | Which age keys can decrypt the server environments' secrets: public keys only | Yes |
| `site/secrets/<env>.enc.env` | A server environment's values, encrypted with SOPS and age. The names stay readable, so a diff shows a secret added or removed | Yes |
| `site/secrets/<env>.env` | A server environment's values in plain text, only before the project has `.sops.yaml`; `make check` fails while it's there | No |

A server environment's values are decrypted in memory when a command needs them, never to a file here. Its bundle holds them only while `scripts/compose.sh` runs Compose on it, and while `make deploy` copies it to the host, which keeps them in its own copy of the bundle.

### Working with them

| Command | Does |
| --- | --- |
| `make secrets-key` | Once per machine: makes its age key (`~/.config/sops/age/keys.txt`, or `SOPS_AGE_KEY_FILE`) and adds its public key to `site/secrets/.sops.yaml`. Back the key up: without it, or the break-glass key, the encrypted values are lost |
| `make secrets-key BREAKGLASS=1` | Prints a new key once, to keep offline, and adds it as a recipient |
| `make secrets-key RECIPIENT=age1…` | Lets a teammate's key decrypt every environment. To remove one, delete it from `.sops.yaml` and run `make secrets-key` |
| `make secrets-init ENV=<env>` | Adds any missing generated values, encrypted; encrypts a plain `<env>.env` if there is one |
| `make secrets-set ENV=<env> NAME=…` | Sets one value, typed in and not shown, such as `LLM_API_KEY` |
| `make secrets-edit ENV=<env>` | Opens every value in an editor, and encrypts them again on save |
| `make rotate NAME=…` | Prints how to rotate one |
| `make rotate NAME=… ENV=<env> APPLY=1` | Rotates it there, as its `rotation` says; a two-phase one then needs `FINISH=1` after the deploy |

`sops` and `age` run from this machine if installed, or else from a small image (`scripts/tools/`), so nothing needs installing. Rotation, by kind:

| `rotation` | `APPLY=1` | Then |
| --- | --- | --- |
| `replace` | A new value | `make up` or `make deploy`, which recreates what reads it (auth-server too, for a web client's secret) |
| `account:<name>` | `authctl service-rotate`: auth-server accepts the old secret and the new one, which is saved | Deploy, check it works, then `FINISH=1` runs `authctl service-finish` to retire the old one |
| `signing-key` | A new key in `AUTH_SIGNING_KEY_NEXT`, which auth-server publishes | Deploy, wait one token lifetime, then `FINISH=1` makes it current and clears `NEXT`; deploy again |
| none | Nothing: the steps are printed | By hand, such as a provider's key or the Postgres password |

## Compose files and the bundle

Compose never runs from the checkout. Every command first renders `generated/<env>/` (`scripts/render.py`), a bundle with the repo's layout, so it runs the same here or on the host `make deploy` copies it to:

- each part's `compose/`, `config/`, `scripted/`, `pack/` and `init-db.sh`, copied, and each module's pack (from `modules/<id>/src/module/` for a module in the project);
- each module's standard wiring, `modules/<id>/standard/<name>.yml` for `base`, `local` and `build`, written from its `module.env`;
- `env/<service>.env`, each service's merged settings; `secrets/<service>.env`, its secrets, and `secrets.yml`, which has each service read them; `versions.env`, every part's merged, then each layer's;
- what's merged from the packs: `clients.yaml`, `permissions/`, `agent-routes.json`, `modules.env`, and each agent's grant;
- on a server, the `Caddyfile`: one site per public address;
- `compose.sh`, which runs Compose on all of it, as project `<PROJECT_NAME>-<env>`.

Compose files are read name by name (`base`, then each layer), part by part, with each module's standard file just before its own. `build.yml` is added for `DEV=1` and `scripted.yml` for `SCRIPTED=1`, from whichever parts have one. Edit the parts, never the bundle: it's rewritten on every command.

## Running a server

A server environment (`dev`, `prod`, or one built on them) runs on its host, `DEPLOY_HOST`, from the bundle `make deploy` copies to `DEPLOY_DIR`. `DEPLOY_SSH` holds any options ssh needs, such as `-p 2222 -i ~/.ssh/deploy`. The host needs Docker with Compose 2.24 or later, rsync, and a login to any private registry.

| Command | Does |
| --- | --- |
| `make check ENV=<env>` | Everything that can be checked here first: no `TODO`, every image pinned by digest and each module released as committed, secrets complete and encrypted, and every service with rotated logs and a memory limit |
| `make deploy ENV=<env>` | `make check`, then copies the bundle with its secrets, starts it, and reloads Caddy |
| `make smoke ENV=<env>` | Its public addresses, through Caddy |
| `make ps`, `logs`, `down` with `ENV=<env>` | Run on the host, over SSH, on its bundle; `make up` there is `make deploy` |
| `make down-all ENV=<env>` | Deletes its data: needs `CONFIRM=<env>` |
| `make backup ENV=<env>` | Dumps every database now. The `backup` service also does it every `BACKUP_EVERY` seconds, keeping `BACKUP_KEEP_DAYS` days, on the host |
| `make backup-pull ENV=<env>` | Copies the newest dump here, to `backups/<env>/` (never committed), after checking it's complete, encrypted for the keys in `site/secrets/.sops.yaml` |
| `make restore ENV=<env> FILE=… CONFIRM=<env>` | Stops everything but Postgres, replaces every database with the dump, and starts it again (on a server, with `make deploy`) |

Every service on a server rotates its logs (`LOG_MAX_SIZE`, `LOG_MAX_FILES`) and has a memory limit (`MEM_LIMIT`, or `MEM_LIMIT_LARGE` for Postgres and the agents), set in `platform/foundation/config/server/settings.env`; override them in `site/config/<env>/settings.env`, or for one service in `site/compose/server.yml`. The model gateway's audit and the backups are volumes, so they outlive their containers.

A backup is only as useful as the secrets it was taken with: `MODEL_KEY` and any module's data key decrypt what's in it, and they're in git, in `site/secrets/<env>.enc.env`. Pull backups off the host regularly; a host's own copies go with the host.

## Kubernetes on this machine

`k8s-local` runs what `local` runs on this machine's Kubernetes, such as Docker Desktop's (turn it on in Docker Desktop's settings). It's built on `local` (`SHAPE=local`) with `TARGET=k8s`, so the same commands work with `ENV=k8s-local`:

```sh
make doctor ENV=k8s-local           # also: kubectl reaches KUBE_CONTEXT
make up ENV=k8s-local               # modules in src/ built first; waits until everything is ready
make seed-demo ENV=k8s-local
make smoke ENV=k8s-local            # the same checks as on local
make verify ENV=k8s-local           # every gate, from empty volumes
```

Nothing is written twice for it. `scripts/render.py` writes the Compose bundle as for `local`, then `scripts/kube.py` turns `docker compose config` on that bundle into Kubernetes objects, in `generated/k8s-local/kustomization.yaml` and `k8s/`, so what runs on the cluster is what Compose and `make smoke` test:

| On Compose | On Kubernetes |
| --- | --- |
| A service | A Deployment with one replica, replaced rather than rolled. A one-off service that another waits on to finish (`seed`, `<id>-db`, `t10-agents`, …) is a Job, run again on every `make up` |
| Its name on Compose's network | A headless Service of the same name, so every address in the settings works as it is |
| A published port | A LoadBalancer Service, `<service>-public`, on the same port; Docker Desktop publishes it on localhost |
| A named volume | A PersistentVolumeClaim. `make down` keeps them; `make down-all` deletes the namespace, and with it the data |
| A file or folder from the bundle | A ConfigMap named by its content's hash, so a change restarts what mounts it |
| Its secrets | A Secret per service, `<service>-secrets`, made in memory by `make up`: never written to `generated/` |
| `healthcheck`, `depends_on` | Its readiness probe, and the order: `make up` applies the services in waves, each once those it waits on are ready or done |

It runs in the namespace `<PROJECT_NAME>-k8s-local` on the `docker-desktop` context; set `KUBE_NAMESPACE` or `KUBE_CONTEXT` in `site/config/k8s-local/settings.env` to change them. Nothing outside its namespace is touched, so it runs beside a workspace's own cluster deployment. `make ps`, `logs`, `exec`-based hooks, `reload MODULE=<id>` and `routes-publish` work as on `local`; `make check ENV=k8s-local` also builds the objects with kustomize and checks no secret is in them.

A module gets its own port for it, `PORT` + 18000, in `modules/<id>/config/k8s-local/settings.env`. A change only for Kubernetes goes in a part's `k8s/<layer>/` as a kustomize component (`k8s/base/`, `k8s/local/` or `k8s/k8s-local/`), which `kustomization.yaml` takes in layer order; `site/k8s/k8s-local/` is a project's own.

## Keeping up with the template

```sh
make template-update      # the latest release; README.md, modules/, site/ and ci.yml stay as they are
make verify
```

It prints what `CHANGELOG.md` says about each release it brought in; do what its **In a project** notes say. The whole practice (the two remotes, overriding instead of editing, conflicts, and releasing a template change) is [`template-updates.md`](template-updates.md).

## CI

`.github/workflows/ci.yml` runs on every push to `main` and every pull request. It's the project's, and calls the template's checks, `.github/workflows/t10-template.yml`, a reusable workflow: `make lint` and `make test-template`, then `make verify` with the scripted model. In the template, which has no module, it scaffolds one first. A project adds its own jobs, such as a release or a deploy, in `ci.yml` with `needs: checks`, and gets the checks' fixes with each template update.

## Feeding back to the foundation

What a project learns about the foundation goes back on purpose, as an item in [`upstream.md`](upstream.md), never as an edit to a foundation repo. Every workaround names its item in a comment, such as `# upstream U3: …`, so `grep -rn 'upstream U3'` finds what to remove once the fix is in a pinned image.

# Working in a project

The reference for a project made from this template: who owns what, where everything lives, the commands, and how settings, secrets and Compose files are put together. Starting a project is [`new-project.md`](new-project.md); building a module is [`module.md`](module.md); why it's built this way is [`design.md`](design.md). This is the one place the layout is described; the other docs link here.

## Who owns what

One rule: **the root and `foundation/` belong to the template; `README.md`, `modules/`, `site/` and `src/` belong to the project; `generated/` is never committed.**

A project changes only its own paths. Everything else comes from the template and is changed there, so every project gets the change and `make template-update` merges cleanly. A project that needs a different value overrides it from `site/`; it never edits a template file. `make check` warns about any template file a project edited.

What a module shares with every other module (how it plugs into the foundation, and the Go code every module's service needs) is the template's too: `scripts/wiring.py` and `kit/go/`. A module's own folders hold only what's particular to it, so a fix to what they share reaches every module with a template update.

## Layout

```text
<project>/
├── README.md              the project: what it is, how to reach it                     project
├── CHANGELOG.md           the template's releases, and what a project does for each     template
├── LICENSE                Apache 2.0, for the template's files                         template
├── Makefile               the commands (`make help`)                                    template
├── scripts/               what the commands run; lib.py finds the parts                template
│   ├── wiring.py          the standard wiring every module gets, from its module.env
│   └── scaffold/src/      what `make new-module` writes into src/<id>/
├── kit/go/                the Go kit every module's service imports: auth, MCP, routes   template
├── tests/                 the template's own tests (`make test-template`)               template
├── docs/                  how the template works                                        template
├── .github/workflows/     CI: lint, the template's tests, `make verify`                 template
├── foundation/            the foundation's images and defaults                          template
│   ├── versions.env       the foundation and third-party pins, tested together
│   ├── compose/           base.yml: every core service; local.yml: published ports;
│   │                      server.yml: Caddy and LiveKit on a server; scripted.yml: SCRIPTED=1
│   ├── config/            <service>.env for every environment, local/ and server/ for some, <service>/ for files
│   ├── components/<name>/ optional pieces a project picks in FOUNDATION: assistant, livekit, console, automations
│   ├── scripted/          the scripted model SCRIPTED=1 runs
│   └── …                  public.json (Caddy's sites), clients.json, agent-routes.json, permissions/,
│                          secrets.json, init-db.sh, module-init-db.sh (each module's database)
├── modules/<id>/          one module's deployment: only what's particular to it         project
│   ├── source.env         where its code is: SRC, and REPO for a repo of its own
│   ├── versions.env       its image on servers, T10_<ID>
│   ├── config/            <service>.env, and a folder per layer: local/ (its port), server/ (its address)
│   ├── compose/           optional: changes to its standard wiring, per layer; scripted.yml for SCRIPTED=1
│   ├── secrets.json       optional: secrets beyond its standard ones
│   ├── init-db.sh         optional: more database setup, after its database and login are made
│   ├── hooks/             optional: seed-demo.sh and smoke.py, run by `make seed-demo` and `make smoke`
│   └── pack/              own repo only: its pack, copied from its image by `make sync-module`
├── src/<id>/              a module's code: its service, tests, Dockerfile and pack (module/)   project
│                          (a module in its own repo: a checkout from `make clone`, not committed)
├── site/                  this project's choices, applied last                         project
│   ├── config/            settings.env (PROJECT_NAME, FOUNDATION), <env>/settings.env, any <service>.env
│   ├── secrets/           the secret values, per environment, and the only place they're read from
│   ├── versions.env       optional: a pin this project needs to differ from the template's
│   └── docs/              the project's own plan and open questions
└── generated/<env>/       the bundle that runs, rewritten on every command                not committed
```

### Parts and layers

`foundation/`, each component that's on, each `modules/<id>/` and `site/` are **parts**, layered in that order, later ones winning. Each part can hold the same things: `versions.env`, `secrets.json`, `config/` and `compose/`. A module's standard wiring and standard secrets come just before its own folder's, so its folder can change anything in them.

Inside each part, `config/` and `compose/` are layered by **environment** (below): every environment's files, then each of its layers in turn.

### Foundation components

`foundation/` is a core every project runs, plus components in `foundation/components/`: `assistant` (agent-pi), `livekit` (LiveKit and the voice worker, which needs `assistant`), `console` and `automations`. `FOUNDATION` in `site/config/settings.env` lists the ones that run, such as `FOUNDATION=assistant,livekit`; empty runs the core alone. A component left out takes its services, settings, secrets, addresses, clients and routes with it. What each holds is in [`foundation/components/README.md`](../foundation/components/README.md).

## Environments

An environment is a name the commands take as `ENV=`. The template ships three:

| Environment | Where | What it adds |
| --- | --- | --- |
| `local` (default) | This machine | Every service on `127.0.0.1` (ports in `config/local/settings.env`), auth-server's dev mode, LiveKit in dev mode, `DEV=1` and `SCRIPTED=1`, `make seed-demo` |
| `dev` | A shared server, reached with `make deploy ENV=dev` | Caddy in front with TLS, nothing else published; auth as in prod, since auth-server allows dev mode only on localhost |
| `prod` | A server, reached with `make deploy ENV=prod` | As `dev`, with prod's stricter secret checks |

`dev` and `prod` build on a shared `server` layer (`config/server/`, `compose/server.yml`): Caddy, LiveKit for real, `AUTH_TRUST_PROXY`, and the `TODO`s every server must fill in. Another environment, such as `uat`, needs only `site/config/uat/settings.env` with `SHAPE=prod` (or `dev`) and its own values; it gets that shape's layers, then its own (`config/uat/`, `compose/uat.yml`) in any part. Each environment is its own Compose project, `<PROJECT_NAME>-<env>`, so two can share a host. `TARGET` says what runs it: `compose` today, `k8s` once it's built ([`plan.md`](plan.md)).

## Commands

`make help` lists them all. `ENV=` picks the environment (default `local`).

| Command | Does |
| --- | --- |
| `make doctor` | Whether this machine can run the project: Docker, Compose 2.24+, Python, free ports |
| `make up` / `down` / `down-all` | Start (building each module from `src/`), stop, or stop and delete data |
| `make seed-demo` | The foundation's sample accounts, then each module's `hooks/seed-demo.sh` (local only) |
| `make smoke` | Checks the running stack: every service, sign-in, each module's contract and app, every agent route and a turn with each module's agent, then each module's `hooks/smoke.py` |
| `make check` | Checks that need no running stack: packs match their images, secrets are complete, grants reached every place, Compose renders, the bundle mounts nothing from outside itself, and on a server, no `TODO` is left and each module from `src/` is released as committed |
| `make test` | Each module's own tests from `src/`, in Docker (`MODULE=<id>` for one) |
| `make reload MODULE=<id>` | After changing a module in `src/`: rebuild and restart it, and what reads its pack if that changed |
| `make verify` | Everything from empty volumes: `test`, `down-all`, `up`, `seed-demo`, `check`, `smoke`. Run it before calling a change done |
| `make new-module ID=<id>` | A new module: its code in `src/<id>/` and its deployment in `modules/<id>/` ([`module.md`](module.md)) |
| `make release MODULE=<id>` | Build a module from `src/`, push it to `IMAGE_REGISTRY` and pin it, for servers |
| `make config-show SVC=<service>` | A service's settings, and which file each came from |
| `make deploy ENV=<env>` | Copy the environment's bundle to its host over SSH and start it there, after `make check` |
| `make secrets-init` | Add missing secrets to `site/secrets/<env>.env`, keeping existing ones (`ENV=` for a server) |
| `make rotate NAME=…` | How to rotate one secret |
| `make template-update` | Merge the template's latest release (`REF=` for another), keeping the project's paths, and print its changelog |
| `make pin` (`WRITE=1`) | What each foundation image's `latest` is, and optionally pin it in the `versions.env` that wins for it |
| `make sync-module MODULE=<id>` | For a module in its own repo: copy its pack out of its pinned image into `modules/<id>/pack/` |
| `make clone` / `make status` | Clone each module that has its own repo into `src/`; show this repo's and their changes |
| `make routes-publish` | Publish the route document again after an agent changes (`make up` does it) |
| `make lint` / `make test-template` | The template's own checks: ruff and shellcheck, and `tests/` and `kit/go/`'s tests |

Two switches, both local only:

- **`SCRIPTED=1`** uses a scripted model, so nothing needs `LLM_API_KEY`. `make` turns it on by itself while `site/secrets/local.env` has no `LLM_API_KEY`, and says so on `make up`; `SCRIPTED=` (empty) turns it off.
- **`DEV=1`** builds each module that has its own repo from its checkout in `src/`, instead of pulling its image. A module whose code is in the project is always built from `src/` on local.

On a server, `make smoke` checks only what Caddy publishes.

## Changing a setting

Every service reads one file, `generated/<env>/env/<service>.env`, merged from every part's `config/<service>.env`, then every part's `config/<layer>/<service>.env` for each of the environment's layers (such as `server`, then `prod`), parts in order. So:

| For | File |
| --- | --- |
| A template default | `foundation/config/` (in the template) |
| A module's own service | `modules/<id>/config/<service>.env` |
| This project, one service, every environment | `site/config/<service>.env` |
| This project, one service, one environment | `site/config/<env>/<service>.env` |
| Ports, public addresses, deploy host, `PROJECT_NAME` | `settings.env` in the same places: values Compose interpolates and scripts read |
| A different image than the template pins | `site/versions.env`, as a deliberate exception |

Then `make up`, which recreates only the containers whose settings changed. `make config-show SVC=<service>` shows where each value came from.

Never edit a Compose file for a setting: they hold only wiring. Never put a secret among settings: `make check` refuses it.

## Secrets

Which secrets exist is the inventory: each part's `secrets.json` (name, consumers, how to make one, how to rotate it, never a value), plus each module's standard ones, made from its `module.env` (`scripts/wiring.py`). A module's own `secrets.json` adds more or replaces a standard one by name.

The values are the project's, in `site/secrets/`, and nothing reads them from anywhere else:

| File | Holds | In git |
| --- | --- | --- |
| `site/secrets/local.env` | This checkout's values, made by every local command, plus `LLM_API_KEY` by hand | No |
| `site/secrets/<env>.env` | A server environment's values in plain text, from `make secrets-init ENV=<env>`, then filled in. Until SOPS is built ([`plan.md`](plan.md), C2); then only while a command runs | No |
| `site/secrets/<env>.enc.env` | The same, encrypted with SOPS and age (planned) | Yes |

Every command copies the environment's values into the bundle as `generated/<env>/secrets.env` (mode 600), which `make deploy` copies to the host.

## Compose files and the bundle

Compose never runs from the checkout. Every command first renders `generated/<env>/` (`scripts/render.py`), a bundle with the repo's layout, so it runs the same here or on the host `make deploy` copies it to:

- each part's `compose/`, `config/`, `scripted/`, `pack/` and `init-db.sh`, copied, and each module's pack (from `src/<id>/module/` for a module in the project);
- each module's standard wiring, `modules/<id>/standard/<name>.yml` for `base`, `local` and `build`, written from its `module.env`;
- `env/<service>.env`, each service's merged settings; `versions.env`, every part's merged; `secrets.env`;
- what's merged from the packs: `clients.yaml`, `permissions/`, `agent-routes.json`, `modules.env`, and each agent's grant;
- on a server, the `Caddyfile`: one site per public address;
- `compose.sh`, which runs Compose on all of it, as project `<PROJECT_NAME>-<env>`.

Compose files are read name by name (`base`, then each layer), part by part, with each module's standard file just before its own. `build.yml` is added for `DEV=1` and `scripted.yml` for `SCRIPTED=1`, from whichever parts have one. Edit the parts, never the bundle: it's rewritten on every command.

## Keeping up with the template

```sh
make template-update      # the latest release; README.md, modules/, site/ and src/ stay as they are
make verify
```

It prints what `CHANGELOG.md` says about each release it brought in; do what its **In a project** notes say. A conflict means the project edited a template file: move that change into `site/`, or propose it to the template. To move to newer foundation images, prefer a template release, since the template's set of pins is tested together; `make pin` shows what's newer.

## CI

`.github/workflows/ci.yml` runs on every push to `main` and every pull request: `make lint` and `make test-template`, then `make verify` with the scripted model. In the template, which has no module, it scaffolds one first. A project gets the workflow with the template, and runs it on its own modules.

## Feeding back to the foundation

What a project learns about the foundation goes back on purpose, as an item in [`upstream.md`](upstream.md), never as an edit to a foundation repo. Every workaround names its item in a comment, such as `# upstream U3: …`, so `grep -rn 'upstream U3'` finds what to remove once the fix is in a pinned image.

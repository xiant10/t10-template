# Working in a project

How to run and change a project made from this template. Why it's built this way is in [`design.md`](design.md).

## Who owns what

One rule: **the root and `foundation/` belong to the template; `modules/` and `site/` belong to the project; `src/` and `generated/` are never committed.** The project's `README.md` is the one project file at the root.

A project is three kinds of part, layered in this order, later ones winning:

| Part | What | Owned by |
| --- | --- | --- |
| `foundation/` | The t10 foundation's images as any project runs them: the pins the template is tested with, defaults, and `TODO` where a project must decide | The template |
| `modules/<id>/` | One business module: its image pin and source repo, Compose files, settings, secrets inventory, and the pack from its image | The project |
| `site/` | This project's own choices: `PROJECT_NAME`, ports, public addresses, the deploy host, overrides of any setting or pin, and its secret values | The project |

Everything a part holds is layered the same way, foundation then modules then site: `versions.env`, `secrets.json`, `config/`, `compose/` and `k8s/`. A project changes only `modules/`, `site/` and its `README.md`. Everything else comes from the template and is changed there, so every project gets the change and template updates merge cleanly. A project that needs a different value overrides it from `site/`; it never edits a template file.

```text
<project>/
├── README.md            the project: what it is, how to reach it                  project
├── LICENSE              Apache 2.0, for the template's files                       template
├── Makefile  scripts/   what the commands run; lib.py finds the parts              template
├── docs/                how the template works: guide, design, module, plan, upstream  template
├── foundation/          the foundation's images, defaults only                    template
│   ├── versions.env     the foundation and third-party pins, tested together
│   ├── components/      optional pieces a project picks in FOUNDATION: assistant, livekit, console, automations
│   ├── compose/         base.yml: every foundation service; local.yml: published ports;
│   │                    server.yml: Caddy and LiveKit on a server; scripted.yml: SCRIPTED=1
│   ├── config/          <service>.env for every environment, local/ and server/ for some, <service>/ for files
│   ├── k8s/             vendor/ (make vendor), base/, and a component per layer: local/, server/ (skeleton)
│   ├── scripted/        the scripted model SCRIPTED=1 runs
│   └── …                public.json (Caddy's sites), clients.json, agent-routes.json, permissions/,
│                        secrets.json, init-db.sh
├── modules/<id>/        one business module                                        project
│   ├── versions.env     its image, T10_<ID>
│   ├── source.env       its repo, which `make clone` fetches into src/
│   ├── compose/         base.yml: its services and the few foundation settings only it needs;
│   │                    local.yml: its published port; build.yml: DEV=1; scripted.yml: SCRIPTED=1
│   ├── config/          <service>.env, settings.env, and a folder per layer: local/, server/, …
│   ├── k8s/             its Kubernetes component (skeleton until Kubernetes is built)
│   ├── pack/            its integration pack, copied from its image by `make sync-module`
│   ├── hooks/           seed-demo.sh and smoke.py, run by `make seed-demo` and `make smoke`
│   └── …                secrets.json, init-db.sh, README.md, docs/
├── site/                this project's choices, applied last                       project
│   ├── config/          settings.env (PROJECT_NAME), <env>/settings.env, any <service>.env
│   ├── secrets/         the secret values, per environment, and the only place they're read from
│   ├── k8s/<env>/       Kubernetes patches for one environment (later)
│   ├── docs/            the project's own plan and open questions
│   └── versions.env     optional: a pin this project needs to differ from the template's
├── src/<repo>/          module source repos, cloned by `make clone`                not committed
└── generated/<env>/     the bundle that runs, rewritten on every run; never an original   not committed
```

### Secrets

Which secrets exist is the inventory, each part's `secrets.json`: name, consumers, how to make one, how to rotate it, never a value. The values are the project's, in `site/secrets/`, one file per environment, and nothing reads them from anywhere else:

| File | Holds | In git |
| --- | --- | --- |
| `site/secrets/local.env` | This checkout's values, from `make secrets-init`, plus `LLM_API_KEY` by hand | No |
| `site/secrets/<env>.env` | A server environment's values in plain text, from `make secrets-init ENV=<env>`, then filled in. Until SOPS is built (`plan.md`, C2); then only while a command runs | No |
| `site/secrets/<env>.enc.env` | The same, encrypted with SOPS and age (planned) | Yes |

Every command copies the environment's values into the bundle as `generated/<env>/secrets.env` (mode 600), which `make deploy` copies to the host. `generated/` is derived only: deleting it loses nothing.

### Foundation components

`foundation/` is a core every project runs, and components in `foundation/components/`: `assistant` (agent-pi), `livekit` (LiveKit and the voice worker, which needs `assistant`), `console` and `automations`. `FOUNDATION` lists the ones that run: the template's list in `foundation/config/settings.env` has all four, and a project sets its own in `site/config/settings.env`, such as `FOUNDATION=assistant,livekit`. A component left out takes its services, settings, secrets, addresses, clients and routes with it. What each holds is in [`foundation/components/README.md`](../foundation/components/README.md).

## Environments

An environment is a name the commands take as `ENV=`. The template ships three, and each part's `config/` and `compose/` can have a layer for each:

| Environment | Where | What it adds |
| --- | --- | --- |
| `local` (default) | This machine | Every service on `127.0.0.1` (ports in `config/local/settings.env`), auth-server's dev mode, LiveKit in dev mode, `DEV=1` and `SCRIPTED=1`, `make seed-demo` |
| `dev` | A shared server, reached with `make deploy ENV=dev` | Caddy in front with TLS, nothing else published; auth as in prod, since auth-server allows dev mode only on localhost |
| `prod` | A server, reached with `make deploy ENV=prod` | As `dev`, with prod's stricter secret checks |

`dev` and `prod` build on a shared `server` layer (`config/server/`, `compose/server.yml`): Caddy, LiveKit for real, `AUTH_TRUST_PROXY`, and the `TODO`s every server must fill in. Another environment, such as `uat`, needs only `site/config/uat/settings.env` with `SHAPE=prod` (or `dev`) and its own values; it gets that environment's layers, then its own (`config/uat/`, `compose/uat.yml`) in any part. Each environment is its own Compose project, `<PROJECT_NAME>-<env>`, so two can share a host.

Each environment says what runs it in `TARGET`: `compose` today, `k8s` once it's built (`plan.md`).

## Commands

`make help` lists them. The main ones:

| Command | Does |
| --- | --- |
| `make up` / `down` / `down-all` | Start, stop, or stop and delete data |
| `make seed-demo` | The foundation's sample accounts, then each module's `hooks/seed-demo.sh` (local only) |
| `make smoke` | Checks the running stack: every service, sign-in, each module's contract and app, every agent route, then each module's `hooks/smoke.py` |
| `make check` | Checks that need no running stack: packs match their images, secrets are complete, grants agree, Compose renders, the bundle mounts nothing from outside itself, and for prod, no `TODO` is left |
| `make config-show SVC=auth-server` | A service's settings, and which layer each came from |
| `make deploy ENV=prod` | Copy the environment's bundle to its host over SSH (rsync, in place), start it there and reload Caddy, after `make check` |
| `make pin` (`WRITE=1`) | What each foundation image's `latest` is, and optionally pin it in the `versions.env` that wins for it |
| `make secrets-init` | Add missing secrets to `site/secrets/<env>.env`, keeping existing ones (`ENV=` for a server) |
| `make new-module ID=<id> SERVICE=… PORT=…` | Write `modules/<id>/` for a new module ([`module.md`](module.md)) |
| `make sync-module MODULE=<id>` | Copy a module's pack out of its pinned image into `modules/<id>/pack/` |
| `make routes-publish` | Publish the route document again after an agent changes |
| `make rotate NAME=…` | How to rotate one secret |
| `make clone` / `make status` | Clone each module's repo (its `source.env`) into `src/`; show this repo's and their changes |

`ENV=` picks the environment (default `local`). `DEV=1` builds modules from `src/` instead of pulling them, and `SCRIPTED=1` uses a scripted model so nothing needs `LLM_API_KEY`. Both are local only. On a server, `make smoke` checks only what Caddy publishes.

## Changing a setting

Every service reads one file, `generated/<env>/env/<service>.env`, merged from every part's `config/<service>.env`, then every part's `config/<layer>/<service>.env` for each of the environment's layers (such as `server`, then `prod`), parts in the order foundation, modules, site. So:

- a template default goes in `foundation/config/`;
- a module's own service's settings go in `modules/<id>/config/`;
- this project's choice, for any service, goes in `site/config/<service>.env` (every environment) or `site/config/<env>/<service>.env` (one).

Values Compose interpolates and scripts read, such as ports, public URLs and `PROJECT_NAME`, go in `settings.env` in the same places. Then run `make up`, which recreates only the containers whose settings changed. `make config-show SVC=<service>` shows where each value came from.

Never edit a Compose file for a setting: they hold only wiring. Never put a secret among settings: `make check` refuses it.

## Compose files and the bundle

Each part's `compose/base.yml` holds what every environment runs. `compose/<layer>.yml` adds what an environment's layers need, such as the published ports in `local.yml` or Caddy in `server.yml`; `build.yml` is added for `DEV=1` and `scripted.yml` for `SCRIPTED=1`, from whichever parts have one.

Compose never runs from the checkout. Every command first renders `generated/<env>/`, a bundle with the repo's layout: each part's `compose/`, `config/`, `scripted/`, `pack/` and `init-db.sh`, the merged `env/`, every part's `versions.env` merged into one, the secrets as `secrets.env` (mode 600), what's merged from the packs, on a server the `Caddyfile`, and a `compose.sh` that runs Compose on it. `scripts/compose.sh` runs that script here, and `make deploy` copies the bundle to a host and runs it there. Edit the parts, never the bundle.

## Adding a module

`make new-module ID=<id> SERVICE=<service> PORT=<port> REPO=<url>` writes `modules/<id>/` with every name taken from the ID. It joins the stack once `make sync-module MODULE=<id>` copies the pack out of its image; then fill in each `TODO`. What the image must ship, what its service must answer and what each file in the folder is for is the contract in [`module.md`](module.md).

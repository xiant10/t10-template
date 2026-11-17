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
│   ├── secrets/           the secret values: local.env, and each server's <env>.enc.env, encrypted
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
| `make secrets-key`, `secrets-init`, `secrets-set`, `secrets-edit`, `rotate` | An environment's secrets: [below](#secrets) |
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

- each part's `compose/`, `config/`, `scripted/`, `pack/` and `init-db.sh`, copied, and each module's pack (from `src/<id>/module/` for a module in the project);
- each module's standard wiring, `modules/<id>/standard/<name>.yml` for `base`, `local` and `build`, written from its `module.env`;
- `env/<service>.env`, each service's merged settings; `secrets/<service>.env`, its secrets, and `secrets.yml`, which has each service read them; `versions.env`, every part's merged;
- what's merged from the packs: `clients.yaml`, `permissions/`, `agent-routes.json`, `modules.env`, and each agent's grant;
- on a server, the `Caddyfile`: one site per public address;
- `compose.sh`, which runs Compose on all of it, as project `<PROJECT_NAME>-<env>`.

Compose files are read name by name (`base`, then each layer), part by part, with each module's standard file just before its own. `build.yml` is added for `DEV=1` and `scripted.yml` for `SCRIPTED=1`, from whichever parts have one. Edit the parts, never the bundle: it's rewritten on every command.

## Keeping up with the template

```sh
make template-update      # the latest release; README.md, modules/, site/ and src/ stay as they are
make verify
```

It prints what `CHANGELOG.md` says about each release it brought in; do what its **In a project** notes say. The whole practice (the two remotes, overriding instead of editing, conflicts, and releasing a template change) is [`template-updates.md`](template-updates.md).

## CI

`.github/workflows/ci.yml` runs on every push to `main` and every pull request: `make lint` and `make test-template`, then `make verify` with the scripted model. In the template, which has no module, it scaffolds one first. A project gets the workflow with the template, and runs it on its own modules.

## Feeding back to the foundation

What a project learns about the foundation goes back on purpose, as an item in [`upstream.md`](upstream.md), never as an edit to a foundation repo. Every workaround names its item in a comment, such as `# upstream U3: …`, so `grep -rn 'upstream U3'` finds what to remove once the fix is in a pinned image.

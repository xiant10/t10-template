# Changelog

What each release of the template changes, newest first, and what a project must do when `make template-update` brings it in. `make template-update` merges the latest release, `v<x.y.z>`, and prints the part of this file it added.

Releases are git tags on the template; how to make one, and how a project takes it, is [`docs/template-updates.md`](docs/template-updates.md). A change that needs nothing from a project bumps the last number; one that asks a project to do something bumps the middle one and says what under **In a project**.

## Unreleased

- **auth-server `sha-95e9f9b`**, the only foundation image whose `latest` moved since the last pins. It starts without LiveKit, with voice off (upstream U10, U15 done), so without the `livekit` component auth-server no longer gets placeholder LiveKit values: the component sets `LIVEKIT_URL` and `LIVEKIT_API_KEY` beside its secret.

**In a project:** nothing, unless `site/` set `LIVEKIT_*` for auth-server only to get past the placeholders; drop it. Then `make verify`.

## v0.9.2 (Nov 19, 2026)

- **`make smoke` expects a tool call only from an agent that has the modules' tools**: one whose `agent.json` lists an `mcpServers` URL ending `/mcp/modules`. A module agent another service calls, such as one that only extracts, has none, and with the scripted model failed "its tool call reached … through ai-gateway-tools" (from kuaidan-sales, whose `sales-capture` agent is one).

**In a project:** nothing. With `SCRIPTED=1`, such an agent is still checked to answer a turn.

## v0.9.1 (Nov 19, 2026)

- **`make test-template` passes in a project.** Its throwaway copies kept the project's `site/config/`, so a project that moved its ports or dropped a component failed `test_golden` and `test_tools_only` in CI. They start from the template's settings now (from kuaidan-sales, whose CI failed on every push since v0.9.0).

**In a project:** nothing. CI's `checks / template` job passes again.

## v0.9.0 (Nov 17, 2026)

What building a real module on the template turned up (kuaidan-sales's `site/docs/template-findings.md`, 1–10): a web app's sign-in works, it opens where Workbench sends it and looks like Workbench, sign-out ends every app, and `make smoke` signs in as a browser does. And a way for every project to report what it finds.

- **Web sign-in fixed** (finding 1). The kit sent `/auth/login` to `<issuer>/authorize`, which auth-server doesn't serve, so every web app's sign-in ended on a 404. It's `/v1/authorize` now, and `/auth/login` passes `tenant` on to it.
- **An app's home is `/t/<tenant>/`** (finding 2). Workbench and auth-server's Apps list open an app there, and the scaffold now routes it (`GET /t/{tenant}/{$}`), with its bare address sending a person to their tenant's. [`module.md`](docs/module.md#its-web-app) says so.
- **Notifications** (finding 3). The kit answers Workbench's bell, `GET /v1/notifications` and `POST /v1/notifications/read`: empty until a module sets `Module.Notifier`.
- **Pages that look like Workbench** (findings 4, 5). `t10kit/frame` is t10-modkit's frame (the rail, Apps list and account menu), and `t10kit/module` draws a page in it: `s.View(r, c)` reads the person's language, theme, name and Apps list from auth-server, `s.Page(w, r, v, module.Page{…})` draws the body inside the frame, and `module.Styles` is Workbench's tokens and base elements, light and dark. `Module.Sections` are the app's sections, served at `GET /v1/me/nav` and in the manifest's `app.nav`; the account menu's language and theme save through `POST /frame/language` and `/frame/theme`. `s.Token(r)` is the person's own token. The manifest gains `app.label_zh` (`Module.LabelZH`). The scaffold's placeholder page uses all of it.
- **Sign-out ends every app** (finding 6). `POST /auth/logout` now asks auth-server for a sign-out ticket and sends the browser on to end the sign-in and every t10 app's session, as the other apps do; auth-server returns it to the kit's `GET /signed-out`.
- **`PersonPage`** (finding 8): `Person` for a page a browser opens. One that isn't signed in, or whose session ended, goes to sign-in and back; one signed in to another tenant than `/t/{tenant}/` names signs in to that one, once.
- **Who sees an app** (finding 7). auth-server lists an app only for people holding one of its module's permissions, so the scaffold's catalog now has `<id>:use` and a `member` template granting it. Upstream U18 asks auth-server for an app every member sees.
- **`PORT_OFFSET`** (finding 9). One setting in `site/config/settings.env` moves every local port and `localhost` address the template and modules set, such as `PORT_OFFSET=10000` for a second project on the machine; `generated/<env>/ports.env` holds what it moved. `make alone` runs on a port free when it starts, instead of the local port + 10000, which could pass 65535 or clash with another project.
- **Browser sign-in in `make smoke`** (finding 10). For each module with `web`, it follows `/auth/login` through auth-server's `/v1/authorize` and sign-in page to the callback, and checks the app's `/t/<tenant>/` answers 200.
- **Reporting findings.** [`template-updates.md`](docs/template-updates.md#reporting-what-a-project-finds) says how a project writes down what it finds about the template, in `site/docs/template-findings.md`, which a new project starts with, and how the template takes it back.

**In a project:**

1. For each module with `web`: route its app's home at `GET /t/{tenant}/{$}` (see `platform/scripts/scaffold/go/server.go`), with `s.PersonPage` in place of `s.Person` on its pages, or `make smoke`'s new browser check fails. Optionally draw its pages with `s.View` and `s.Page`, list them in `Module.Sections`, and set `Module.LabelZH`.
2. If you patched `platform/kit/go/module/web.go` for the sign-in address or added a `Token` method, take the template's file on conflict (`git checkout --theirs platform/kit/go/module/web.go`): both are in the kit now. A frame copied into a module can go, for `t10kit/frame`. A module's own sign-out continuation to `/v1/signout` can go too: `/auth/logout` does it, and `?next=` is used only standalone.
3. If its app's users hold none of the module's permissions, add one they all get (as the scaffold's `<id>:use` and `member` template), or they won't see it in their Apps list.
4. If you moved local ports one by one in `site/config/local/settings.env` to run beside another project, you can replace them with `PORT_OFFSET` in `site/config/settings.env`.
5. Copy `site/docs/template-findings.md` from the template if you want the starter file (`git show template/main:site/docs/template-findings.md`); a project that already keeps one adds a **Status** column.

Then `make verify`.

## v0.8.1 (Nov 17, 2026)

A stable signing key on local, so `make reload` no longer breaks a module for minutes, and the last paths from before v0.7.0.

- **auth-server keeps its signing key on local.** `AUTH_SIGNING_KEY_CURRENT` is now made for every environment, not only dev and prod. Without it, auth-server's dev mode made a new key at every start, so restarting it (as `make reload` does after a pack change) signed out every session and voided each service's cached token until it expired: a module answered 503 and `make smoke` failed for up to five minutes.
- **Docs.** `new-project.md`, `design.md` and the comments in `new-module.py`, `release.sh`, `reload.sh`, `render.py` and `seed-demo.sh` gave module code at `src/<id>/` or `src/<SRC>/`; it's `modules/<id>/src/`. The old-path check in `make test-template` now catches `src/<anything>` and `src/crm` too.

**In a project:** nothing to do. The next `make up` adds the key to `site/secrets/local.env` (and `k8s-local.env` with `ENV=k8s-local`) and restarts auth-server with it, which signs everyone out once. Check with `make verify`.

## v0.8.0 (Nov 17, 2026)

A module's Dockerfile no longer depends on the project's layout, CI is split so a project can add its own jobs, and the docs say where things are since v0.7.0.

- **A module's Dockerfile builds anywhere.** The scaffold's Dockerfile copies the `kit` build context to `/kit` and points `go.mod`'s `replace t10kit` at it during the build, so moving the template's files or the module's folder no longer means editing every module's Dockerfile. `go.mod` keeps its relative `replace` for builds and editors on this machine.
- **CI the project owns.** The checks are now a reusable workflow, `.github/workflows/t10-template.yml`, which the template updates. `.github/workflows/ci.yml` is now the project's (`lib.OWNED`): it calls the checks, and a project adds its own jobs there, such as a release or a deploy, with `needs: checks`.
- **Pack or folder.** [`docs/module.md`](docs/module.md#its-pack-or-its-folder) says which of a module's `secrets.json`, `init-db.sh` and `hooks/` go in its pack and which in `modules/<id>/`. `make check` warns when a module has `init-db.sh` in both, since only the folder's runs.
- **Docs.** Every path from before v0.7.0 (`src/<id>/`, `../../kit/go`, `scripts/compose.sh` in the `project.mk` example) is now its `platform/` or `modules/<id>/src/` path, and four broken links are fixed, including the one in the README `make new-module` writes. `make test-template` now fails on a broken link or an old path in the docs.
- `ruff.toml` moved to `platform/ruff.toml`. A project's own ignore rules go in `site/.gitignore` or `modules/<id>/.gitignore`, so the root `.gitignore` stays the template's.

**In a project:** in each `modules/<id>/src/Dockerfile` made before this release, set `WORKDIR /src`, change `COPY --from=kit . /w/platform/kit/go/` to `COPY --from=kit . /kit/`, and start both `RUN` lines that call `go mod download` and `go build` with `go mod edit -replace t10kit=/kit && ` (compare with `platform/scripts/scaffold/go/Dockerfile`). Replace `.github/workflows/ci.yml` with the template's, adding back any job of your own below `checks`: `make template-update` keeps your copy, since it's now the project's. Then `make verify`.

## v0.7.0 (Nov 17, 2026)

Repository layout under `platform/` and co-located modules under `modules/<id>/`, synthesized OAuth clients and scripted wiring, self-contained module packs, per-agent action scoping, and web sign-in in the Go kit ([`docs/module.md`](docs/module.md)).

- **Cleaner repository layout (`platform/` and `modules/<id>/src/`).** The template's files now live under `platform/` (`platform/foundation/`, `platform/scripts/`, `platform/kit/`, `platform/docs/`, `platform/tests/`, `platform/CHANGELOG.md`), and each module's code lives inside its own folder at `modules/<id>/src/` (removing the top-level `src/` directory). A project's root holds only `platform/`, `modules/`, `site/`, `Makefile` and `README.md`, and `lib.OWNED` is `("README.md", "modules", "site")`.
- **Standard OAuth clients, runtimes, accounts and scripted wiring.** `platform/scripts/wiring.py` now generates each module's standard `clients.yaml` additions from its `CAPABILITIES` and `AGENTS` (its `<service>-web` OAuth client for `web`, each agent's `agent-ti-<agent>` runtime for `agent`, and `runtime_grants` for `tools`), its `SERVICE_ACCOUNTS` (`SERVICE` and each agent's runtime), and its `standard/scripted.yml` (`SCRIPTED_TOOL` in `module.env`, default `<id>_whoami`). A scaffolded module no longer needs `clients.fragment.json`, `compose/scripted.yml`, or `SERVICE_ACCOUNTS` in `module.env`; existing ones still work and merge over the standard entries.
- **Self-contained module packs.** A module's pack (`modules/<id>/src/module/`, or `/module` in its image) can now hold its own `secrets.json`, `init-db.sh` (mounted into `<id>-db` and in `make alone`) and `hooks/<event>.sh` or `.py`, layered just before `modules/<id>/`'s own. `make alone` also gives throwaway values to any secrets the module declares, and layers `site/config/` settings for its service.
- **Per-agent action scoping and multi-audience grants.** `AGENT_ACTIONS_<AGENT>` in `module.env` restricts one agent and its runtime to a subset of the module's tool actions; `GRANT_AUDIENCES` adds extra audiences when a module's agent calls another module's tools.
- **Web sign-in and session cookies in `t10kit/module`.** `Module.Register` now serves `GET /auth/login`, `GET /auth/callback` (PKCE + code exchange using `AUTH_WEB_CLIENT_SECRET`, sealed in an AES-GCM cookie with `<ID>_SESSION_KEY`) and `POST /auth/logout`, and `Module.Person` accepts either a `Bearer` token or the session cookie (with same-origin checks on state-changing requests). In standalone mode (`make alone`), `GET /auth/login` signs in immediately, and `Fake` accepts `Bearer person:<perms>` and `Bearer agent:<perms>` to test non-admin permissions. `Auth` caches the service's own token until 30s before expiry.
- **Deploy, reload and Kubernetes.** `make deploy` publishes `agent-routes.json` on the server after starting the stack; `make reload` rebuilds all of a module's `SERVICES` and restarts `ai-gateway-tools` and `workbench` when its pack changes; `platform/scripts/kube.py` carries Compose's `mem_limit` to Kubernetes `resources.limits.memory`.

**In a project:** move each module's code from `src/<id>/` into `modules/<id>/src/`, set `SRC=src` in `modules/<id>/source.env`, update `replace t10kit` in `modules/<id>/src/go.mod` to `../../../platform/kit/go`, and in `modules/<id>/src/Dockerfile` set `WORKDIR /w/modules/module/src` and `COPY --from=kit . /w/platform/kit/go/`. Optionally, delete `modules/<id>/src/module/clients.fragment.json`, `modules/<id>/compose/scripted.yml`, and `SERVICE_ACCOUNTS` from `module.env`.

## v0.6.0 (Nov 16, 2026)

Extending without editing the template: every part adds to the foundation the same way, a module says what it has, and a project has its own hooks and commands ([`docs/guide.md`](docs/guide.md#what-a-part-adds), [`docs/module.md`](docs/module.md#what-it-has)).

- **Every part adds the same way.** Any part, `site/` included, can have `clients.json`, `agent-routes.json`, `permissions/`, `public.json` and `part.env` (additions to the foundation's lists, `WORKBENCH_URLS` and the like). So a project adds its own OAuth client, such as a mobile or mini-program app, a catalog or an agent route in `site/`, without a module. A client or runtime with `"_merge": true` changes one already defined, such as adding a redirect URI to `t10-workbench`. A module's additions from its pack come just before its own folder's, so `modules/<id>/` and `site/` can change them too. `runtime_grants` are given once every part is in, so one can name a runtime a later part defines.
- **A module says what it has.** `module.env` gets `CAPABILITIES`, of `web`, `tools`, `agent` and `database`, and each one adds only its own wiring, secrets, list entries, checks and smoke steps. A module without `web` needs no public address, web client or session key; one without `tools` isn't on the tools gateway or in the harnesses' grants. `AGENTS` lists several agents, each with its own runtime, route, grant and secret (`<AGENT>_AUTH_CLIENT_SECRET` beyond the first). `SERVICES` adds services from the same image, such as a worker, with the standard settings, secrets and server limits. `REQUIRES` names components or modules it needs, which `make check` and every command enforce.
- **Pack versions.** `PACK_VERSION=1` in `module.env` says which pack format it's written in; the template refuses one it can't read, so a module in its own repo can't silently meet a template that reads its pack differently. A pack without it, or without `CAPABILITIES`, reads as before (web, tools, a database unless `DATABASE=false`, an agent when `AGENT` is set).
- **Hooks for every part.** `hooks/<event>.sh` or `.py` in any part, run in part order: `post-up` (after `make up`), `seed-demo`, `smoke`, `check`, `pre-deploy` and `post-deploy`. `scripts/hook.py` runs them; a `smoke` or `check` hook in Python gets the same helpers a module's `hooks/smoke.py` always had.
- **A project's own commands.** The Makefile includes `site/project.mk` and each `modules/<id>/module.mk`, which are the project's, and `make help` lists their targets. `make help` now prints names correctly whatever files it reads.
- **Layers for an environment.** `LAYERS=server,staging` in `site/config/<env>/settings.env` sets the layers it reads, keeping `local` or `server` first; without it, its shape's as before.
- **One list of what a project owns,** `lib.OWNED`, which `make template-update` and `make check` both read.
- **Scaffolds by language.** `scripts/scaffold/src/` is now `scripts/scaffold/go/`, and `make new-module SCAFFOLD=<lang>` picks one; `go` is the default and the only one so far.
- Components' `component.env` is now `part.env`, as for every part.
- With several modules, the scripted model calls the tool of the module a turn names (`make smoke` puts `[<id>]` in its prompt), so each module agent's turn reaches its own module; before, every agent called the first module's tool, which its grant refuses.
- `make check` stops with one clear failure when the bundle doesn't render, such as for a new module whose secrets `make up` hasn't made yet.

**In a project:** add `PACK_VERSION=1` and `CAPABILITIES=web,tools,agent,database` (without what the module doesn't have) to each `src/<id>/module/module.env`, and for a module with `DATABASE=false`, drop that line and leave `database` out of `CAPABILITIES`; `make contract` now requires both keys, and refuses `DATABASE` beside `CAPABILITIES`. Optionally, replace `AGENT`, `AGENT_TITLE` and `AGENT_RUNTIME` with `AGENTS=<agent>` and `AGENT_TITLE_<AGENT>=…` as `make new-module` now writes; the old keys still work. A module in its own repo gets the same keys in its image's pack with its next release. Move anything a project kept in an edited template file (a Makefile target, a client added to `foundation/clients.json`, a step added to a script) to `site/project.mk`, `site/clients.json` or `site/hooks/`. Check with `make contract MODULE=<id>` for each module, then `make verify`.

## v0.5.0 (Nov 16, 2026)

Kubernetes on this machine ([`docs/guide.md`](docs/guide.md#kubernetes-on-this-machine)).

- **`ENV=k8s-local`** runs the whole stack on this machine's Kubernetes, such as Docker Desktop's: `make up`, `seed-demo`, `smoke`, `check`, `verify`, `reload`, `ps` and `logs` work as on `local`. It's in a namespace of its own, `<PROJECT_NAME>-k8s-local`, on ports 36xxx and 35xxx, so it runs beside `local` and beside a workspace's own cluster deployment.
- **Made from Compose.** `TARGET=k8s` has `scripts/kube.py` turn `docker compose config` on the bundle into Kubernetes objects (`generated/<env>/kustomization.yaml`, `k8s/`), so nothing is written twice. Secrets become one Secret per service, made in memory, never on disk. `make check` builds the objects with kustomize and checks no secret is in them.
- A part's `k8s/<layer>/` is a kustomize component for what's particular to Kubernetes.
- `make new-module` gives a module a k8s-local port, `PORT` + 18000.
- The scripted model is on by itself on any local-shaped environment without `LLM_API_KEY`, not just `local`.

**In a project:** to run `k8s-local` with a module made before this release, give it a port that doesn't clash with `local`'s: `modules/<id>/config/k8s-local/settings.env` with `<ID>_PORT` and `<ID>_PUBLIC_URL` on `PORT` + 18000, as `make new-module` now writes. Without it, `k8s-local` uses the module's `local` port, which works while `local` isn't running. A project with its own `site/config/k8s-local/` isn't affected otherwise.

## v0.4.0 (Nov 16, 2026)

Running a server ([`docs/guide.md`](docs/guide.md#running-a-server)).

- **Backups.** A `backup` service dumps every database daily on a server (`BACKUP_EVERY`, `BACKUP_KEEP_DAYS`). `make backup`, `make backup-pull` (checked, then encrypted with age for the keys in `site/secrets/.sops.yaml`, into `backups/<env>/`), and `make restore FILE=… CONFIRM=<env>`.
- **Logs and memory.** Every service on a server rotates its logs and has a memory limit (`LOG_MAX_SIZE`, `LOG_MAX_FILES`, `MEM_LIMIT`, `MEM_LIMIT_LARGE`); `make check` fails for a service without them.
- **Server commands run on the host.** `make ps`, `logs`, `down`, `backup` and `rotate` with a server's `ENV` run there over SSH; `DEPLOY_SSH` holds ssh options. `make down-all` on a server needs `CONFIRM=<env>`.
- The model gateway's audit is on a volume, so it outlives the container.

**In a project:** a module's own Compose service that isn't from the standard wiring needs `logging` and `mem_limit` in that module's `compose/server.yml`, as `foundation/compose/server.yml` does, or `make check` fails for a server.

## v0.3.0 (Nov 16, 2026)

A module is proven alone before it meets the foundation ([`docs/integration.md`](docs/integration.md)).

- **`make alone MODULE=<id>`** runs a module's service by itself, with its own Postgres and no foundation. With `T10_STANDALONE=1`, the kit (`module.NewAccess`) stands in for auth-server: `Bearer person` is a tenant admin, `Bearer agent` an agent holding the catalog's actions. It refuses to start beside `AUTH_ISSUER`.
- **`make contract MODULE=<id>`** checks a module's pack and, run alone, everything its service must answer, including that each tool is callable with the catalog's actions.
- **`make verify`** runs the gates in order: `test`, each module's `contract`, then the full stack.

**In a project:** a module made before this release: in its `main.go`, call `module.NewAccess(moduleID, service)` instead of `module.NewAuth`, so `make contract` can run it alone. A module in its own repo that doesn't use the kit answers `T10_STANDALONE=1` as `docs/integration.md` says.

## v0.2.0 (Nov 16, 2026)

Server secrets: encrypted, per service, and rotatable.

- **Each service gets only its own secrets.** A secret's `env` in `secrets.json` says which service gets it under which variable; `render.py` writes `secrets/<service>.env`. No foundation Compose file holds a secret any more, and `make check` fails on one there (warns in a project's).
- **Encrypted server secrets** with SOPS and age: `make secrets-key`, `secrets-init`, `secrets-set`, `secrets-edit`. `site/secrets/<env>.enc.env` is committed; values are decrypted in memory only.
- **Rotation**: `make rotate NAME=… ENV=… APPLY=1` for `replace`, `account:<name>` and `signing-key` secrets. The signing key is generated (`es256`).
- auth-server is recreated whenever `clients.yaml` changes (`T10_CLIENTS_SHA`).

**In a project:**

1. Run `make secrets-key` once, commit `site/secrets/.sops.yaml`, then `make secrets-init ENV=<env>` for each server environment to encrypt its `<env>.env`, and commit `<env>.enc.env`. Run `make secrets-key BREAKGLASS=1` and keep the printed key offline.
2. A Compose file of yours that writes `${SECRET}` still works; `make check` warns. Move it to an `env` entry in that part's `secrets.json`.

## v0.1.0 (Nov 16, 2026)

The first release. What every module shares now comes from the template, so a template update reaches every module.

- **Generated module wiring.** `scripts/render.py` writes each module's standard Compose wiring from its `module.env` (`scripts/wiring.py`): its database one-shot, its accounts, its agent, its service and what waits for it. Its standard secrets come from there too. A module's folder holds only what's particular to it: `make new-module` writes 7 small files where it wrote 13. `DATABASE=false` in `module.env` leaves the database out.
- **One place for a module's grants.** What its agent tools need is said once, in its catalog's `agent` block. The harnesses, its agent's grant and the runtimes in `clients.yaml` all get it from there. `GRANT_ACTIONS` and `GRANT_AUDIENCE` in `module.env` are optional.
- **The Go kit, `kit/go/`.** The token verifier, auth, MCP and the routes every module answers moved out of each module's code into `t10kit/module`, which a module imports. A module's code is its `main.go`, its tools, its web app and their tests.
- **`make new-module ID=crm`** is enough: `SERVICE` defaults to `t10-<id>`, `PORT` to the next free one from 18100, and the code goes in `src/<id>/`, beside `modules/<id>/`.
- **Scripted model by itself.** On local, with no `LLM_API_KEY`, every command uses the scripted model; `SCRIPTED=` turns it off.
- **New commands.** `make doctor` (Docker, Compose, Python, free ports), `make lint` (ruff and shellcheck, in Docker) and `make test-template` (the template's own tests in `tests/`, and the kit's).
- **CI.** `.github/workflows/ci.yml` lints, runs the template's tests, and runs `make verify` on the project's modules (or, in the template, a scaffolded one).
- **Releases.** `make template-update` takes the latest release unless given `REF=`, and prints what this file says about it.
- The empty Kubernetes skeleton (`foundation/k8s/`, `site/k8s/`, each module's `k8s/`) is gone until Kubernetes is built (`docs/plan.md`, phase E).

**In a project** made before this release:

1. For each module whose code is in `src/`: delete from `modules/<id>/compose/base.yml` what the standard wiring now does (the `<id>-db` and `<id>-seed` one-shots, `auth-server`, `t10-agents`, `agent-ti`, `ai-gateway-tools` and `workbench`, and the service's image, `env_file`, standard environment, healthcheck and `depends_on`); keep only what's particular to it. Delete `compose/local.yml` (unless it adds more than the port and build), `init-db.sh` (unless it does more than make the database and login), the standard entries in `secrets.json`, and `k8s/`. `make config-show`, `docker compose config` (`scripts/compose.sh config`) and `make verify` show the result is the same.
2. To move its code onto the kit: replace its `auth.go`, `mcp.go` and `verifier/` with the kit, as `scripts/scaffold/src/` does (`main.go`, `server.go`, `tools.go`, `go.mod` with `replace t10kit => ../../kit/go`, and the `Dockerfile`'s `COPY --from=kit`). Until then it keeps building as it is, apart from its local build, which now passes the kit as a build context it doesn't use.
3. A module in its own repo needs nothing: its folder's files still override the standard wiring, and the same names are used.

# Changelog

What each release of the template changes, newest first, and what a project must do when `make template-update` brings it in. `make template-update` merges the latest release, `v<x.y.z>`, and prints the part of this file it added.

Releases are git tags on the template; how to make one, and how a project takes it, is [`docs/template-updates.md`](docs/template-updates.md). A change that needs nothing from a project bumps the last number; one that asks a project to do something bumps the middle one and says what under **In a project**.

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

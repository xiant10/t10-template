# Changelog

What each release of the template changes, newest first, and what a project must do when `make template-update` brings it in. `make template-update` merges the latest release, `v<x.y.z>`, and prints the part of this file it added.

Releases are git tags on the template; how to make one, and how a project takes it, is [`docs/template-updates.md`](docs/template-updates.md). A change that needs nothing from a project bumps the last number; one that asks a project to do something bumps the middle one and says what under **In a project**.

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

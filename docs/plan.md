# What's left to build

Nov 16, 2026 · Revised Nov 16: re-planned top down, structure first. What's built is in [`design.md`](design.md) and how to use it in [`guide.md`](guide.md). This is the template's plan; a project's own items (its module pins, where its servers run) go in its `site/docs/plan.md`.

## Order of work

Each phase builds on the one before: the structure every later step lands in, then proof that it's a template, then what a server needs (secrets first), then Compose on servers, then Kubernetes.

| Step | Change | Status |
| --- | --- | --- |
| **A. Structure** | Moves only, nothing behaves differently. Each step checked by diffing the rendered Compose config and a full local run | |
| A1 | The ownership rule, written in `guide.md`: the root and `foundation/` are the template's, `modules/` and `site/` the project's, `src/` and `generated/` never committed; every part layered the same way | Done Nov 16 |
| A2 | Secrets: the values in `site/secrets/<env>.env`, one code path for every environment, `generated/` only ever a copy; `make secrets-init ENV=…` for any environment | Done Nov 16 |
| A3 | Versions in layers: `foundation/versions.env` (the template's tested set), `modules/<id>/versions.env`, optional `site/versions.env`, merged into the bundle; `modules/<id>/source.env` replaces `repos.txt`; `make pin` writes the file that wins | Done Nov 16 |
| A4 | `foundation/dev/` renamed `foundation/scripted/`, as `dev` is now an environment; the project's own plan moved to `site/docs/` | Done Nov 16 |
| A5 | Merge the Kubernetes skeleton: `foundation/k8s/{vendor,base,local,server}/`, a module's `k8s/`, `site/k8s/`; base plus each layer builds, empty | Done Nov 16 |
| **B. Prove the template** | | |
| B1 | A copy with no module: `make up`, `make check` and `make smoke` on the foundation alone. Found that `t10-agents` installed every agent its image ships, including a module's (U6), which crashed `agent-ti` without that module's account; it now copies only the foundation's `ti` plus each module's agent from `/module-agents/` | Done Nov 16 |
| B2 | `make new-module ID=…`, which makes the folder, and a written module contract (`module.md`). A scaffolded `property` plus its own additions matched its hand-written folder and passed a full local run. Local runs now add a new module's generated secrets themselves | Done Nov 16 |
| B3 | The template as its own repo, `xiant10/t10-template`, with no module (done Nov 16); a project tracks it as a git remote, `make template-update` merges it, and `make check` warns when a template file was edited in the project | In progress |
| B4 | Foundation components: `foundation/` split into a core and `components/` (`assistant`, `livekit`, `console`, `automations`), which a project picks with `FOUNDATION`; agent-sales removed. Everything on, and the core alone, each pass a full local run | Done Nov 16 |
| **C. Secrets** | Before any server, since a server needs its secrets | |
| C1 | The inventory says which service gets which secret: `consumers` becomes a map from service to variable to value (such as `DATABASE_URL`), and `render.py` writes each service's secrets as its own file, which Compose reads as a second env file and Kubernetes as that service's Secret. Most `${…}` references leave `foundation/compose/base.yml`. A generator for keys like the signing key (`authctl gen-key`, one-line PEM) | Not started |
| C2 | SOPS and age: `site/secrets/.sops.yaml`, `make secrets-init ENV=…` and `make secrets-edit ENV=…` on `<env>.enc.env`; decrypted to `site/secrets/<env>.env` only while a command runs, and the bundle's copy deleted from this machine after `make deploy` | Not started |
| C3 | Rotation: what `make rotate` prints today, working for each environment | Not started |
| **D. Compose on servers** | Built so far: the `server`, `dev` and `prod` layers, `SHAPE`, `TARGET`, one Compose project per environment, Caddy with TLS from each part's public addresses, LiveKit for real, `make deploy` (Nov 16; tested on this machine behind Caddy on `*.localhost`, not yet on a real host) | |
| D1 | Postgres backups (a `pg_dump` job to off-host storage, with each module's data keys kept beside them), log rotation and memory limits, a volume for the model gateway's audit, a guard on `make down-all` for servers, a smoke sign-in on servers (U14, or a smoke service account) | Not started |
| D2 | The first real `dev` host: `make deploy ENV=dev`, `make smoke ENV=dev` | Not started. Needs a host (`site/docs/plan.md`) |
| **E. Kubernetes** | Once Compose on a server isn't enough | |
| E1 | The module lists (`TOOL_SERVERS`, `GRANT_*`, …) move from `foundation/compose/base.yml` into `config/`, with `render.py` appending each module's, so both targets read them | Not started |
| E2 | `make vendor` | Not started |
| E3 | `foundation/k8s/` base and a component per layer, each module's component, `render.py` writing `generated/<env>/` as a kustomize folder, `TARGET=k8s` | Skeleton only (A5) |
| E4 | A `k8s-local` environment on Docker Desktop passes `make check` and `make smoke` | Not started |
| E5 | A cluster, with Postgres in the cluster | Not started |
| **F. Ongoing** | `upstream.md` items; projects pin their modules once their images have packs | |

Done before the re-plan, Nov 16: the inventory and local secrets, the clients merge, each service's settings merged into `env/<service>.env`, the self-contained bundle in `generated/<env>/`, the template split (`modules/<id>/`, `site/`, `src/`, module hooks, nothing outside `modules/` and `site/` naming a module), and `make check` and a scripted Compose smoke test, run locally since the repo has no CI.

## Kubernetes (E)

The foundation's manifests live in each foundation repo's `deploy/k8s`, and the workspace's base reaches them as sibling folders (`../../../auth-server/deploy/k8s/base`). We can't do that without checkouts. Instead:

1. **`make vendor`** copies each foundation repo's `deploy/k8s` into `foundation/k8s/vendor/<repo>/`, at the commit that repo's pinned image tag names (`sha-<commit>` in `versions.env`), for example with `git archive` from GitHub. The files are committed, never edited by hand, and their diff shows up on every upgrade.
2. **`foundation/k8s/`** is our copy of the workspace's `deploy/k8s/base`, minus any module, pointing at `vendor/`. Its `images:` block maps each local image name (`auth-server:latest`, …) to the pin from `versions.env`.
3. **`modules/<id>/k8s/`** is a kustomize Component, so an overlay adds a module with one line:
   - its Deployment and Service (vendored from its repo's `deploy/k8s`, image pinned),
   - a `configMapGenerator` merging `<id>.yaml` into `auth-server-permissions` and `<id>=…` into `workbench-modules` (`MODULES_DIR`), as the workspace's `catalog/` does today,
   - a ConfigMap of the agent folder, and a patch adding an init container to `agent-ti` that copies it into the agents emptyDir after `t10-agents`,
   - patches for `GRANT_*` on the harnesses, `TOOL_SERVERS` and `TOOL_MODULE_SERVERS` on ai-gateway-tools, its route, and NetworkPolicy rules letting its service reach `ai-gateway-agent` and `ai-gateway-tools` reach it,
   - Jobs: `<id>-db` creates the database and login, and `<id>-accounts` runs `authctl service-add`. Both are idempotent and run as hooks, or with `make k8s-seed`.
4. **Layers, as on Compose.** An environment with `TARGET=k8s` (for example `k8s-local` with `SHAPE=local`, or a cluster's `prod`) gets a component per layer: `foundation/k8s/local/` for Docker Desktop (LoadBalancer services and dev mode, adapted from the workspace's `overlays/local`) and `foundation/k8s/server/` (ingress with cert-manager for each public address, real issuer URLs, replicas and disruption budgets, starting from `auth-server`'s vendored `overlays/production`). Postgres runs in the cluster in every environment for now, as decided Nov 16: a StatefulSet with a volume, and a backup CronJob. `render.py` writes `generated/<env>/kustomization.yaml` from these, the modules' components and `site/k8s/<env>/` patches, and `make up` and `make deploy` run `kubectl --context $KUBE_CONTEXT apply -k` on it, pruning only this project's objects.
5. **Pull secrets.** The foundation images are public and need none. A private module image, such as `t10-property`'s, needs its `k8s/` to give that pod `imagePullSecrets: [{name: ghcr}]`, made from `GHCR_PULL_TOKEN`. `k8s/components/pull-secret/` does the same for every pod's ServiceAccount, so an overlay can turn it on with one line if foundation images go private.

### Settings in Kubernetes

`render.py` turns each service's merged `generated/<env>/env/<service>.env`, the same file Compose reads, into one patch that sets those variables on its container. It uses `env:` rather than a ConfigMap merge because the vendored manifests mix `env:` and `envFrom:`, and an explicit `env:` entry wins over both. Files in `config/<svc>/` become a `configMapGenerator` plus a volume patch. Generated ConfigMap names carry a content hash, so a change rolls the pods that use it. The exception is `workbench-modules`, which `workbench` re-reads without a restart. Replicas, resources and probes are ordinary kustomize patches in the overlay (`k8s/<env>/patches/`).

Commands that come with it:

| Command | Does |
| --- | --- |
| `make config-show SVC=… ENV=prod` | As today, and for Kubernetes |
| `make config-diff ENV=…` | What changed compared with what's running: `docker compose config`, or `kubectl diff -k` |
| `make check` | Also: `kustomize build` succeeds for each overlay, and every variable in `config/` is either known for that service (taken from the vendored manifests) or marked `# custom: <reason>`, which catches typos a service would ignore. Exact once U9 lands |

## Production secrets (C)

### Choice: SOPS with age, encrypted in this repo

| Option | Fits | Doesn't fit |
| --- | --- | --- |
| **SOPS + age** (chosen) | One encrypted file per environment that feeds both Compose and k8s. Works offline and in a local repo. Diffs show which keys changed. No controller in the cluster | Whoever deploys needs the age key. No automatic rotation |
| Sealed Secrets | k8s-native, and the encrypted value is safe to commit | k8s only, so Compose needs a second mechanism. Values are tied to one cluster's key, and you can't read them back to check |
| External Secrets Operator | The best answer once there's a cloud secret manager or Vault, with central rotation and audit | Needs that store first. Too much for one local repo today |

SOPS keeps secret names and locations stable. If we later move to External Secrets, each generated `Secret` becomes an `ExternalSecret` with the same name and keys, and no service notices the change.

### Layout

```text
site/secrets/
├── .sops.yaml               which age recipients can decrypt each environment
├── local.env                as today: plain text, per checkout, not committed
├── prod.enc.env             SOPS-encrypted, committed
└── uat.enc.env              SOPS-encrypted, when uat exists
```

- **One file per environment** is the only place values live. A command that needs them decrypts it to `site/secrets/<env>.env` (git-ignored, mode 600) for as long as it runs, the same file every command already reads, and writes:
  - for Compose, `generated/<env>/secrets.env` (mode 600), the bundle's own secrets file, which `make deploy` copies to the host with the rest and then deletes here,
  - for k8s, `Secret` manifests applied directly with `sops -d … | scripts/to-k8s-secrets | kubectl apply -f -`, so decrypted YAML never touches disk. KSOPS would do the same inside `kustomize build`, but needs a plugin installed everywhere.
- **Age keys.** Each project's operator holds an operator key, plus one break-glass key printed and stored offline. `.sops.yaml` lists the recipients, so removing someone means re-encrypting with `sops updatekeys`. Keys never enter the repo.

### Rotation, by kind

`make rotate NAME=…` prints each secret's steps from the inventory. Grouped by how rotation works:

| Secret | Consumers | Rotation |
| --- | --- | --- |
| `AUTH_SIGNING_KEY_CURRENT` and `_NEXT` | auth-server | Two-phase: generate with `authctl gen-key`, publish as `_NEXT`, wait one token lifetime, promote to `_CURRENT` |
| Service client secrets (`agent-ti`, `ai-gateway*`, `t10-knowledge`, `t10-automations`, each module's service and agent, …) | Each service, and its account in auth-server | Two-phase: `authctl service-rotate`, roll the service, then `authctl service-finish`. auth-setup never rotates |
| Web client secrets (`t10-workbench`, `t10-console`, each module's web app) | That app, plus the hash in `clients.yaml` | Change the value, re-render, then roll auth-server and the app together. Sign-in fails briefly in between |
| Session keys (`WORKBENCH_SESSION_KEY`, each module's) | That app | Change and roll the app. Everyone signs in again |
| `AUTH_TOTP_KEY` | auth-server | Not rotatable without re-enrolling TOTP |
| **A module's data key**, such as `<ID>_DATA_KEY` | That module | **May not be rotatable. Losing it makes encrypted data unreadable.** Back it up with every database backup |
| Database logins | That service, plus the Postgres role | New role password, roll the service. External Postgres in prod |
| Model provider keys (`LLM_API_KEY`, speech keys) | ai-gateway-llm only | Add the new key at the provider, roll the gateway, then revoke the old one |
| Gateway API keys | ai-gateway, and harnesses calling it | Change on both sides, then roll |
| `LIVEKIT_API_SECRET` | auth-server, LiveKit, voice worker | Change all three together |
| `GHCR_PULL_TOKEN` | Pull-secret component | Make a new token, apply it, then revoke the old one |

### Rules

- Never pass secrets on a command line or in a ConfigMap. Only `Secret` objects or `env_file`.
- `prod` never uses dev mode. `AUTH_DEV_MODE` is unset, which also makes auth-server require a signing key.
- Each service sees only its own secrets: one k8s `Secret` per service, never a shared one.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Remote kustomize bases (`github.com/...//deploy/k8s?ref=`) | Network on every build, and upgrades show no diff. Vendoring gives the same pin and makes it reviewable |
| Helm chart for the whole platform | The foundation ships kustomize. A chart would redo its manifests, and they'd drift |

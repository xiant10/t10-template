# What's left to build

Nov 16, 2026 · Revised Nov 16: re-planned top down, structure first. What's built is in [`design.md`](design.md) and how to use it in [`guide.md`](guide.md). This is the template's plan; a project's own items (its module pins, where its servers run) go in its `site/docs/plan.md`.

## Order of work

Each phase builds on the one before: the structure every later step lands in, then proof that it's a template, then what a server needs (secrets first), then Compose on servers, then Kubernetes. A finished step leaves this table for [`CHANGELOG.md`](../CHANGELOG.md) when it's released.

| Step | Change | Status |
| --- | --- | --- |
| **A. Structure**, **B. Prove the template** | The ownership rule and layout; secrets, versions and environments in layers; foundation components; the template as its own repo with `make template-update`; `make new-module` with a module's code in the project, `make test`, `reload`, `verify` and `release`. What each step found is in git history | Done Nov 16 |
| B6 | Maintainability (v0.1.0, [`CHANGELOG.md`](../CHANGELOG.md)): each module's standard wiring and secrets generated from its `module.env`; its grants said once, in its catalog; the Go kit, `kit/go/`; `make doctor`, `lint`, `test-template`; tests in `tests/`; CI; releases with migration notes; the scripted model on by itself; the empty Kubernetes skeleton removed. The generated wiring was diffed against the old copied wiring for local, `DEV=1`, `SCRIPTED=1` and prod, and a scaffolded module passed `make verify` | Done Nov 16 |
| B8 | Extending without editing the template (v0.6.0, [`CHANGELOG.md`](../CHANGELOG.md)): every part adds clients, routes, catalogs and list entries the same way, with `_merge` to change one; module `CAPABILITIES`, several `AGENTS`, more `SERVICES`, `REQUIRES`; `PACK_VERSION`; hooks for every part; `site/project.mk` and `modules/<id>/module.mk`; `LAYERS`; `lib.OWNED`; scaffolds by language. `make verify` passed with a standard module, one with no web app, two agents and a worker, and a `site/` with its own client, a merged client, hooks and a make target | Done Nov 16 |
| B7 | Gates for a module (v0.3.0): `make alone` runs it by itself with the kit standing in for auth-server, `make contract` checks its pack and service, `make verify` runs unit, alone, then integrated; [`integration.md`](integration.md) is the protocol | Done Nov 16 |
| **C. Secrets** | Before any server, since a server needs its secrets | |
| C1 | Each secret's `env` says which service gets it; `render.py` writes `secrets/<service>.env`, and no Compose file holds a secret (resolved config diffed identical for local, scripted, `DEV=1`, prod and core); `es256` signing keys from `authctl gen-key` | Done Nov 16 |
| C2 | SOPS and age: `make secrets-key` (operator, break-glass, recipients), `secrets-init`, `secrets-set`, `secrets-edit` on `<env>.enc.env`, decrypted in memory only; a server's bundle holds secrets only while Compose or `make deploy` needs them | Done Nov 16 |
| C3 | `make rotate NAME=… ENV=… APPLY=1`: `replace`, `account:<name>` (authctl two-phase, tested live), `signing-key` (NEXT then promote) | Done Nov 16 |
| **D. Compose on servers** | Built so far: the `server`, `dev` and `prod` layers, `SHAPE`, `TARGET`, one Compose project per environment, Caddy with TLS from each part's public addresses, LiveKit for real, `make deploy` (Nov 16; tested on this machine behind Caddy on `*.localhost`, not yet on a real host) | |
| D1 | Postgres backups (a `backup` service, `make backup`, `backup-pull` encrypted for the age keys, `restore`, tested end to end), rotated logs and a memory limit for every service on a server (`make check` enforces it), a volume for the model gateway's audit, server commands run on the host over SSH (`DEPLOY_SSH`), `make down-all` on a server needs `CONFIRM`. A full deploy rehearsed against a throwaway host with its own Docker. Still open: a smoke sign-in on servers (U14) | Done Nov 16 |
| D2 | The first real `dev` host: `make deploy ENV=dev`, `make smoke ENV=dev` | Not started. Needs a host (`site/docs/plan.md`) |
| **E. Kubernetes** | Once Compose on a server isn't enough | |
| E1–E4 | `TARGET=k8s` and the `k8s-local` environment: `scripts/kube.py` makes the Kubernetes objects from Compose's resolved config, so the module lists stay where they are (E1) and nothing is vendored (E2), as decided Nov 16 ([below](#kubernetes-e)). On Docker Desktop, `make up`, `seed-demo`, `check`, `smoke` and `reload` pass for the foundation alone and with a scaffolded module, beside the Compose stack and the workspace's `t10` namespace | Done Nov 16 |
| E5 | A server cluster: [below](#a-server-cluster-e5) | Not started |
| **F. Ongoing** | `upstream.md` items; projects pin their modules once their images have packs | |


## Kubernetes (E)

### Decided Nov 16: made from Compose, not vendored

The first plan was to vendor each foundation repo's `deploy/k8s` at its pinned commit and layer kustomize components over it. Building E3 found two problems with that:

- The foundation's manifests hard-code the `t10` namespace and `*.t10.svc.cluster.local` addresses in their defaults. A project in its own namespace would reach the workspace's services wherever a default isn't overridden, without an error; in the `t10` namespace it would replace them. On this machine the workspace's whole stack already runs there.
- Their settings, secrets and setup differ from the template's Compose stack, service by service. Keeping both meant every setting, secret and module wiring twice, with `make smoke` testing only one of them.

So `scripts/kube.py` makes the objects from `docker compose config` on the bundle `render.py` already writes: the same images, settings, secrets, mounts, health checks and order, in a namespace of its own ([`guide.md`](guide.md#kubernetes-on-this-machine)). One description stays one description, and what Kubernetes runs is what the gates test. E1 (moving the module lists out of Compose) and E2 (`make vendor`) aren't needed. What's given up: the foundation's own replica counts, disruption budgets and NetworkPolicies, which a server cluster adds back in E5, as kustomize components of its own.

### A server cluster (E5)

What's left before `TARGET=k8s` on a `dev` or `prod` shape:

- **Secrets**, decrypted in memory from `<env>.enc.env` straight into `kubectl apply`, as `make up` already does for `k8s-local`; nothing to change but allowing the shape.
- **Ingress** with cert-manager for each public address, from the same `public.json` files Caddy reads, in place of the LoadBalancer Services.
- **More than one node.** A volume shared by two services (`agents`, written by `t10-agents` and read by `agent-ti`) needs ReadWriteMany or a different hand-off; one replica per Deployment until each service says it can run more.
- **Limits and policies:** resources from `MEM_LIMIT`, NetworkPolicies, disruption budgets, as a `foundation/k8s/server/` component.
- **Images from the registry:** modules from `make release`, with a pull secret for a private one.
- **Postgres in the cluster** with a backup CronJob, as decided Nov 16, or a managed one.
- **`make deploy ENV=<env>`** applying to `KUBE_CONTEXT` instead of copying over SSH, and `make smoke` through the ingress.

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

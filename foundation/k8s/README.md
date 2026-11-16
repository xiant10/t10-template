# foundation/k8s/

The foundation on Kubernetes, the second target beside `../compose/`. A skeleton for now: what
each folder will hold is below and in `docs/plan.md` (phase E). An environment uses it when its
settings say `TARGET=k8s`, which `scripts/render.py` refuses until it's built.

| Path | Holds | Compose's counterpart |
| --- | --- | --- |
| `vendor/<repo>/` | Each foundation repo's `deploy/k8s`, copied by `make vendor` at the commit its pinned image names. Committed, never edited | The images in `../versions.env` |
| `base/` | Ties the vendored manifests together, with the namespace and the pinned images | `../compose/base.yml` |
| `local/` | Component: one machine (Docker Desktop): Postgres and LiveKit in the cluster, LoadBalancer services, dev mode | `../compose/local.yml` |
| `server/` | Component: a real cluster: Postgres in the cluster with backups, ingress with TLS for each public address, replicas | `../compose/server.yml` |

Settings and secrets don't live here. `scripts/render.py` writes `generated/<env>/kustomization.yaml`
from `base/`, the environment's layer components, each module's `k8s/` and `site/k8s/<env>/`, and
gives each service a ConfigMap from the same `env/<service>.env` Compose reads, and a Secret.

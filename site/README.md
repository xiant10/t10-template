# site/

This project's own choices, applied after `foundation/` and `modules/`, so anything here
overrides them. It's the only place a project changes the foundation's settings: everything
outside `site/` and `modules/` comes from the template and is never edited here.

| Path | What it holds |
|------|---------------|
| `config/settings.env` | `PROJECT_NAME`, and any setting for every environment |
| `config/<env>/settings.env` | One environment: its public addresses, `DEPLOY_HOST`, `DEPLOY_DIR` and `LIVEKIT_NODE_IP` on a server, or ports on local. An environment other than local, dev and prod (such as `uat`) also sets `SHAPE` here |
| `config/<service>.env`, `config/<env>/<service>.env` | A foundation or module service's settings, over the defaults in `foundation/config/` or `modules/<id>/config/` |
| `secrets/` | The secret values, one file per environment, and the only place they're read from (`secrets/README.md`) |
| `secrets.json` | Secrets this project adds, if any, in the same format as `foundation/secrets.json` |
| `versions.env` | Optional: a pin this project needs to differ from `foundation/versions.env` or a module's, as a deliberate exception |
| `docs/` | This project's own plan, decisions and open questions; how the template works is in `../docs/` |
| `k8s/<env>/` | Kubernetes patches for one environment: replicas, resources, ingress class. Never settings |
| `compose/<env>.yml` | Rarely: Compose changes for this project only, layered after the others |

`make config-show SVC=<service>` shows which layer each value comes from.

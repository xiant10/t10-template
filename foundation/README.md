# Foundation

The t10 foundation as any project runs it: published images (pinned in `versions.env`, the set the template is tested with)
and their configuration. Part of the template: nothing here names a module or a project, and a
project never edits it. Modules add to it from `../modules/<id>/`, and a project overrides its
settings from `../site/`, which is also where every `TODO` in `config/prod/` gets its value.

| Path | Holds |
| --- | --- |
| `compose/base.yml` | Every foundation service, the same set as t10-quickstart's `compose.all.yml`, images only. Wiring in `environment:`, settings in `config/`. Nothing that differs by environment |
| `compose/local.yml` | `local`: every service published on 127.0.0.1, LiveKit in dev mode |
| `compose/server.yml` | `dev` and `prod`: Caddy in front with TLS (its sites from `public.json` and each module), LiveKit for real; nothing else published |
| `k8s/` | The same on Kubernetes: `vendor/`, `base/`, and a component per layer, `local/` and `server/`. A skeleton until phase E of `../docs/plan.md`; see `k8s/README.md` |
| `public.json` | The foundation's public addresses: the setting that holds each, and the service and port behind it |
| `compose/scripted.yml`, `scripted/fake-model.mjs` | `SCRIPTED=1`: a scripted model in place of the provider, so nothing needs `LLM_API_KEY` |
| `init-db.sh` | One database per foundation service, on a new Postgres volume |
| `clients.json` | OAuth clients and runtimes, before modules add theirs. `scripts/render.py` merges it into auth-server's `clients.yaml` |
| `agent-routes.json` | Agents and pools, before modules add theirs. Rendered and published to t10-agent-control |
| `permissions/` | Foundation permission catalogs to deploy. None yet |
| `secrets.json` | Every secret the foundation's services use: who uses it, how to make it, how to rotate it. Never values |
| `config/<service>.env` | A service's settings in every environment |
| `config/<service>/` | Config files mounted into it, such as `ai-gateway-llm/config.yaml` |
| `config/settings.env` | `TARGET=compose`, for every environment |
| `config/local/settings.env` | Default ports and addresses on this machine |
| `config/server/settings.env` | What every server must decide, as `TODO`: addresses, the deploy host, LiveKit's public IP |
| `config/<layer>/<service>.env` | A service's settings in some environments, over `config/<service>.env`: `local/auth-server.env` turns on dev mode, `server/auth-server.env` trusts Caddy's forwarded headers |

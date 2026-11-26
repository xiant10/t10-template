# t10-template

A starting point for a project that runs business modules on the t10 foundation, using only the foundation's published images. A project made from it adds its modules in `modules/` and its own choices in `site/`; everything else comes from the template, so template updates merge cleanly.

## What it's for

The t10 foundation already does the hard, shared parts: sign-in and tenants (auth-server), agents and their routing (t10-agent-control, agent-ti, agent-pi), the AI gateway every turn, model call and tool call goes through, collaboration, knowledge, the workbench, voice and automations. A business needs its own logic on top of that, such as a CRM or property management, and needs its agents to use it.

This template is how a project gets there without forking or patching the foundation:

- **The foundation, as images and configuration.** Every foundation service runs from a published image: its `latest` on a laptop, and on a server the tag and digest the template tested. A project picks which components run and adjusts each container's settings in `site/`; it never changes foundation code. Upgrading a server's foundation means changing a version file.
- **Custom logic, as modules.** A module is the project's own code: a service with its data, the tools its agents call, its agent and its web app. `make new-module` writes a working one in `modules/<id>/` to build on; the template wires it into the foundation (accounts, permissions, grants, OAuth clients, database, routes, secrets), so a module holds only its own logic.
- **Modules agents can use.** Each module's tools are reached through `ai-gateway-tools`, with the permissions its catalog grants its agent, so the foundation's agents and the module's own agent act on the business data safely and on behalf of a signed-in person.
- **Proven in steps.** A module is tested alone, with a stand-in for auth-server, before it meets the foundation, then with the whole stack, then on a server ([`platform/docs/integration.md`](platform/docs/integration.md)). `make verify` runs the first three gates and CI runs it on every push.
- **Local to server, one description.** The same files run the whole stack on a laptop with `make up`, and on a server with `make deploy ENV=<env>` (Docker Compose over SSH), with encrypted secrets, backups, log rotation and memory limits. `make up ENV=k8s-local` runs the same stack on this machine's Kubernetes, made from the same files; a server cluster is planned ([`platform/docs/plan.md`](platform/docs/plan.md)).
- **A template that keeps giving.** A project owns `README.md`, `modules/`, `site/` and its CI, `.github/workflows/ci.yml`. Everything else lives in `platform/` (and the root `Makefile`), so `make template-update` brings in its fixes and features without touching the project's work.

```
 t10 foundation (published images)        this template (platform/)      your project
 ─────────────────────────────────        ─────────────────────────      ──────────────────────────
 auth-server, agents, ai-gateway,   ──▶   wiring, layering, secrets, ──▶ modules/  each module's code & deployment
 collab, knowledge, workbench, ...        kit, gates, deploy, updates    site/     settings, secrets, overrides
```

Who it's for: developers building a project's modules, and the coding agents working with them. Every task is a `make` target with a check after it (`make help` lists them), and the docs say what to run and what passing looks like.

## Project structure

A project is split between `platform/` (which the **template** owns and `make template-update` updates), the paths the **project** owns (`lib.OWNED`: `README.md`, `modules/`, `site/` and `.github/workflows/ci.yml`), and the rendered runtime bundle in `generated/` (never committed):

```text
<project>/
├── README.md                        the project: what it is and how to run it                  project
├── Makefile                         every command (`make help`); includes site/project.mk      template
├── .github/workflows/               t10-template.yml: the checks (template); ci.yml: calls them  project
├── platform/                        the template engine, foundation and SDK                    template
│   ├── CHANGELOG.md                 template releases and migration notes
│   ├── foundation/                  the t10 foundation from published images
│   │   ├── versions.env             foundation images (latest, for local) and third-party tags@digests
│   │   ├── compose/                 base.yml (core), local.yml, server.yml, scripted.yml
│   │   ├── config/                  default service settings (<service>.env) and layers; server/versions.env pins
│   │   ├── components/<name>/       optional foundation pieces (assistant, livekit, console, automations)
│   │   └── …                        clients.json, agent-routes.json, permissions/, secrets.json, init-db.sh
│   ├── scripts/                     rendering, wiring, checks, secrets, k8s, deploy, scaffolds
│   │   ├── render.py                compiles parts and layers into generated/<env>/
│   │   ├── wiring.py                synthesizes each module's Compose wiring, secrets and OAuth clients
│   │   ├── kube.py                  turns the resolved Compose bundle into Kubernetes objects
│   │   └── scaffold/<lang>/         starter module code for `make new-module` (go)
│   ├── tests/                       the template's own test suite (`make test-template`)
│   └── docs/                        architecture, guides and upstream tracker
├── modules/<id>/                    one business module: its code, pack and deployment         project
│   ├── source.env, versions.env     where its code is (`SRC=src`), and its pinned server image (`T10_<ID>`)
│   ├── config/                      service settings and per-layer ports/URLs (local, k8s-local, server)
│   ├── src/                         its service's code, tests, Dockerfile and pack (or cloned repo):
│   │   ├── main.go, server.go, tools.go, server_test.go, Dockerfile
│   │   └── module/                  the module pack (/module in its image):
│   │       ├── module.env           capabilities (web, tools, agent, database), agents, services
│   │       ├── permissions/         <id>.yaml catalog and the `agent` block naming tool actions
│   │       ├── agents/<agent>/      agent.json and instructions for agent-ti
│   │       └── …                    optional secrets.json, init-db.sh, hooks/, clients.fragment.json
│   └── …                            optional compose/, secrets.json, init-db.sh, hooks/, module.mk, pack/
├── site/                            this project's choices, layered last                       project
│   ├── config/                      settings.env (PROJECT_NAME, FOUNDATION), <env>/settings.env, overrides
│   ├── secrets/                     local.env (untracked) and SOPS+age <env>.enc.env (committed)
│   └── …                            optional versions.env, clients.json, permissions/, hooks/, project.mk
└── generated/<env>/                 the self-contained bundle that Compose and k8s run         untracked
```

### How the pieces fit together

1. **Parts (`platform/foundation/` $\rightarrow$ `components/` $\rightarrow$ `modules/<id>/` $\rightarrow$ `site/`).** Every part has the same shape and contributes settings, Compose files, secrets, OAuth clients, permission catalogs, agent routes and lifecycle hooks in order, later parts winning. `site/` is always last, so a project can override any foundation or module setting without editing template files.
2. **Co-located module + synthesized wiring (`modules/<id>/` + `platform/scripts/wiring.py`).** Each module keeps its deployment config in `modules/<id>/` and its code and pack in `modules/<id>/src/`. Its `module.env` declares what it has (`CAPABILITIES=web,tools,agent,database`, `AGENTS`, `SERVICES`) and `permissions/<id>.yaml` declares what actions its tools need once. From those, `platform/scripts/wiring.py` generates its standard database and auth-server seed jobs, service wiring, secrets, OAuth web client, agent runtimes, tool grants and scripted-model wiring.
3. **Environment layers (`base` $\rightarrow$ `local` or `server` $\rightarrow$ `<env>`).** Inside each part, configuration is layered by environment shape (`local` for a laptop or `k8s-local`, `server` plus `dev` or `prod` for remote hosts, or custom `LAYERS` such as `staging`).
4. **The rendered bundle (`generated/<env>/`).** Before any runtime command runs, `platform/scripts/render.py` merges all active parts and layers into `generated/<env>/`—producing one `env/<service>.env` and `secrets/<service>.env` per service, merged `clients.yaml`, `agent-routes.json`, `Caddyfile` (for servers), and `kustomization.yaml` + `k8s/*.yaml` (when `TARGET=k8s`). Nothing outside `generated/<env>/` is mounted at runtime, so the exact same bundle runs locally, on a remote Docker Compose host over SSH, or on Kubernetes.

| Read | For |
| --- | --- |
| [`platform/docs/new-project.md`](platform/docs/new-project.md) | Starting a project, step by step, from cloning to a first deploy |
| [`platform/docs/module.md`](platform/docs/module.md) | Building a module: what it provides, where its parts live, the loop while you work |
| [`platform/docs/integration.md`](platform/docs/integration.md) | The gates a module passes to join a project, alone first, then with the foundation |
| [`platform/docs/guide.md`](platform/docs/guide.md) | The reference: who owns what, the layout, commands, settings, secrets, the bundle |
| [`platform/docs/template-updates.md`](platform/docs/template-updates.md) | Keeping a project's own changes while taking the template's updates, and releasing them |
| [`platform/CHANGELOG.md`](platform/CHANGELOG.md) | The template's releases, and what a project does for each |
| [`platform/docs/design.md`](platform/docs/design.md), [`platform/docs/plan.md`](platform/docs/plan.md), [`platform/docs/upstream.md`](platform/docs/upstream.md) | Why it's built this way, what's left to build, and what the foundation should take back |

## Start a project

The whole walk-through, from cloning to a first deploy, is [`platform/docs/new-project.md`](platform/docs/new-project.md). In short:

1. Clone it with the template as a remote named `template`, and give the project its own `origin`:
   ```sh
   git clone -o template https://github.com/xiant10/t10-template.git myproject
   cd myproject && git remote add origin <your project's repo>
   ```
   Set `PROJECT_NAME` and pick the foundation components in `site/config/settings.env`, and replace this README with your project's.
2. Add each module: `make new-module ID=<id>` writes a working service in `modules/<id>/src/` to build on, and `make test`, `make up` and `make smoke` check it. [`platform/docs/module.md`](platform/docs/module.md) is how to build one.
3. Note your project's plan and open questions in `site/docs/plan.md`.
4. Later, `make template-update` merges the template's latest release and prints what it asks of the project. Your `README.md`, `modules/` and `site/` stay as they are; everything else comes from the template, so change it there, not in the project. `make check` warns about any template file edited in the project.

## Run it

You need Docker with Compose 2.24 or later, and Python 3. With no module, it runs the foundation alone.

```sh
make doctor                         # Docker, Compose, Python, free ports
make up                             # latest foundation images; local secrets are made in site/secrets/local.env
make seed-demo                      # sample accounts
make smoke                          # end-to-end checks
```

`make up` leaves `LLM_API_KEY` empty in `site/secrets/local.env` for an OpenAI-compatible key; until it's set, every local command uses a scripted model.

| Address | What |
| --- | --- |
| <http://127.0.0.1:38083> | Workbench |
| <http://127.0.0.1:38020> | Platform console |
| <http://127.0.0.1:38081> | auth-server, the issuer |

It runs the whole foundation, the same services as t10-quickstart's `compose.all.yml`, with every conversation, model call and tool call going through `ai-gateway`.

Sign in as `admin@acme.example`, with `AUTH_ADMIN_PASSWORD` from `site/secrets/local.env`. After `make seed-demo`, sample users are in tenant `ten_sample-acme` with password `t10-sample-password`.

The ports are 38xxx and 37xxx, so this runs beside t10-quickstart. Override them in `site/config/local/settings.env`.

On a server, it's `make release`, `make check ENV=<env>`, `make deploy ENV=<env>` and `make smoke ENV=<env>`; [Running a server](platform/docs/guide.md#running-a-server) covers the host, secrets, backups and day-to-day commands.

## License

Licensed under the [Apache License, Version 2.0](LICENSE). A project made from the template keeps the template's files under it; its own `modules/` and `site/` are licensed as the project chooses. Code `make new-module` writes into `modules/<id>/src/` comes from the template's `platform/scripts/scaffold/`, under the same license; the kit's `verifier/` comes from auth-server, also Apache 2.0.

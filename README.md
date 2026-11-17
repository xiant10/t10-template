# t10-template

A starting point for a project that runs business modules on the t10 foundation, using only the foundation's published images. A project made from it adds its modules in `modules/` and its own choices in `site/`; everything else comes from the template, so template updates merge cleanly.

## What it's for

The t10 foundation already does the hard, shared parts: sign-in and tenants (auth-server), agents and their routing (t10-agent-control, agent-ti, agent-pi), the AI gateway every turn, model call and tool call goes through, collaboration, knowledge, the workbench, voice and automations. A business needs its own logic on top of that, such as a CRM or property management, and needs its agents to use it.

This template is how a project gets there without forking or patching the foundation:

- **The foundation, as images and configuration.** Every foundation service runs from a pinned, published image. A project picks which components run and adjusts each container's settings in `site/`; it never changes foundation code. Upgrading the foundation means changing a version file.
- **Custom logic, as modules.** A module is the project's own code: a service with its data, the tools its agents call, its agent and its web app. `make new-module` writes a working one to build on; the template wires it into the foundation (accounts, permissions, grants, OAuth clients, database, routes, secrets), so a module holds only its own logic.
- **Modules agents can use.** Each module's tools are reached through `ai-gateway-tools`, with the permissions its catalog grants its agent, so the foundation's agents and the module's own agent act on the business data safely and on behalf of a signed-in person.
- **Proven in steps.** A module is tested alone, with a stand-in for auth-server, before it meets the foundation, then with the whole stack, then on a server ([`docs/integration.md`](docs/integration.md)). `make verify` runs the first three gates and CI runs it on every push.
- **Local to server, one description.** The same files run the whole stack on a laptop with `make up`, and on a server with `make deploy ENV=<env>` (Docker Compose over SSH), with encrypted secrets, backups, log rotation and memory limits. Kubernetes is planned ([`docs/plan.md`](docs/plan.md)).
- **A template that keeps giving.** A project owns only `README.md`, `modules/`, `site/` and `src/`. Everything else is the template's, so `make template-update` brings in its fixes and features without touching the project's work.

```
 t10 foundation (published images)        this template                  your project
 ─────────────────────────────────        ─────────────────────────      ──────────────────────────
 auth-server, agents, ai-gateway,   ──▶   wiring, layering, secrets, ──▶ modules/  each module's deployment
 collab, knowledge, workbench, ...        gates, deploy, updates         src/      each module's code
                                                                         site/     settings, secrets, overrides
```

Who it's for: developers building a project's modules, and the coding agents working with them. Every task is a `make` target with a check after it (`make help` lists them), and the docs say what to run and what passing looks like.

| Read | For |
| --- | --- |
| [`docs/new-project.md`](docs/new-project.md) | Starting a project, step by step, from cloning to a first deploy |
| [`docs/module.md`](docs/module.md) | Building a module: what it provides, where its parts live, the loop while you work |
| [`docs/integration.md`](docs/integration.md) | The gates a module passes to join a project, alone first, then with the foundation |
| [`docs/guide.md`](docs/guide.md) | The reference: who owns what, the layout, commands, settings, secrets, the bundle |
| [`docs/template-updates.md`](docs/template-updates.md) | Keeping a project's own changes while taking the template's updates, and releasing them |
| [`CHANGELOG.md`](CHANGELOG.md) | The template's releases, and what a project does for each |
| [`docs/design.md`](docs/design.md), [`docs/plan.md`](docs/plan.md), [`docs/upstream.md`](docs/upstream.md) | Why it's built this way, what's left to build, and what the foundation should take back |

## Start a project

The whole walk-through, from cloning to a first deploy, is [`docs/new-project.md`](docs/new-project.md). In short:

1. Clone it with the template as a remote named `template`, and give the project its own `origin`:
   ```sh
   git clone -o template https://github.com/xiant10/t10-template.git myproject
   cd myproject && git remote add origin <your project's repo>
   ```
   Set `PROJECT_NAME` and pick the foundation components in `site/config/settings.env`, and replace this README with your project's.
2. Add each module: `make new-module ID=<id>` writes a working service in `src/<id>/` to build on, and `make test`, `make up` and `make smoke` check it. [`docs/module.md`](docs/module.md) is how to build one.
3. Note your project's plan and open questions in `site/docs/plan.md`.
4. Later, `make template-update` merges the template's latest release and prints what it asks of the project. Your `README.md`, `modules/`, `site/` and `src/` stay as they are; everything else comes from the template, so change it there, not in the project. `make check` warns about any template file edited in the project.

## Run it

You need Docker with Compose 2.24 or later, and Python 3. With no module, it runs the foundation alone.

```sh
make doctor                         # Docker, Compose, Python, free ports
make up                             # pinned images; local secrets are made in site/secrets/local.env
make seed-demo                      # sample accounts
make smoke                          # end-to-end checks
```

`make up` leaves `LLM_API_KEY` empty in `site/secrets/local.env` for an OpenAI-compatible key; until it's set, every local command uses a scripted model.

| Address | What |
| --- | --- |
| <http://127.0.0.1:38083> | Workbench |
| <http://127.0.0.1:38020> | Platform console |
| <http://localhost:38081> | auth-server, the issuer |

It runs the whole foundation, the same services as t10-quickstart's `compose.all.yml`, with every conversation, model call and tool call going through `ai-gateway`.

Sign in as `admin@acme.example`, with `AUTH_ADMIN_PASSWORD` from `site/secrets/local.env`. After `make seed-demo`, sample users are in tenant `ten_sample-acme` with password `t10-sample-password`.

The ports are 38xxx and 37xxx, so this runs beside t10-quickstart. Override them in `site/config/local/settings.env`.

On a server, it's `make release`, `make check ENV=<env>`, `make deploy ENV=<env>` and `make smoke ENV=<env>`; [Running a server](docs/guide.md#running-a-server) covers the host, secrets, backups and day-to-day commands.

## License

Licensed under the [Apache License, Version 2.0](LICENSE). A project made from the template keeps the template's files under it; its own `modules/`, `site/` and `src/` are licensed as the project chooses. Code `make new-module` writes into `src/` comes from the template's `scripts/scaffold/`, under the same license; the kit's `verifier/` comes from auth-server, also Apache 2.0.

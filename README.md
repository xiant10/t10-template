# t10-template

A starting point for a project that runs business modules on the t10 foundation, using only the foundation's published images. A project made from it adds its modules in `modules/` and its own choices in `site/`; everything else comes from the template, so template updates merge cleanly.

How to start a project from it is in [`docs/new-project.md`](docs/new-project.md), how to work in it in [`docs/guide.md`](docs/guide.md), why it's laid out this way in [`docs/design.md`](docs/design.md), what a module provides in [`docs/module.md`](docs/module.md), what's left to build in [`docs/plan.md`](docs/plan.md), and what the foundation should take back in [`docs/upstream.md`](docs/upstream.md).

## Start a project

The whole walk-through, from cloning to a first deploy, is [`docs/new-project.md`](docs/new-project.md). In short:

1. Clone it with the template as a remote named `template`, and give the project its own `origin`:
   ```sh
   git clone -o template https://github.com/xiant10/t10-template.git myproject
   cd myproject && git remote add origin <your project's repo>
   ```
   Set `PROJECT_NAME` and pick the foundation components in `site/config/settings.env`, and replace this README with your project's.
2. Add each module: `make new-module ID=<id> SERVICE=<service> PORT=<port> REPO=<url>`, then follow [`docs/module.md`](docs/module.md).
3. Note your project's plan and open questions in `site/docs/plan.md`.
4. Later, `make template-update` merges the template's changes. Your `README.md`, `modules/` and `site/` stay as they are; everything else comes from the template, so change it there, not in the project. `make check` warns about any template file edited in the project.

## Run it

You need Docker with Compose 2.24 or later, and Python 3. With no module, it runs the foundation alone.

```sh
make up                             # pinned images; local secrets are made in site/secrets/local.env
make seed-demo                      # sample accounts
make smoke                          # end-to-end checks
```

`make up` leaves `LLM_API_KEY` empty in `site/secrets/local.env` for an OpenAI-compatible key; with none, prefix each command with `SCRIPTED=1` to use a scripted model.

| Address | What |
| --- | --- |
| <http://127.0.0.1:38083> | Workbench |
| <http://127.0.0.1:38020> | Platform console |
| <http://localhost:38081> | auth-server, the issuer |

It runs the whole foundation, the same services as t10-quickstart's `compose.all.yml`, with every conversation, model call and tool call going through `ai-gateway`.

Sign in as `admin@acme.example`, with `AUTH_ADMIN_PASSWORD` from `site/secrets/local.env`. After `make seed-demo`, sample users are in tenant `ten_sample-acme` with password `t10-sample-password`.

The ports are 38xxx and 37xxx, so this runs beside t10-quickstart. Override them in `site/config/local/settings.env`.

## License

Licensed under the [Apache License, Version 2.0](LICENSE). A project made from the template keeps the template's files under it; its own `modules/` and `site/` are licensed as the project chooses.

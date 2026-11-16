# Starting a new project

Step by step, from an empty folder to a project that runs its own modules locally and deploys to a server. Day-to-day work is in [`guide.md`](guide.md); what a module must provide, and how to work on one, is in [`module.md`](module.md).

A project is this template plus four things of its own: `src/` (each module's code), `modules/` (each module's deployment), `site/` (its name, components, addresses, secrets and overrides) and its `README.md`. You never edit anything else, so template updates merge cleanly.

## 1. Before you start

- Docker with Compose 2.24 or later, Python 3 and git. Nothing else: modules build and test inside Docker.
- Read access to `xiant10/t10-template` (it's private), and to any module's repo or image the project uses from elsewhere.
- For a server later: an SSH login to the host, which needs Docker, rsync and `docker login ghcr.io`.

## 2. Make the project

```sh
git clone -o template https://github.com/xiant10/t10-template.git myproject
cd myproject
git remote add origin <your project's repo>
git push -u origin main
```

The template stays a remote named `template`, which `make template-update` merges from later. Don't fork it on GitHub and don't copy the files without git: either loses the shared history the updates rely on.

## 3. Name it and choose what runs

Edit `site/config/settings.env`:

```sh
PROJECT_NAME=myproject                           # prefixes containers, volumes and networks
FOUNDATION=assistant,livekit,console,automations # drop the components you don't need
```

What each component does, and what goes missing without it, is in [`foundation/components/README.md`](../foundation/components/README.md). `FOUNDATION=` with nothing runs the core alone.

Then make the project's own files its own:

- Replace `README.md` with what this project is and how to reach it.
- Write down its plan and open questions in `site/docs/plan.md`.

Commit these as the project's first commit.

## 4. Run the foundation alone

Before adding any module, check that the foundation runs on your machine:

```sh
make doctor                 # Docker, Compose, Python, free ports
make up                     # with no LLM_API_KEY yet, a scripted model
make seed-demo              # sample tenant and users
make check
make smoke
```

`make up` writes random local secrets to `site/secrets/local.env`, which is never committed. Open <http://127.0.0.1:38083> (workbench) and sign in as `admin@acme.example`, with `AUTH_ADMIN_PASSWORD` from that file. All addresses are in the [README](../README.md#run-it).

The local ports are the template's (38xxx, 37xxx), so two projects made from it clash. Run one at a time (`make down` in the other), or move this one's ports in `site/config/local/settings.env`.

To use a real model, paste an OpenAI-compatible key as `LLM_API_KEY` in `site/secrets/local.env`: until then every local command uses the scripted model, and `make up` says so. To use another provider or model, override `OPENAI_BASE_URL`, `SMART_MODEL_NAME` and `FAST_MODEL_NAME` in `site/config/ai-gateway-llm.env`.

## 5. Build and add a module

A module is the business part of the project: a service with its own database, web app, tools and agent. Its code goes in `src/`, in this project's repo, unless several projects share it (then see [`module.md`](module.md#a-module-in-its-own-repo)).

```sh
make new-module ID=crm            # service t10-crm, on the next free port
make test MODULE=crm              # its tests, in Docker
make up                           # builds it from src/crm/ and runs it with the foundation
make smoke                        # checks it end to end, including a turn with its agent
```

That gives two folders, both the project's:

| Folder | Holds |
| --- | --- |
| `src/crm/` | Its code: a small working Go service, its tests, its Dockerfile, and its pack in `module/` (permissions, agent, OAuth clients, `module.env`) |
| `modules/crm/` | Its deployment: its settings, its address and port, its image pin. Its wiring into the foundation, database and standard secrets come from the template |

The service already does what every module must ([`module.md`](module.md#its-service)), through the template's Go kit: readiness, its manifest for workbench, a person's access, and its tools at `/mcp` for agents, with tokens checked against auth-server. What you build is the module itself:

| What | Where |
| --- | --- |
| Its agent tools | `src/<id>/tools.go`, replacing the example `<id>_whoami` |
| Its API and web app | `src/<id>/server.go` and files beside it |
| Its data | Migrations in its code, against the database it's given |
| Its permissions and roles | `src/<id>/module/permissions/<id>.yaml` |
| Its agent's instructions | `src/<id>/module/agents/<id>/base.md` |
| Its settings, and secrets beyond the standard ones | `modules/<id>/config/` and `modules/<id>/secrets.json` |
| Its demo data, extra checks | `modules/<id>/hooks/seed-demo.sh`, `hooks/smoke.py` |

The loop while you work:

```sh
make test MODULE=crm              # after each change: seconds once Docker's caches are warm
make reload MODULE=crm            # rebuild and restart it, and what reads its pack if that changed
make smoke
```

A tool needing a new action has it in one place, the `agent` block of its catalog; the project gives it to every place that needs it. Commit `src/` and `modules/` together: one commit is one change to the module.

## 6. Change a setting

Never edit `foundation/` or a Compose file. Put the value in `site/`:

| For | File |
| --- | --- |
| One service, every environment | `site/config/<service>.env` |
| One service, one environment | `site/config/<env>/<service>.env` |
| Ports, public addresses, deploy host | `site/config/<env>/settings.env` |
| A different image than the template pins | `site/versions.env`, as a deliberate exception |

`make config-show SVC=<service>` shows each value and the file it came from. Secrets never go among settings; `make check` refuses them.

## 7. Test before you report it done

The full check, from empty volumes:

```sh
make verify                 # test, down-all, up, seed-demo, check, smoke
```

`make test` and `make check` need no running stack and are quick enough to run after every change. `make smoke` checks the running stack end to end: each module's contract, a turn with its agent, its tool call through the gateway, and its hooks.

## 8. Deploy to a server

For `dev` (the same for `prod`):

1. Publish each module built from `src/`: set `IMAGE_REGISTRY` (such as `ghcr.io/<owner>`) in `site/config/settings.env`, `docker login` to it, commit, then `make release MODULE=<id>` and commit the pin it writes in `modules/<id>/versions.env`. Servers pull that image; they never build.
2. In `site/config/dev/settings.env`, set `DEPLOY_HOST`, `DEPLOY_DIR`, every public address (`AUTH_PUBLIC_URL`, `WORKBENCH_PUBLIC_URL`, each module's, the components') and `LIVEKIT_NODE_IP` if LiveKit runs. Point each address's DNS at the host.
3. `make secrets-init ENV=dev`, then fill in the empty values in `site/secrets/dev.env`, such as `LLM_API_KEY`. Until SOPS is built ([`plan.md`](plan.md), C2), that file is plain text and never committed, so keep a safe copy of it.
4. `make check ENV=dev` fails while any `TODO` is left, or a module's pinned image is older than its code in `src/`.
5. `make deploy ENV=dev` copies the bundle to the host and starts it behind Caddy, with TLS.
6. `make smoke ENV=dev` checks the public addresses.

Another environment, such as `uat`, needs only `site/config/uat/settings.env` with `SHAPE=prod` (or `dev`) and its own values.

## 9. Keep up with the template

```sh
make template-update      # the latest release; README.md, modules/, site/ and src/ stay as they are
make check                # warns about any template file this project edited
```

It prints what [`CHANGELOG.md`](../CHANGELOG.md) says about each release it brought in: do what its **In a project** notes say, then the full check in step 7. A conflict means the project edited a template file: move that change into `site/`, or propose it to the template.

To move to newer foundation images, `make pin` shows what's new and `make pin WRITE=1` writes it. Prefer taking new pins through a template update, since the template's set is tested together.

## What's committed

| Path | Committed |
| --- | --- |
| `README.md`, `modules/`, `site/`, `src/` | Yes, the project's own |
| Everything else in the repo | Yes, from the template; never edited here |
| `site/secrets/<env>.env` | Never. Only `<env>.enc.env`, once SOPS is built |
| `src/<repo>/` cloned by `make clone` | Never: a module's own repo, kept out of git |
| `generated/` | Never: the rendered bundle |

## Checklist

- [ ] Cloned with `-o template`, own `origin` added
- [ ] `PROJECT_NAME` and `FOUNDATION` set; `README.md` and `site/docs/plan.md` written
- [ ] The foundation alone passes `make check` and `make smoke`
- [ ] Each module: made with `make new-module`, its own tools and permissions, `make verify` passes
- [ ] Before a server: each module from `src/` released and its pin committed
- [ ] Each server environment: settings filled in, secrets made and kept safe, `make check ENV=…`, `make deploy ENV=…`, `make smoke ENV=…`

# Starting a new project

Step by step, from an empty folder to a project that runs its own modules locally and deploys to a server. Day-to-day work is in [`guide.md`](guide.md); what a module must provide, and how to work on one, is in [`module.md`](module.md).

A project is this template plus four things of its own: `modules/` (each module's code and deployment), `site/` (its name, components, addresses, secrets and overrides), its `README.md`, and its CI, `.github/workflows/ci.yml`. You never edit anything else, so template updates merge cleanly.

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

The template stays a remote named `template`, which `make template-update` merges from later; your work goes to `origin`. Don't fork it on GitHub and don't copy the files without git: either loses the shared history the updates rely on. How the two stay apart is [`template-updates.md`](template-updates.md).

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

`make up` writes random local secrets to `site/secrets/local.env`, which is never committed. Open <http://127.0.0.1:38083> (workbench) and sign in as `admin@acme.example`, with `AUTH_ADMIN_PASSWORD` from that file. All addresses are in the [README](../../README.md#run-it).

The local ports are the template's (38xxx, 37xxx), so two projects made from it clash. Run one at a time (`make down` in the other), or move all of this one's with one setting, `PORT_OFFSET=10000` in `site/config/settings.env` (48xxx, 47xxx; 20000 for a third project): every `*_PORT` and every `localhost` or `127.0.0.1` address the template and its modules set moves by it, on this machine only. A port you set yourself in `site/config/local/settings.env` is taken as it is. `make doctor` then checks the moved ports are free.

To use a real model, paste an OpenAI-compatible key as `LLM_API_KEY` in `site/secrets/local.env`: until then every local command uses the scripted model, and `make up` says so. To use another provider or model, override `OPENAI_BASE_URL`, `SMART_MODEL_NAME` and `FAST_MODEL_NAME` in `site/config/ai-gateway-llm.env`.

## 5. Build and add a module

A module is the business part of the project: a service with its own database, web app, tools and agent. Its code goes in `modules/<id>/src/`, in this project's repo, unless several projects share it (then see [`module.md`](module.md#a-module-in-its-own-repo)).

```sh
make new-module ID=crm            # service t10-crm, on the next free port
make test MODULE=crm              # its tests, in Docker
make up                           # builds it from modules/crm/src/ and runs it with the foundation
make smoke                        # checks it end to end, including a turn with its agent
```

That gives one folder, the project's, in two parts:

| Folder | Holds |
| --- | --- |
| `modules/crm/src/` | Its code: a small working Go service, its tests, its Dockerfile, and its pack in `module/` (permissions, agent, OAuth clients, `module.env`) |
| `modules/crm/` (the rest) | Its deployment: its settings, its address and port, its image pin. Its wiring into the foundation, database and standard secrets come from the template |

The service already does what every module must ([`module.md`](module.md#its-service)), through the template's Go kit: readiness, its manifest for workbench, a person's access, and its tools at `/mcp` for agents, with tokens checked against auth-server. What you build is the module itself:

| What | Where |
| --- | --- |
| Its agent tools | `modules/<id>/src/tools.go`, replacing the example `<id>_whoami` |
| Its API and web app | `modules/<id>/src/server.go` and files beside it |
| Its data | Migrations in its code, against the database it's given |
| Its permissions and roles | `modules/<id>/src/module/permissions/<id>.yaml` |
| Its agent's instructions | `modules/<id>/src/module/agents/<id>/base.md` |
| Its settings, and secrets beyond the standard ones | `modules/<id>/config/` and `modules/<id>/secrets.json` |
| Its demo data, extra checks | `modules/<id>/hooks/seed-demo.sh`, `hooks/smoke.py` |
| What it has: web app, tools, agents, database; more agents or a worker | `CAPABILITIES`, `AGENTS`, `SERVICES` in `modules/<id>/src/module/module.env` ([`module.md`](module.md#what-it-has)) |

The loop while you work:

```sh
make test MODULE=crm              # after each change: seconds once Docker's caches are warm
make reload MODULE=crm            # rebuild and restart it, and what reads its pack if that changed
make smoke
```

A tool needing a new action has it in one place, the `agent` block of its catalog; the project gives it to every place that needs it. Commit a module's `src/` and its deployment together: one commit is one change to the module.

## 6. Change a setting

Never edit `foundation/` or a Compose file. Put the value in `site/`:

| For | File |
| --- | --- |
| One service, every environment | `site/config/<service>.env` |
| One service, one environment | `site/config/<env>/<service>.env` |
| Ports, public addresses, deploy host | `site/config/<env>/settings.env` |
| A different image than the template pins | `site/versions.env`, as a deliberate exception |
| An OAuth client, catalog or agent route of its own, or a change to the foundation's | `site/clients.json`, `site/permissions/`, `site/agent-routes.json` ([`guide.md`](guide.md#what-a-part-adds)) |
| A step before or after a command; a command of its own | `site/hooks/<event>.sh` ([`guide.md`](guide.md#hooks)); `site/project.mk` |

`make config-show SVC=<service>` shows each value and the file it came from. Secrets never go among settings; `make check` refuses them.

## 7. Test before you report it done

The full check, from empty volumes:

```sh
make verify                 # test, down-all, up, seed-demo, check, smoke
```

`make test` and `make check` need no running stack and are quick enough to run after every change. `make smoke` checks the running stack end to end: each module's contract, a browser signing in to its web app, a turn with its agent, its tool call through the gateway, and its hooks.

When something you hit is the template's doing rather than the project's (a bug in `platform/`, a route nobody documented, a step every module will repeat), write it in `site/docs/template-findings.md` as you go, so the template's maintainers can take it back ([`template-updates.md`](template-updates.md#reporting-what-a-project-finds)). Don't fix it quietly in a template file.

## 8. Deploy to a server

For `dev` (the same for `prod`):

1. Publish each module built from `modules/<id>/src/`: set `IMAGE_REGISTRY` (such as `ghcr.io/<owner>`) in `site/config/settings.env`, `docker login` to it, commit, then `make release MODULE=<id>` and commit the pin it writes in `modules/<id>/versions.env`. Servers pull that image; they never build.
2. In `site/config/dev/settings.env`, set `DEPLOY_HOST`, `DEPLOY_DIR`, every public address (`AUTH_PUBLIC_URL`, `WORKBENCH_PUBLIC_URL`, each module's, the components') and `LIVEKIT_NODE_IP` if LiveKit runs. Point each address's DNS at the host.
3. Secrets, encrypted with SOPS and age ([`guide.md`](guide.md#secrets)):
   - once per project: `make secrets-key`, which makes this machine's age key and `site/secrets/.sops.yaml`, then `make secrets-key BREAKGLASS=1`, whose printed key you keep offline; back up `~/.config/sops/age/keys.txt` too;
   - `make secrets-init ENV=dev` makes every generated value, the signing key included, in `site/secrets/dev.enc.env`;
   - `make secrets-set ENV=dev NAME=LLM_API_KEY` for each value it says to fill in;
   - commit `site/secrets/.sops.yaml` and `dev.enc.env`. A teammate who deploys runs `make secrets-key` on their machine, and you add them with `make secrets-key RECIPIENT=age1…`.
4. `make check ENV=dev` fails while any `TODO` is left, or a module's pinned image is older than its code in `modules/<id>/src/`.
5. `make deploy ENV=dev` copies the bundle to the host and starts it behind Caddy, with TLS.
6. `make smoke ENV=dev` checks the public addresses.
7. Backups run on the host every day. `make backup-pull ENV=dev` copies the newest here, encrypted; do it on a schedule, since the host's own copies go with the host. Restoring one is `make restore ENV=dev FILE=… CONFIRM=dev`. Running a server is in [`guide.md`](guide.md#running-a-server).

Another environment, such as `uat`, needs only `site/config/uat/settings.env` with `SHAPE=prod` (or `dev`) and its own values.

## 9. Keep up with the template

```sh
make template-update      # the latest release; README.md, modules/ and site/ stay as they are
make check                # warns about any template file this project edited
```

It prints what [`CHANGELOG.md`](../CHANGELOG.md) says about each release it brought in: do what its **In a project** notes say, then the full check in step 7. Conflicts, releasing a change from the template, and new foundation images are in [`template-updates.md`](template-updates.md).

## What's committed

| Path | Committed |
| --- | --- |
| `README.md`, `modules/`, `site/`, `.github/workflows/ci.yml` | Yes, the project's own |
| Everything else in the repo | Yes, from the template; never edited here |
| `site/secrets/<env>.env` | Never. Only `<env>.enc.env`, once SOPS is built |
| `modules/<id>/src/` cloned by `make clone` | Never: a module's own repo, kept out of git |
| `generated/` | Never: the rendered bundle |

## Checklist

- [ ] Cloned with `-o template`, own `origin` added
- [ ] `PROJECT_NAME` and `FOUNDATION` set; `README.md` and `site/docs/plan.md` written
- [ ] The foundation alone passes `make check` and `make smoke`
- [ ] Each module: made with `make new-module`, its own tools and permissions, `make verify` passes
- [ ] Before a server: each module from `modules/<id>/src/` released and its pin committed
- [ ] Each server environment: settings filled in, secrets made and kept safe, `make check ENV=…`, `make deploy ENV=…`, `make smoke ENV=…`

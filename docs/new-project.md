# Starting a new project

Step by step, from an empty folder to a project that runs its own modules locally and deploys to a server. Day-to-day work is in [`guide.md`](guide.md); what a module must provide is in [`module.md`](module.md).

A project is this template plus three things of its own: `modules/` (one folder per business module it runs), `site/` (its name, components, addresses, secrets and overrides) and its `README.md`. You never edit anything else, so template updates merge cleanly.

## 1. Before you start

- Docker with Compose 2.24 or later, Python 3 and git.
- Read access to `xiant10/t10-template` (it's private) and to each module's repo and image.
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
SCRIPTED=1 make up          # a scripted model, so no LLM_API_KEY is needed yet
make seed-demo              # sample tenant and users
SCRIPTED=1 make check
SCRIPTED=1 make smoke
```

`make up` writes random local secrets to `site/secrets/local.env`, which is never committed. Open <http://127.0.0.1:38083> (workbench) and sign in as `admin@acme.example`, with `AUTH_ADMIN_PASSWORD` from that file. All addresses are in the [README](../README.md#run-it).

The local ports are the template's (38xxx, 37xxx), so two projects made from it clash. Run one at a time (`make down` in the other), or move this one's ports in `site/config/local/settings.env`.

To use a real model, paste an OpenAI-compatible key as `LLM_API_KEY` in `site/secrets/local.env` and run without `SCRIPTED=1`. To use another provider or model, override `OPENAI_BASE_URL`, `SMART_MODEL_NAME` and `FAST_MODEL_NAME` in `site/config/ai-gateway-llm.env`.

## 5. Build and add a module

A module is the business part of the project: a service with its own database, web app, tools and agent. It lives in its own repo, and the project runs its published image. What you build in that repo:

| What | Where | Why |
| --- | --- | --- |
| The service | Its repo, any language | Answers `/readyz`, `/v1/module`, `/v1/access` and serves its tools at `/mcp` ([`module.md`](module.md#its-service)) |
| Its permission catalog | Shipped in the image at `/module/permissions/<id>.yaml` | auth-server loads it: the module's actions, roles and the `agent` block |
| Its agent | `/module/agents/<agent>/` in the image | agent-ti runs it; reached as `Agent-Name: <agent>` |
| Its OAuth clients and grants | `/module/clients.fragment.json` in the image | Merged into auth-server's clients |
| The facts a deployment needs | `/module/module.env` in the image | `MODULE_ID`, `SERVICE`, `PORT`, grants, agent, public URL setting |
| CI that publishes the image | Its repo | Tags `sha-<commit>`, which the project pins |

`t10-property`'s `module/` folder and Dockerfile are a worked example.

Then wire it into the project:

```sh
make new-module ID=crm SERVICE=t10-crm PORT=18076 REPO=https://github.com/xiant10/t10-crm.git
# pin its image in modules/crm/versions.env: T10_CRM=ghcr.io/xiant10/t10-crm:sha-<commit>@sha256:<digest>
make sync-module MODULE=crm       # copies the pack out of the image into modules/crm/pack/
grep -rn TODO modules/crm         # fill in each one
make up && make check && make smoke
```

The module's folder is only its deployment: its Compose service, settings, secrets inventory and a copy of its pack. Grants, tool server, agent route, workbench entry and clients reach the foundation from there, with nothing to edit anywhere else. Add what only this module needs by hand, such as demo data in `modules/crm/hooks/seed-demo.sh` or extra checks in `hooks/smoke.py`.

### Working on a module's code

```sh
make clone                        # each module's repo into src/, which the project doesn't commit
DEV=1 SCRIPTED=1 make up          # builds the modules from src/ instead of pulling their images
make status                       # changes in this repo and in each src/ repo
```

The pack still comes from `modules/<id>/pack/`, so after changing a module's catalog, agent or clients, build its image and copy the pack from it: `IMAGE=t10-crm:dev make sync-module MODULE=crm`. A change in both places is a commit in the module's repo, then one in the project that pins the new image and its pack.

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
make down-all && SCRIPTED=1 make up && make seed-demo && SCRIPTED=1 make check && SCRIPTED=1 make smoke
```

`make check` needs no running stack and is quick enough to run after every change. `make smoke` checks the running stack end to end, including each module's contract and its hooks.

## 8. Deploy to a server

For `dev` (the same for `prod`):

1. In `site/config/dev/settings.env`, set `DEPLOY_HOST`, `DEPLOY_DIR`, every public address (`AUTH_PUBLIC_URL`, `WORKBENCH_PUBLIC_URL`, each module's, the components') and `LIVEKIT_NODE_IP` if LiveKit runs. Point each address's DNS at the host.
2. `make secrets-init ENV=dev`, then fill in the empty values in `site/secrets/dev.env`, such as `LLM_API_KEY`. Until SOPS is built ([`plan.md`](plan.md), C2), that file is plain text and never committed, so keep a safe copy of it.
3. `make check ENV=dev` fails while any `TODO` is left.
4. `make deploy ENV=dev` copies the bundle to the host and starts it behind Caddy, with TLS.
5. `make smoke ENV=dev` checks the public addresses.

Another environment, such as `uat`, needs only `site/config/uat/settings.env` with `SHAPE=prod` (or `dev`) and its own values.

## 9. Keep up with the template

```sh
make template-update      # merges template/main; README.md, modules/ and site/ stay as they are
make check                # warns about any template file this project edited
```

Then the full check in step 7. A conflict means the project edited a template file: move that change into `site/`, or propose it to the template.

To move to newer foundation images, `make pin` shows what's new and `make pin WRITE=1` writes it. Prefer taking new pins through a template update, since the template's set is tested together.

## What's committed

| Path | Committed |
| --- | --- |
| `README.md`, `modules/`, `site/` | Yes, the project's own |
| Everything else in the repo | Yes, from the template; never edited here |
| `site/secrets/<env>.env` | Never. Only `<env>.enc.env`, once SOPS is built |
| `src/`, `generated/` | Never: module checkouts, and the rendered bundle |

## Checklist

- [ ] Cloned with `-o template`, own `origin` added
- [ ] `PROJECT_NAME` and `FOUNDATION` set; `README.md` and `site/docs/plan.md` written
- [ ] The foundation alone passes `make check` and `make smoke`
- [ ] Each module: image with a pack, pinned, `make sync-module`, no `TODO` left, passes the full check
- [ ] Each server environment: settings filled in, secrets made and kept safe, `make check ENV=…`, `make deploy ENV=…`, `make smoke ENV=…`

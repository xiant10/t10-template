# Integrating a module

The protocol a module follows to join a project: the gates it passes, in order, each runnable on its own, and what each one proves. A module is the project's custom logic (its service, tools, agent and web app); the foundation is what it plugs into. Building one is [`module.md`](module.md), and what it must provide is [the contract](module.md#its-service).

The rule: **a module is proven alone before it meets the foundation.** A failure found alone is about the module, in seconds, with nothing else running; a failure in the full stack can be anywhere. So each gate runs only once the one before it passes.

| Gate | Command | Needs | Proves |
| --- | --- | --- | --- |
| 1. Unit | `make test MODULE=<id>` | Docker only | Its own code: tools, API, data logic, with auth-server stood in for by `module.Fake` |
| 2. Alone | `make contract MODULE=<id>` | Docker only: the module and its own Postgres | It keeps the module contract by itself: its pack is a version this template reads and agrees with itself, and its service answers what every module must, with a person's and an agent's tokens, for the capabilities it has |
| 3. Integrated | `make up`, `make smoke` | The whole foundation | It plugs in: its accounts, grants, catalog, clients, agent and route work with the real auth-server, gateways and agent; its agent answers a turn whose tool call reaches it |
| 4. Server | `make release`, `make check ENV=<env>`, `make deploy`, `make smoke ENV=<env>` | A host | The released image is the code that passed, with the environment's real addresses and secrets |

`make verify` runs gates 1 to 3 in order, from empty volumes, for every module whose code is in the project; CI runs it on every push. Before calling a change to a module done, `make verify` passes.

## Gate 1: unit

`make test MODULE=<id>` builds the module's Dockerfile `test` stage: `go vet` and `go test`, with the image's own toolchain. Its tests use `module.Fake` for auth-server, so they need no stack. What every module answers is tested in the kit (`kit/go/module`); a module's tests cover its own tools and API.

## Gate 2: alone

```sh
make contract MODULE=crm          # starts it alone, checks it, stops it
make alone MODULE=crm             # or keep it running, to work against it: it prints its address
make alone-down MODULE=crm
```

`make alone` runs the module's service by itself as its own Compose project, with its own throwaway Postgres and database, built from `modules/<id>/src/`, on a port that is free when it starts (`make alone` prints its address, and `platform/scripts/alone.py <id> url` gives it again), so it runs beside the full stack and other projects. It gets its own settings from `modules/<id>/config/`, and `T10_STANDALONE=1` with no `AUTH_ISSUER`, which switches the kit to a stand-in for auth-server:

| Token | Is |
| --- | --- |
| `Bearer person` | A signed-in tenant admin, `usr_alone` in `ten_alone` |
| `Bearer agent` | An agent acting for them, holding exactly the actions the catalog's `agent` block grants |
| anything else | Refused |

So `curl -H 'Authorization: Bearer person' http://127.0.0.1:48100/v1/access` works against it, and so does a tool call with `Bearer agent`. Standalone mode refuses to start when `AUTH_ISSUER` is set, as it always is in the stack, so it can't be switched on there.

`make contract` (`scripts/contract.py`) then checks:

- **Its pack**, without running anything: `module.env` has every key (`PACK_VERSION`, one this template reads, and `CAPABILITIES` among them) and follows the names its ID sets; the catalog is the module's; with `tools`, its `agent` block names the module's actions and its service as the audience; with `agent`, each agent signs in as its runtime and reads its secret's variable, and its OAuth clients name each runtime; with `web`, its web client uses its public URL and web client secret; its Dockerfile ships the pack at `/module`.
- **Its service**, running alone: ready; `/v1/module` and `/v1/access` for a person, refused without a token and for an agent; with `tools`, its tools listed over MCP without a token, each named for the module, each callable by an agent holding only the catalog's actions, and refused without a token, for a person's own token, and from a page.

The commonest mistake it catches: a tool whose action isn't in the catalog's `agent` block. Its unit tests pass, but alone, as in the stack, the agent isn't granted it, and `make contract` names the tool and the fix.

## Gate 3: integrated

```sh
make up                           # builds it from src/ and runs it with the foundation
make smoke                        # every service, then each module's contract and agent with real tokens
```

What only the full stack can show: its accounts are made in auth-server, its grants reach the harnesses and runtimes, its catalog and clients load, its agent is routed and answers a turn, and that turn's tool call reaches the module through `ai-gateway-tools`. Then its own `hooks/smoke.py`, if it has one. While working, `make reload MODULE=<id>` rebuilds it and restarts what reads its pack.

## Gate 4: server

`make release MODULE=<id>` builds the image from `modules/<id>/src/` as committed, pushes it and pins it. `make check ENV=<env>` fails while the pin is behind it, a `TODO` is left, or a secret is missing or in plain text. Then `make deploy ENV=<env>` and `make smoke ENV=<env>`. The steps are in [`new-project.md`](new-project.md#8-deploy-to-a-server).

## A module in its own repo

The same gates, with gate 1 in its own repo's CI. Gate 2 runs from a project: `make clone` checks it out into `modules/<id>/src/`, and `make contract MODULE=<id>` builds and checks it from there, so a module can be proven against the contract before its image is published. A module that doesn't use the Go kit must answer `T10_STANDALONE=1` the same way (the tokens above, refused beside `AUTH_ISSUER`) for gate 2 to run. Gate 3 then pins its published image and copies its pack (`make sync-module`).

## When a gate fails

| Gate | Look at |
| --- | --- |
| 1 | The test output; the code in `modules/<id>/src/` |
| 2 | The failing line names the file or route. Its logs: `docker compose -p <PROJECT_NAME>-alone-<id> logs` while `make alone` runs it |
| 3 | `make logs SVC=<service>`; `make check` for grants and secrets; `make config-show SVC=<service>` for a setting |
| 4 | `make check ENV=<env>`; the host's logs through its bundle's `compose.sh logs` |

A failure at gate 3 that gate 2 should have caught is a gap in the contract check: add the check to `scripts/contract.py` in the template, so every module gets it.

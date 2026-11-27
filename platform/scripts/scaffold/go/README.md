# __Id__

The __id__ module's source: its service, `__service__`, and its pack. It lives in this project's
repo, and the project builds and runs it from here: its deployment is `modules/__id__/`.

| Path | Holds |
| --- | --- |
| `main.go` | Startup: settings from the environment, the database, its access checks, and the module |
| `server.go` | Its own routes beside the standard ones: the web app's page, and any API of its own |
| `ontology.go` | Its ontology: its records and what may be done to them, from which t10-modkit serves `/v1/ontology`, the object and action routes, and the `__id___describe`, `_search`, `_get` and `_propose` tools; replace the example notes with the module's own ([platform/docs/module.md](../../../platform/docs/module.md#model-its-ontology)) |
| `ontology.conformance.json` | The records and actions `make contract` runs the ontology conformance suite with |
| `tools.go` | Its own agent tools at `/mcp`, beside the generated ones; replace the example with the module's own |
| `server_test.go` | Tests of its own tools and routes, with `module.Fake` for auth-server: no stack needed |
| `go.mod` | Its dependencies, among them `github.com/xiant10/t10-modkit` at the template's pinned tag, `T10_MODKIT` |
| `module/` | The pack: `module.env`, its permission catalog, its agent, its OAuth clients, and `ontology.json`, its published core descriptor (`UPDATE_ONTOLOGY=1 go test` writes it) ([`platform/docs/module.md`](../../../platform/docs/module.md)) |
| `Dockerfile` | The image, with the pack at `/module`; its `test` stage runs vet and the tests |

What every module answers (`/readyz`, `/v1/module`, `/v1/access`, the MCP protocol, and checking
a person's or an agent's token against auth-server) comes from t10-modkit,
`github.com/xiant10/t10-modkit/module`, and its tests are there ([docs/api.md](https://github.com/xiant10/t10-modkit/blob/main/docs/api.md)).

From the project's root:

```sh
make test MODULE=__id__        # vet and tests, in Docker
make contract MODULE=__id__    # it alone, with its own Postgres: the module contract (platform/docs/integration.md)
make up                        # builds it from here and runs it with the foundation
make reload MODULE=__id__      # after a change: rebuild and restart it, and what reads its pack
make smoke                     # the whole stack end to end, including this module's hooks
```

A new tool's action goes in one place, including the generated tools' `__id__:read`, `__id__:propose` and, with an `undoable` action, `__id__:act`: the `agent` block of `module/permissions/__id__.yaml`:
the project gives it to the agent, its runtimes and the harnesses.

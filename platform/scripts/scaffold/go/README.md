# __Id__

The __id__ module's source: its service, `__service__`, and its pack. It lives in this project's
repo, and the project builds and runs it from here: its deployment is `modules/__id__/`.

| Path | Holds |
| --- | --- |
| `main.go` | Startup: settings from the environment, the database, its access checks, and the module |
| `server.go` | Its own routes beside the standard ones: the web app's page, and any API of its own |
| `tools.go` | Its agent tools at `/mcp`; replace the example with the module's own |
| `server_test.go` | Tests of its own tools and routes, with `module.Fake` for auth-server: no stack needed |
| `go.mod` | Its dependencies, and the template's kit as `../../../platform/kit/go` (the Dockerfile uses its `kit` build context instead) |
| `module/` | The pack: `module.env`, its permission catalog, its agent, its OAuth clients ([`platform/docs/module.md`](../../../platform/docs/module.md)) |
| `Dockerfile` | The image, with the pack at `/module`; its `test` stage runs vet and the tests |

What every module answers (`/readyz`, `/v1/module`, `/v1/access`, the MCP protocol, and checking
a person's or an agent's token against auth-server) comes from the template's kit,
`t10kit/module` in `platform/kit/go/`, and its tests are there.

From the project's root:

```sh
make test MODULE=__id__        # vet and tests, in Docker
make contract MODULE=__id__    # it alone, with its own Postgres: the module contract (platform/docs/integration.md)
make up                        # builds it from here and runs it with the foundation
make reload MODULE=__id__      # after a change: rebuild and restart it, and what reads its pack
make smoke                     # the whole stack end to end, including this module's hooks
```

A new tool's action goes in one place, the `agent` block of `module/permissions/__id__.yaml`:
the project gives it to the agent, its runtimes and the harnesses.

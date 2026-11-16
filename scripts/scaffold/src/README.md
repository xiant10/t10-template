# __Id__

The __id__ module's source: its service, `__service__`, and its pack. It lives in this project's
repo, and the project builds and runs it from here: its deployment is `modules/__id__/`.

| Path | Holds |
| --- | --- |
| `main.go` | Startup: settings from the environment, the database, the token verifier |
| `server.go` | `/readyz`, `/v1/module` (the manifest workbench reads), `/v1/access` and the web app's page |
| `auth.go` | Who a request is for: a person's own token, or an agent's delegated one, with their live standing |
| `mcp.go`, `tools.go` | The agent tools at `/mcp`; add the module's own in `tools.go` |
| `server_test.go` | Tests that need no running stack |
| `verifier/` | auth-server's token verifier, copied (upstream U16) |
| `module/` | The pack: `module.env`, its permission catalog, its agent, its OAuth clients ([`docs/module.md`](../../docs/module.md)) |
| `Dockerfile` | The image, with the pack at `/module`; its `test` stage runs vet and the tests |

From the project's root:

```sh
make test MODULE=__id__        # vet and tests, in Docker
make up                        # builds it from here and runs it with the foundation
make reload MODULE=__id__      # after a change: rebuild and restart it, and what reads its pack
make smoke                     # the whole stack end to end, including this module's hooks
```

A new tool needs an action its agent may use: add it to `GRANT_ACTIONS` in `module/module.env`,
the catalog's `agent` block, the agent's `grants` and the runtimes in `module/clients.fragment.json`.
`make check` names any place that's missing it.

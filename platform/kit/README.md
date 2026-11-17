# kit/

Code every module shares, imported rather than copied, so a fix reaches every module with
`make template-update`. Part of the template: a project never edits it.

| Path | Holds |
| --- | --- |
| `go/module/` | `t10kit/module`: what every module's service answers (`/readyz`, `/v1/module`, `/v1/access`, `/v1/me/nav`, `/v1/notifications`, its tools over MCP at `/mcp`), a person's and an agent's access checked against auth-server, `Fake` for tests, and its web app's sign-in, sign-out and pages in the frame (`PersonPage`, `View`, `Page`, `Styles`) |
| `go/frame/` | `t10kit/frame`: the rail, Apps list and account menu every server-drawn t10 page wears, copied from `t10-modkit@0efa4a6` (upstream U16) |
| `go/verifier/` | auth-server's token verifier, copied at `auth-server@95e9f9b` (upstream U16: imported from the foundation once it's published) |

A module's `go.mod` reaches it with `replace t10kit => ../../../platform/kit/go`; its Dockerfile copies the
build context `kit`, which Compose, `make test` and `make release` pass. `make test-template`
runs the kit's own tests (`go/Dockerfile`). How a module uses it is in `../docs/module.md`.

# Foundation components

The foundation's optional pieces. Each folder is a part shaped like `../` (the core) or a module:
any of `compose/`, `config/`, `secrets.json`, `public.json`, `clients.json` (in
the form of a module's `clients.fragment.json`), `agent-routes.json` (pools and agents to add),
and `part.env`, which can name components it needs in `REQUIRES` and add to the core's lists
(`WORKBENCH_URLS`), as any part's can (`../../docs/guide.md#what-a-part-adds`). Their images are pinned with the core's, in `../versions.env`.

| Component | Runs | Without it |
| --- | --- | --- |
| `assistant` | agent-pi, the general assistant and the picker's default agent | `ti` is the default agent |
| `livekit` | LiveKit and t10-livekit-agent, the voice worker, which speaks for agent-pi. Needs `assistant` | No calls. auth-server gets placeholder LiveKit values, since it requires them (upstream U15) |
| `console` | t10-console, the platform console, and its sign-in client | Platform admin only through `authctl` and `agentctl` |
| `automations` | t10-automations, its workbench page, and collab's link to it | No scheduled or triggered agent work |

The core, in `../compose/base.yml`, is what everything else needs: postgres, auth-server,
t10-agent-control, the three ai-gateway roles, t10-collab, t10-knowledge, agent-ti and workbench.

## Choosing them

`FOUNDATION` lists the components that run. The template's list, in
`../config/settings.env`, has all four; a project sets its own in `site/config/settings.env`:

```sh
FOUNDATION=assistant,livekit,console,automations    # the template's: everything
FOUNDATION=assistant,livekit                        # no console, no automations
FOUNDATION=                                         # the core alone
```

A component that isn't listed isn't a part, so its services, ports, settings (and their `TODO`s
on a server), secrets, public address, clients and routes all drop out. Its pins stay in
`../versions.env`, unused. Its secret values may stay in `site/secrets/`, so listing it again
reuses them. `make check` fails on a name that isn't a component, or a component listed without
one it needs. `make up` removes the containers of
a component that's no longer listed.

A component the template adds later reaches a project only once the project lists it.

Tested Nov 16: everything, and the core alone, each from empty volumes with `make up`,
`seed-demo`, `check` and `smoke`.

# Foundation components

The foundation's optional pieces. Each folder is a part shaped like `../` (the core) or a module:
any of `compose/`, `config/`, `versions.env`, `secrets.json`, `public.json`, `clients.json` (in
the form of a module's `clients.fragment.json`), `agent-routes.json` (pools and agents to add),
and `component.env`, which can name components it needs in `REQUIRES` and add to the core's lists
(`WORKBENCH_URLS`). Every component is on unless the project switches it off.

| Component | Runs | Without it |
| --- | --- | --- |
| `assistant` | agent-pi, the general assistant and the picker's default agent | `ti` is the default agent |
| `voice` | LiveKit and t10-livekit-agent, which speaks for agent-pi. Needs `assistant` | No calls. auth-server gets placeholder LiveKit values, since it requires them (upstream U15) |
| `console` | t10-console, the platform console, and its sign-in client | Platform admin only through `authctl` and `agentctl` |
| `automations` | t10-automations, its workbench page, and collab's link to it | No scheduled or triggered agent work |

The core, in `../compose/base.yml`, is what everything else needs: postgres, auth-server,
t10-agent-control, the three ai-gateway roles, t10-collab, t10-knowledge, agent-ti and workbench.

## Switching one off

In `site/config/settings.env`, for every environment of the project:

```sh
FOUNDATION_OFF=voice,console
```

Its services, ports, settings (and their `TODO`s on a server), secrets, images, public address,
clients and routes all drop out, because it's no longer a part. Its values may stay in
`site/secrets/`, unused, so switching it back on reuses them. `make check` fails on a name that
isn't a component, or when a component that's on needs one that's off. On a running stack,
`make up` leaves the old containers behind; `make down` first, or `scripts/compose.sh up -d
--remove-orphans`.

Tested Nov 16: everything on, and everything off (the core alone), each from empty volumes with
`make up`, `seed-demo`, `check` and `smoke`.

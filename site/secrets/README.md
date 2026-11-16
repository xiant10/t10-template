# Secrets

This project's secret values, one file per environment, and the only place they're read from.
Which secrets exist, which service gets each, and how to make and rotate them is in each part's
`secrets.json` (`../../foundation/`, `../../modules/<id>/`), never here.

| File | Holds | In git |
| --- | --- | --- |
| `local.env` | Random values for this checkout, from `make secrets-init`, plus `LLM_API_KEY` pasted in by hand | No |
| `<env>.env` | A server environment's values in plain text, from `make secrets-init ENV=<env>` and filled in by hand. Until SOPS is built; then only while a command runs | No |
| `<env>.enc.env` | A server environment's values, encrypted with SOPS and age (planned: `../../docs/plan.md`, C2) | Yes, encrypted |

Every run copies the environment's values into `generated/<env>/secrets.env` (mode 600), the one
file in the deployment bundle that holds them, and `make deploy` copies that to the host.
`generated/` is never the original: deleting it loses nothing. `make check` fails when a secret is
missing, unknown, or, in prod, a dev default or the same as local. `make rotate NAME=…` prints how
to rotate one.

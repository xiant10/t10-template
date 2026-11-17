# Secrets

This project's secret values, and the only place they're read from. Which secrets exist, which
service gets each, and how to make and rotate them is in each part's `secrets.json`, never here.
How to work with them is in `../../docs/guide.md` (Secrets).

| File | Holds | In git |
| --- | --- | --- |
| `local.env` | Random values for this checkout, made by every local command, plus `LLM_API_KEY` pasted in by hand | No |
| `.sops.yaml` | The age public keys that can decrypt the server environments' files, from `make secrets-key` | Yes |
| `<env>.enc.env` | A server environment's values, encrypted with SOPS and age, from `make secrets-init ENV=<env>`; `make secrets-set` and `make secrets-edit` change them | Yes, encrypted |
| `<env>.env` | A server environment's values in plain text, only before `.sops.yaml` exists; `make check` fails while it's here | No |

A server's values are decrypted in memory when a command needs them, never to a file here.
Back up your age key (`~/.config/sops/age/keys.txt`) and keep the break-glass key offline:
without either, the encrypted values are lost.

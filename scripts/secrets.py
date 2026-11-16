#!/usr/bin/env python3
"""Secrets per environment, against foundation/secrets.json and each module's secrets.json.

    scripts/secrets.py init ENV          # add missing values to site/secrets/<env>.env; keeps existing ones
    scripts/secrets.py check ENV [--allow-empty=NAME,…]   # every required secret set, nothing unknown, no dev values in prod
    scripts/secrets.py rotate NAME       # print how to rotate one secret

`init` only fills generated values (hex32, b64key). `provided` ones, such as
LLM_API_KEY, are left empty for someone to paste in. For a server environment the file is
plain text until SOPS is built (docs/plan.md, C2), so keep it off shared disks.
"""
import base64
import pathlib
import secrets
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402

INVENTORY = lib.inventory()
BY_NAME = {s["name"]: s for s in INVENTORY}
# The defaults t10-quickstart ships, which must never reach prod.
DEV_MARKERS = ("dev-only", "change-me", "quickstart-dev", "AAAAAAAAAAAAAAAAAAAA", "devkey")


def applies(s, env):
    """`envs` in the inventory names the template environments a secret is for: local, dev, prod."""
    return lib.shape(env) in s.get("envs", lib.SHAPES)


def generate(kind):
    if kind == "hex32":
        return secrets.token_hex(32)
    if kind == "b64key":
        return base64.b64encode(secrets.token_bytes(32)).decode()
    return ""


def init(env):
    path = lib.secrets_file(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    have = lib.read_env(path)
    lines = [f"# Secrets for {env}. Written by scripts/secrets.py init; existing values are kept.",
             "# Not committed. Fill in the empty `provided` values by hand."]
    added = 0
    for s in INVENTORY:
        if not applies(s, env):
            continue
        value = have.get(s["name"])
        if value is None:
            value = generate(s["generate"])
            added += 1
        lines.append(f"{s['name']}={value}")
    off = lib.secrets_off()
    for k in sorted(set(have) - {s["name"] for s in INVENTORY}):
        lines.append(f"# {k} belongs to a component this project doesn't run (FOUNDATION)" if k in off else f"# {k} is not in the secrets inventory")
        lines.append(f"{k}={have[k]}")
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)
    missing = [s["name"] for s in INVENTORY if applies(s, env) and s["generate"] == "provided" and not s.get("optional") and not lib.read_env(path).get(s["name"])]
    print(f"{path.relative_to(lib.ROOT)}: {added} added" + (f"; fill in {', '.join(missing)}" if missing else ""))


def check(env, allow_empty=()):
    path = lib.secrets_file(env).relative_to(lib.ROOT)
    have = lib.read_env(lib.secrets_file(env))
    problems = []
    for s in INVENTORY:
        if not applies(s, env):
            continue
        if not have.get(s["name"]) and not s.get("optional") and s["name"] not in allow_empty:
            problems.append(f"{s['name']} is not set")
    off = lib.secrets_off()
    for k, v in have.items():
        if k in off:
            continue
        if k not in BY_NAME:
            problems.append(f"{k} is not in the secrets inventory")
        elif lib.shape(env) == "prod" and any(m in v for m in DEV_MARKERS):
            problems.append(f"{k} holds a dev default")
    if lib.shape(env) == "prod":
        local = lib.read_env(lib.secrets_file("local"))
        problems += [f"{k} is the same as in local.env" for k, v in have.items() if v and local.get(k) == v]
    for p in problems:
        print(f"{path}: {p}", file=sys.stderr)
    return not problems


def main(argv):
    if argv[:1] == ["init"] and len(argv) == 2:
        init(argv[1])
    elif argv[:1] == ["check"] and len(argv) >= 2:
        allow = [n for a in argv[2:] if a.startswith("--allow-empty=") for n in a.split("=", 1)[1].split(",")]
        sys.exit(0 if check(argv[1], allow) else 1)
    elif argv[:1] == ["rotate"] and len(argv) == 2:
        s = BY_NAME.get(argv[1]) or sys.exit(f"{argv[1]} is not in the secrets inventory")
        print(f"{s['name']}: used by {', '.join(s['consumers'])}\n{s['rotate']}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

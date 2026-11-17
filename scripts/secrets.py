#!/usr/bin/env python3
"""Secrets per environment, against the inventory: each part's secrets.json (lib.inventory).

    scripts/secrets.py init ENV          # add missing values; keeps existing ones
    scripts/secrets.py check ENV [--allow-empty=NAME,…]   # every required secret set, nothing unknown, no dev values in prod
    scripts/secrets.py key [--breakglass]                 # this machine's age key, and site/secrets/.sops.yaml
    scripts/secrets.py recipient AGE_PUBLIC_KEY           # let another key decrypt every environment
    scripts/secrets.py set ENV NAME      # one value, typed in (not shown) or from stdin
    scripts/secrets.py edit ENV          # every value, in an editor (sops edit)
    scripts/secrets.py rotate NAME [ENV] [--finish]       # how to rotate one secret; with ENV, do it there

Local's values are plain text in site/secrets/local.env. A server environment's are encrypted
with SOPS and age in site/secrets/<env>.enc.env, which is committed, once the project has
site/secrets/.sops.yaml (`make secrets-key`); they're decrypted in memory, never to disk
(lib.secrets_text). Until then they're plain text in site/secrets/<env>.env, and `make check`
fails for that environment.

`init` fills generated values (hex32, b64key, es256: a signing key from auth-server's image).
`provided` ones, such as LLM_API_KEY, are left empty for `make secrets-set` or `make secrets-edit`.
"""
import base64
import os
import pathlib
import re
import secrets
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402

INVENTORY = lib.inventory()
BY_NAME = {s["name"]: s for s in INVENTORY}
# The defaults t10-quickstart ships, which must never reach prod.
DEV_MARKERS = ("dev-only", "change-me", "quickstart-dev", "AAAAAAAAAAAAAAAAAAAA", "devkey")
KEY_FILE = pathlib.Path(os.environ.get("SOPS_AGE_KEY_FILE") or pathlib.Path.home() / ".config/sops/age/keys.txt")


def applies(s, env):
    """`envs` in the inventory names the template environments a secret is for: local, dev, prod."""
    return lib.shape(env) in s.get("envs", lib.SHAPES)


def generate(kind):
    if kind == "hex32":
        return secrets.token_hex(32)
    if kind == "b64key":
        return base64.b64encode(secrets.token_bytes(32)).decode()
    if kind == "es256":
        # auth-server's own generator, from its pinned image; one line, as env files hold it.
        pem = subprocess.run(["docker", "run", "--rm", "--entrypoint", "authctl", lib.versions()["T10_AUTH_SERVER"], "gen-key"],
                             capture_output=True, text=True, check=True).stdout.strip()
        return '"' + pem.replace("\n", "\\n") + '"'
    return ""


def where(env):
    return (lib.encrypted_file(env) if lib.encrypts(env) else lib.secrets_file(env)).relative_to(lib.ROOT)


def save(env, values, header):
    """Writes every value back, as written (quotes kept), inventory first, then any it doesn't know."""
    lines = [f"# Secrets for {env}. {header}"]
    known = set()
    for s in INVENTORY:
        if applies(s, env) and s["name"] in values:
            lines.append(f"{s['name']}={values[s['name']]}")
            known.add(s["name"])
    off = lib.secrets_off()
    for k in sorted(set(values) - known):
        lines.append(f"# {k} belongs to a component this project doesn't run (FOUNDATION)" if k in off else f"# {k} is not in the secrets inventory")
        lines.append(f"{k}={values[k]}")
    lib.write_secrets(env, "\n".join(lines) + "\n")


def init(env):
    have = lib.secret_values(env, raw=True)
    values, added = dict(have), 0
    for s in INVENTORY:
        if applies(s, env) and s["name"] not in values:
            values[s["name"]] = generate(s["generate"])
            added += 1
    if added or (lib.encrypts(env) and lib.secrets_file(env).exists()):
        save(env, values, "Written by scripts/secrets.py; existing values are kept.")
    missing = [s["name"] for s in INVENTORY if applies(s, env) and s["generate"] == "provided" and not s.get("optional")
               and not lib.parse_env(f"x={values[s['name']]}")["x"]]
    print(f"{where(env)}: {added} added" + (f"; fill in {', '.join(missing)} (make secrets-set ENV={env} NAME=…)" if missing else ""))


def check(env, allow_empty=()):
    have = lib.secret_values(env)
    problems = []
    if lib.shape(env) != "local" and lib.secrets_file(env).exists():
        problems.append("is plain text: make secrets-key, then make secrets-init ENV=" + env + " encrypts it" if not lib.SOPS_CONFIG.exists()
                        else f"is plain text beside {lib.encrypted_file(env).name}: make secrets-init ENV={env} encrypts it")
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
        local = lib.secret_values("local")
        problems += [f"{k} is the same as in local.env" for k, v in have.items() if v and local.get(k) == v]
    for p in problems:
        print(f"{where(env) if lib.has_secrets(env) else f'site/secrets/{env}'}: {p}", file=sys.stderr)
    return not problems


def key(breakglass=False):
    """This machine's age key, made if missing, and site/secrets/.sops.yaml naming it. With
    breakglass, a new key printed once for paper, never saved, and added as a recipient."""
    made = subprocess.run([str(lib.ROOT / "scripts/sops.sh"), "age-keygen"], capture_output=True, text=True, check=True).stdout
    if breakglass:
        print("A break-glass age key. Print or write this down, keep it offline, and don't save it on any machine:\n")
        print(made)
        recipient(public_key(made))
        return
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(made)
        KEY_FILE.chmod(0o600)
        print(f"made {KEY_FILE}: back it up somewhere safe; without it or the break-glass key, the encrypted secrets are lost")
    mine = public_key(KEY_FILE.read_text())
    print(f"this machine's public key: {mine}")
    recipient(mine)


def public_key(key_text):
    return next(line.split(":", 1)[1].strip() for line in key_text.splitlines() if line.startswith("# public key:"))


def recipient(pub):
    """Adds an age public key to every environment in .sops.yaml, if it isn't there, and
    re-encrypts each file for exactly the keys .sops.yaml names (so a key deleted there is dropped)."""
    if not pub.startswith("age1"):
        sys.exit(f"{pub}: an age public key starts with age1")
    have = lib.SOPS_CONFIG.read_text() if lib.SOPS_CONFIG.exists() else ""
    keys = [k.strip() for line in have.splitlines() if line.strip().startswith("age:") for k in line.split(":", 1)[1].split(",") if k.strip()]
    if pub not in keys:
        keys.append(pub)
    lib.SECRETS.mkdir(parents=True, exist_ok=True)
    lib.SOPS_CONFIG.write_text(
        "# Who can decrypt each server environment's secrets, site/secrets/<env>.enc.env: age public keys.\n"
        "# Written by `make secrets-key`; RECIPIENT=age1… adds one. Removing one: delete it here, then\n"
        "# `make secrets-key` re-encrypts every file without it. Keys themselves never go in the repo.\n"
        "creation_rules:\n"
        "  - path_regex: \\.enc\\.env$\n"
        f"    age: {','.join(keys)}\n")
    print(f"{lib.SOPS_CONFIG.relative_to(lib.ROOT)}: {len(keys)} recipient(s); commit it")
    for f in sorted(lib.SECRETS.glob("*.enc.env")):
        lib.sops("updatekeys", "--yes", "--input-type", "dotenv", str(f.relative_to(lib.ROOT)))
        print(f"re-encrypted {f.relative_to(lib.ROOT)}")


def set_value(env, name, value):
    if name not in BY_NAME:
        sys.exit(f"{name} is not in the secrets inventory")
    values = lib.secret_values(env, raw=True)
    values[name] = value
    save(env, values, "Written by scripts/secrets.py.")


def edit(env):
    if not lib.encrypts(env):
        sys.exit(f"{lib.secrets_file(env).relative_to(lib.ROOT)} is plain text: edit it directly")
    if not lib.encrypted_file(env).exists():
        init(env)
    os.execv(str(lib.ROOT / "scripts/sops.sh"), ["sops.sh", "sops", "--config", str(lib.SOPS_CONFIG.relative_to(lib.ROOT)),
                                                 "edit", "--input-type", "dotenv", "--output-type", "dotenv",
                                                 str(lib.encrypted_file(env).relative_to(lib.ROOT))])


def on_host(env, *cmd):
    """Runs a command in the environment's auth-server: here for local, else on its host
    (scripts/compose.sh runs a server's commands there, over SSH)."""
    args = [str(lib.ROOT / "scripts/compose.sh"), "exec", "-T", "auth-server", *cmd]
    r = subprocess.run(args, capture_output=True, text=True, env=dict(os.environ, ENV=env))
    if r.returncode != 0:
        sys.exit(f"{' '.join(cmd)}: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout.strip()


def rotate(name, env=None, finish=False):
    """Rotates one secret in ENV where the inventory says how (`rotation`), or prints how."""
    s = BY_NAME.get(name) or sys.exit(f"{name} is not in the secrets inventory")
    kind = s.get("rotation", "manual")
    roll = f"make deploy ENV={env}" if env and lib.shape(env) != "local" else "make up"
    if env is None or kind == "manual":
        print(f"{s['name']}: used by {', '.join(s.get('consumers', []))}\n{s['rotate']}")
        if kind != "manual":
            print(f"`make rotate NAME={name} ENV=<env> APPLY=1` does it.")
        return
    if kind == "replace":
        set_value(env, name, generate(s["generate"]))
        print(f"{name}: a new value in {where(env)}. Now {roll}, which rolls everything that reads it.")
    elif kind.startswith("account:"):
        account = kind.split(":", 1)[1]
        if finish:
            on_host(env, "authctl", "service-finish", f"--name={account}")
            print(f"{name}: the old secret of {account} is retired.")
            return
        out = on_host(env, "authctl", "service-rotate", f"--name={account}")
        found = re.search(r"shown once:\s*(\S+)", out)
        if not found:
            sys.exit(f"authctl service-rotate --name={account} printed no secret: {out[-200:]}")
        new = found.group(1)
        set_value(env, name, new)
        print(f"{name}: auth-server accepts both secrets of {account} now, and the new one is in {where(env)}.\n"
              f"Next: {roll}, check it works, then make rotate NAME={name} ENV={env} FINISH=1 to retire the old one.")
    elif kind == "signing-key":
        values = lib.secret_values(env, raw=True)
        if finish:
            if not lib.parse_env(f"x={values.get('AUTH_SIGNING_KEY_NEXT', '')}")["x"]:
                sys.exit("AUTH_SIGNING_KEY_NEXT is empty: start with make rotate NAME=AUTH_SIGNING_KEY_CURRENT ENV=" + env)
            values["AUTH_SIGNING_KEY_CURRENT"], values["AUTH_SIGNING_KEY_NEXT"] = values["AUTH_SIGNING_KEY_NEXT"], ""
            save(env, values, "Written by scripts/secrets.py.")
            print(f"The new signing key is current. Now {roll}.")
            return
        set_value(env, "AUTH_SIGNING_KEY_NEXT", generate("es256"))
        print(f"A new signing key is AUTH_SIGNING_KEY_NEXT in {where(env)}. Now {roll}, so auth-server publishes it;\n"
              f"after one token lifetime, make rotate NAME={name} ENV={env} FINISH=1 makes it current.")
    else:
        sys.exit(f"{name}: unknown rotation {kind!r}")


def main(argv):
    flags = [a for a in argv if a.startswith("--")]
    args = [a for a in argv if not a.startswith("--")]
    if args[:1] == ["init"] and len(args) == 2:
        init(args[1])
    elif args[:1] == ["check"] and len(args) == 2:
        allow = [n for a in flags if a.startswith("--allow-empty=") for n in a.split("=", 1)[1].split(",")]
        sys.exit(0 if check(args[1], allow) else 1)
    elif args == ["key"]:
        key("--breakglass" in flags)
    elif args[:1] == ["recipient"] and len(args) == 2:
        recipient(args[1])
    elif args[:1] == ["set"] and len(args) == 3:
        import getpass
        value = getpass.getpass(f"{args[2]} for {args[1]} (not shown): ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
        set_value(args[1], args[2], value)
        print(f"{args[2]} set in {where(args[1])}")
    elif args[:1] == ["edit"] and len(args) == 2:
        edit(args[1])
    elif args[:1] == ["rotate"] and len(args) in (2, 3):
        rotate(args[1], args[2] if len(args) == 3 else None, "--finish" in flags)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

#!/usr/bin/env python3
"""Postgres backups for an environment, on its host for a server (scripts/compose.sh runs them
there). The backup service dumps every database on a schedule into its backups volume
(foundation/backup.sh); these act on it:

    scripts/backup.py now ENV             # one dump now
    scripts/backup.py pull ENV            # copy the newest here, to backups/<env>/, checked and encrypted
    scripts/backup.py restore ENV FILE    # put one back, replacing every database (needs CONFIRM=<env>)

`pull` encrypts with age for every key in site/secrets/.sops.yaml, the same keys that can read
the environment's secrets, so a backup is as safe off the host as its secrets are. A restore
also needs that environment's secrets as they were then (MODEL_KEY, any module's data key):
they're in git, in site/secrets/<env>.enc.env.
"""
import gzip
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402

BACKUPS = lib.ROOT / "backups"


def compose(env, *args, stdin=None, binary=False):
    r = subprocess.run([str(lib.PLATFORM / "scripts/compose.sh"), *args], input=stdin, capture_output=True,
                       text=not binary, env=dict(os.environ, ENV=env))
    if r.returncode != 0:
        err = r.stderr.decode(errors="replace") if binary else r.stderr
        sys.exit(f"compose {' '.join(args[:3])}: {err.strip()[-400:]}")
    return r.stdout


def run(env, *cmd, **kw):
    """A command in a one-off backup container, which has the backups volume and the database password."""
    return compose(env, "run", "--rm", "--no-deps", "-T", "--entrypoint", cmd[0], "backup", *cmd[1:], **kw)


def recipients():
    text = lib.SOPS_CONFIG.read_text() if lib.SOPS_CONFIG.exists() else ""
    return [k.strip() for line in text.splitlines() if line.strip().startswith("age:") for k in line.split(":", 1)[1].split(",") if k.strip()]


def age(*args, data):
    r = subprocess.run([str(lib.PLATFORM / "scripts/sops.sh"), "age", *args], input=data, capture_output=True, cwd=lib.ROOT)
    if r.returncode != 0:
        sys.exit(f"age: {r.stderr.decode(errors='replace').strip()[-300:]}")
    return r.stdout


def now(env):
    print(run(env, "bash", "/backup.sh", "once").strip())


def pull(env):
    keys = recipients()
    if not keys and lib.shape(env) != "local":
        sys.exit("make secrets-key first: a server's backups are encrypted for the keys in site/secrets/.sops.yaml")
    newest = run(env, "sh", "-c", "ls -1t /backups/*.sql.gz 2>/dev/null | head -1").strip()
    if not newest:
        sys.exit(f"{env} has no backup yet: make backup ENV={env}")
    data = run(env, "cat", newest, binary=True)
    try:
        sql = gzip.decompress(data)
    except OSError as e:
        sys.exit(f"{newest} isn't a whole gzip file: {e}")
    if b"PostgreSQL database cluster dump complete" not in sql[-2000:]:
        sys.exit(f"{newest} doesn't end as a complete pg_dumpall does")
    out = BACKUPS / env / pathlib.Path(newest).name
    out.parent.mkdir(parents=True, exist_ok=True)
    if keys:
        data = age(*[a for k in keys for a in ("-r", k)], data=data)
        out = out.with_name(out.name + ".age")
    out.write_bytes(data)
    out.chmod(0o600)
    print(f"{out.relative_to(lib.ROOT)}: {len(sql) // 1024} KiB of SQL, complete" + (f", encrypted for {len(keys)} key(s)" if keys else ""))


def restore(env, path):
    if os.environ.get("CONFIRM") != env:
        sys.exit(f"this replaces every database in {env} with {path}: run it again with CONFIRM={env}")
    data = pathlib.Path(path).read_bytes()
    if path.endswith(".age"):
        data = age("-d", "-i", "@key", data=data)
    sql = gzip.decompress(data)
    # Nothing may hold a database open while the dump drops and makes it again.
    compose(env, "stop")
    compose(env, "start", "postgres")
    compose(env, "exec", "-T", "postgres", "sh", "-c", "until pg_isready -U t10 -q; do sleep 1; done")
    out = compose(env, "exec", "-T", "postgres", "psql", "-q", "-U", "t10", "-d", "postgres", stdin=sql, binary=True)
    errors = [line for line in out.decode(errors="replace").splitlines() if re.search(r"ERROR", line)]
    print(f"restored {path} into {env}" + (f"; psql reported {len(errors)} error(s), such as dropping the login it runs as" if errors else ""))
    if lib.shape(env) == "local":
        subprocess.run([str(lib.PLATFORM / "scripts/compose.sh"), "up", "-d", "--wait"], check=True, env=dict(os.environ, ENV=env))
        print("started again: make smoke checks it")
    else:
        print(f"now make deploy ENV={env} starts it again, then make smoke ENV={env}")


def main(argv):
    if argv[:1] == ["now"] and len(argv) == 2:
        now(argv[1])
    elif argv[:1] == ["pull"] and len(argv) == 2:
        pull(argv[1])
    elif argv[:1] == ["restore"] and len(argv) == 3:
        restore(argv[1], argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

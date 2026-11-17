#!/usr/bin/env python3
"""Runs each part's hooks/<EVENT>.sh or hooks/<EVENT>.py, in part order: foundation/, its
components that are on, each module's folder, then site/ (docs/guide.md#hooks).

    scripts/hook.py EVENT           # post-up, seed-demo, pre-deploy or post-deploy

`make smoke` and `make check` run their hooks themselves, so a .py one can use their helpers.
Each hook runs from the repo root with the caller's environment, plus ENV, T10_PART (its part's
folder, such as site or modules/crm), T10_MODULE (a module's ID, else empty) and T10_COMPOSE (this
project's scripts/compose.sh). A .sh one runs with sh, a .py one with python3 -I -B. One that
fails stops the rest, and the command.
"""
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402


def main(argv):
    if len(argv) != 1 or argv[0] in ("smoke", "check"):
        sys.exit(__doc__)
    env = os.environ.get("ENV", "local")
    for part, hook in lib.hooks(argv[0]):
        rel = hook.relative_to(lib.ROOT)
        print(f"hook {rel}", file=sys.stderr)
        cmd = ["sh", str(rel)] if hook.suffix == ".sh" else [sys.executable, "-I", "-B", str(rel)]
        r = subprocess.run(cmd, cwd=lib.ROOT, env=dict(os.environ, ENV=env, T10_PART=str(part.relative_to(lib.ROOT)),
                                                      T10_MODULE=(lib.module_of(part) or {}).get("MODULE_ID", ""),
                                                      T10_COMPOSE=str(lib.ROOT / "scripts" / "compose.sh")))
        if r.returncode != 0:
            sys.exit(f"{rel} failed ({r.returncode})")


if __name__ == "__main__":
    main(sys.argv[1:])

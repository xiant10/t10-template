#!/usr/bin/env python3
"""`make doctor`: whether this machine can run the project, before the first `make up`.

Docker running, Compose 2.24 or later, Python 3.9 or later, the `template` git remote that
`make template-update` merges from, and, while the stack isn't running, that each local port is
free.
"""
import os
import pathlib
import re
import socket
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402

ENV = os.environ.get("ENV", "local")
check = lib.check


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=lib.ROOT, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


check("Python 3.9 or later", sys.version_info >= (3, 9), sys.version.split()[0])
r = run("docker", "info", "--format", "{{.ServerVersion}}")
check("Docker is running", r.returncode == 0, (r.stderr or r.stdout).strip()[-300:])
r = run("docker", "compose", "version", "--short")
version = tuple(int(n) for n in re.findall(r"\d+", r.stdout)[:2]) if r.returncode == 0 else ()
check("Docker Compose 2.24 or later", version >= (2, 24), r.stdout.strip() or r.stderr.strip())
r = run("git", "remote", "get-url", "template")
origin = run("git", "remote", "get-url", "origin").stdout.strip()
if r.returncode != 0 and not re.search(r"/t10-template(\.git)?$", origin):  # the template itself has none
    print("warn no git remote named template, so `make template-update` can't run: git remote add template <template repo>")

if lib.shape(ENV) == "local":
    project = f"{lib.settings(ENV).get('PROJECT_NAME')}-{ENV}"
    running = run("docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}").stdout.strip()
    if running:
        print(f"skip ports: {ENV} is running")
    else:
        busy = []
        for name, value in sorted(lib.settings(ENV).items()):
            if name.endswith("_PORT") and value.isdigit():
                with socket.socket() as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    if s.connect_ex(("127.0.0.1", int(value))) == 0:
                        busy.append(f"{name}={value}")
        check(f"{ENV}'s ports are free", not busy,
              f"in use: {', '.join(busy)}; another project may be running (make down there), or move them in site/config/{ENV}/settings.env")

lib.finish()

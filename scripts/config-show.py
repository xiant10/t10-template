#!/usr/bin/env python3
"""Prints one service's effective settings in Compose, and the layer each came from.

    scripts/config-show.py SERVICE        # ENV=local by default

Secret values are masked. Layers, highest first: each part's config/<env>/<service>.env,
then each part's config/<service>.env, site/ before modules/ before foundation/, then what the
Compose files set (wiring, module variables, secrets).
"""
import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402

ENV = os.environ.get("ENV", "local")
MODULE_KEYS = ("GRANT_", "TOOL_", "AGENT_URLS", "MODULE_URLS", "AUTH_APP_URLS")


def main(service):
    run = subprocess.run([str(lib.ROOT / "scripts" / "compose.sh"), "config", "--format", "json"], capture_output=True, text=True)
    if run.returncode:
        sys.exit(run.stderr)
    services = json.loads(run.stdout)["services"]
    if service not in services:
        sys.exit(f"{service} isn't a service: {', '.join(sorted(services))}")
    effective = services[service].get("environment") or {}

    secret_names = {s["name"] for s in lib.inventory()}
    secret_values = {v for v in lib.read_env(lib.secrets_file(ENV)).values() if len(v) >= 8}
    layers = [(str(path.relative_to(lib.ROOT)), lib.read_env(path)) for path in reversed(lib.service_layers(service, ENV))]

    width = max((len(k) for k in effective), default=0)
    for key in sorted(effective):
        value = effective[key] or ""
        source = next((name for name, values in layers if key in values), "compose (wiring)")
        if key in secret_names or any(s in value for s in secret_values):
            value, source = "•••", "secrets" if source == "compose (wiring)" else source
        elif key.startswith(MODULE_KEYS):
            source += ", with module packs"
        print(f"{key:<{width}}  {value:<60}  {source}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])

#!/bin/sh
# Demo data on a local stack (local, or k8s-local on Kubernetes): the foundation's sample
# accounts, then each part's hooks/seed-demo.sh or .py (scripts/hook.py), run from the repo root.
# Safe to repeat. Local only, because the sample password is published.
#
# A hook gets ENV (local or k8s-local), AUTH_URL (auth-server's published address), T10_COMPOSE
# (this project's scripts/compose.sh, for `exec` into a container), T10_PG_USER (Postgres's
# admin user), T10_PART and T10_MODULE, and can ask for a setting with
# `python3 -I -B scripts/lib.py setting "$ENV" NAME`.
set -eu
cd "$(dirname "$0")/.."
ENV=${ENV:-local}
[ "$(python3 -I -B scripts/lib.py shape "$ENV")" = local ] || { echo "seed-demo is for local only" >&2; exit 1; }
port() { python3 -I -B scripts/lib.py setting "$ENV" "$1"; }

scripts/compose.sh exec -T auth-server authctl samples-add
AUTH_URL="http://127.0.0.1:$(port AUTH_PORT)"
export ENV T10_PG_USER=t10 AUTH_URL
python3 -I -B scripts/hook.py seed-demo

#!/bin/sh
# Copies an environment's bundle, generated/<env>/, to its host and starts it there with the
# bundle's own compose.sh. The host and folder are DEPLOY_HOST (an ssh destination) and
# DEPLOY_DIR, set in site/config/<env>/settings.env. `make check` runs first.
#
#   ENV=prod scripts/deploy.sh
#
# The host needs Docker with Compose 2.24 or later, rsync, and `docker login ghcr.io` for the
# any private module image. Nothing else from this repo goes there.
set -eu
cd "$(dirname "$0")/.."
env=${ENV:-local}
[ "$(python3 -I -B scripts/lib.py shape "$env")" != local ] || { echo "ENV=$env runs on this machine: make up" >&2; exit 1; }
[ -z "${DEV:-}${SCRIPTED:-}" ] || { echo "DEV and SCRIPTED are for local only" >&2; exit 1; }
setting() { python3 -I -B scripts/lib.py setting "$env" "$1"; }
host=$(setting DEPLOY_HOST)
dir=$(setting DEPLOY_DIR)
[ "$host" != TODO ] && [ "$dir" != TODO ] || { echo "set DEPLOY_HOST and DEPLOY_DIR in site/config/$env/settings.env" >&2; exit 1; }

ENV=$env python3 -I -B scripts/check.py
# secrets.env keeps its mode 600 on the host; --delete drops what the bundle no longer has.
# --inplace keeps each file's inode, so a running container's bind mount sees the new content.
ssh "$host" "mkdir -p '$dir'"
rsync -a --inplace --delete "generated/$env/" "$host:$dir/"
ssh "$host" "'$dir/compose.sh' up -d --wait --wait-timeout 300 --remove-orphans && '$dir/compose.sh' exec -T caddy caddy reload --config /etc/caddy/Caddyfile"

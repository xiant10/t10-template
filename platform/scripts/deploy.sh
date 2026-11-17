#!/bin/sh
# Copies an environment's bundle, generated/<env>/, to its host and starts it there with the
# bundle's own compose.sh. The host and folder are DEPLOY_HOST (an ssh destination) and
# DEPLOY_DIR, set in site/config/<env>/settings.env. `make check` runs first.
#
#   ENV=prod scripts/deploy.sh
#
# The host needs Docker with Compose 2.24 or later, rsync, and `docker login ghcr.io` for
# any private module image. Nothing else from this repo goes there. Each part's
# hooks/pre-deploy and hooks/post-deploy run here, before the copy and once it's up (scripts/hook.py).
set -eu
cd "$(dirname "$0")/../.."
env=${ENV:-local}
[ "$(python3 -I -B platform/scripts/lib.py shape "$env")" != local ] || { echo "ENV=$env runs on this machine: make up" >&2; exit 1; }
[ -z "${DEV:-}${SCRIPTED:-}" ] || { echo "DEV and SCRIPTED are for local only" >&2; exit 1; }
setting() { python3 -I -B platform/scripts/lib.py setting "$env" "$1"; }
host=$(setting DEPLOY_HOST)
dir=$(setting DEPLOY_DIR)
ssh_opts=$(setting DEPLOY_SSH)
[ "$host" != TODO ] && [ "$dir" != TODO ] || { echo "set DEPLOY_HOST and DEPLOY_DIR in site/config/$env/settings.env" >&2; exit 1; }

ENV=$env python3 -I -B platform/scripts/check.py
ENV=$env python3 -I -B platform/scripts/hook.py pre-deploy
# The bundle with its secrets, decrypted in memory from site/secrets/<env>.enc.env, only until
# it's copied: the trap renders it again without them, so they stay only on the host.
trap 'python3 -I -B platform/scripts/render.py "$env"' EXIT
T10_BUNDLE_SECRETS=1 python3 -I -B platform/scripts/render.py "$env"
# The secret files keep their mode 600 on the host; --delete drops what the bundle no longer has.
# --inplace keeps each file's inode, so a running container's bind mount sees the new content.
# shellcheck disable=SC2086
ssh $ssh_opts "$host" "mkdir -p '$dir'"
rsync -a --inplace --delete -e "ssh $ssh_opts" "generated/$env/" "$host:$dir/"
# shellcheck disable=SC2086
ssh $ssh_opts "$host" "'$dir/compose.sh' up -d --wait --wait-timeout 300 --remove-orphans && '$dir/compose.sh' exec -T caddy caddy reload --config /etc/caddy/Caddyfile && { out=\$('$dir/compose.sh' run --rm --no-deps --quiet-pull --entrypoint sh agent-routes -c 'agentctl import /routes.json --reason \"make deploy\"' 2>&1); s=\$?; echo \"\$out\"; [ \$s -eq 0 ] || echo \"\$out\" | grep -q 'changes nothing' || { echo \"\$out\" | grep -q 'until it.s retired' && echo 'warn: a removed module agent pool is still routed (upstream U17)'; }; }"
ENV=$env python3 -I -B platform/scripts/hook.py post-deploy

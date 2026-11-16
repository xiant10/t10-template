#!/bin/sh
# After changing a module built from src/, on local: rebuilds its image and restarts it. When
# its pack (src/<SRC>/module/) changed since the last reload, also restarts what reads the pack
# at start: auth-server (its catalog and clients), and t10-agents and agent-ti (its agent).
#
#   MODULE=<id> scripts/reload.sh
set -eu
cd "$(dirname "$0")/.."
[ -n "${MODULE:-}" ] || { echo "say which module: MODULE=<id>" >&2; exit 1; }
[ "$(python3 -I -B scripts/lib.py shape "${ENV:-local}")" = local ] || { echo "reload is for local only" >&2; exit 1; }
# shellcheck disable=SC2046
set -- $(python3 -I -B scripts/lib.py built "$MODULE")
src=$2 service=$3

scripts/compose.sh up -d --build --no-deps --wait "$service"
state=generated/.pack-$MODULE
pack=$(cd "src/$src/module" && find . -type f | LC_ALL=C sort | xargs shasum | shasum | cut -d' ' -f1)
if [ "$(cat "$state" 2>/dev/null)" != "$pack" ]; then
	echo "its pack changed, so restarting what reads it"
	scripts/compose.sh up -d --force-recreate --no-deps --wait auth-server t10-agents agent-ti
	make --no-print-directory routes-publish
	echo "$pack" >"$state"
fi

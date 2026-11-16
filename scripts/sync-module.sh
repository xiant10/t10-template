#!/bin/sh
# Copies a module's pack out of its image into modules/<id>/pack/, or with --check, fails if
# modules/<id>/pack/ differs from it.
#
#   MODULE=<id> scripts/sync-module.sh [--check]    # MODULE may be left out when there's one module
#
# The image is T10_<ID> from the parts' versions.env files, unless IMAGE names another (such as a local
# build: IMAGE=<service>:dev).
set -eu
cd "$(dirname "$0")/.."

check=false
[ "${1:-}" = "--check" ] && check=true
module=${MODULE:-}
if [ -z "$module" ]; then
	set -- modules/*/
	[ $# -eq 1 ] && [ -d "$1" ] || { echo "say which module: MODULE=<id> (folders in modules/)" >&2; exit 1; }
	module=$(basename "$1")
fi
dest=modules/$module/pack
[ -d "modules/$module" ] || { echo "modules/$module doesn't exist" >&2; exit 1; }
if [ -z "${IMAGE:-}" ]; then
	var=T10_$(echo "$module" | tr '[:lower:]-' '[:upper:]_')
	IMAGE=$(python3 -I -B scripts/lib.py version "$var")
fi

tmp=$(mktemp -d)
container=$(docker create "$IMAGE")
trap 'docker rm -f "$container" >/dev/null; rm -rf "$tmp"' EXIT
docker cp -q "$container:/module" "$tmp/module"

if $check; then
	if ! diff -r "$tmp/module" "$dest"; then
		echo "$dest differs from $IMAGE: run make sync-module MODULE=$module" >&2
		exit 1
	fi
	echo "$dest matches $IMAGE"
else
	rm -rf "$dest"
	cp -R "$tmp/module" "$dest"
	echo "$dest now holds the pack from $IMAGE"
fi

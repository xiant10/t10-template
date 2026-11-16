#!/bin/sh
# Tests each module built from src/: its Dockerfile's `test` stage, so they run with the image's
# own toolchain and nothing needs installing here. Docker caches the stage, so a module whose
# source hasn't changed isn't tested again.
#
#   scripts/test.sh                 # every module built from src/; MODULE=<id> for one
set -eu
cd "$(dirname "$0")/.."
list=$(python3 -I -B scripts/lib.py built ${MODULE:-})
if [ -z "$list" ]; then
	echo "no module is built from src/ yet: make new-module"
	exit 0
fi
echo "$list" | while read -r id src service; do
	echo "== $id: src/$src"
	docker build --target test "src/$src"
done

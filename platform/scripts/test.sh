#!/bin/sh
# Tests each module built from modules/<id>/src/: its Dockerfile's `test` stage, so they run with
# the image's own toolchain and nothing needs installing here. A stage labelled t10.test=run is
# then run as a container beside a throwaway Postgres, with TEST_DATABASE_URL set, so a module's
# database tests run too; one without the label (a Dockerfile from before v0.10.0) runs its tests
# while it builds, with no database.
#
#   scripts/test.sh                 # every module built from modules/<id>/src/; MODULE=<id> for one
set -eu
cd "$(dirname "$0")/../.."
list=$(python3 -I -B platform/scripts/lib.py built ${MODULE:-})
if [ -z "$list" ]; then
	echo "no module is built in this project yet: make new-module"
	exit 0
fi
project=$(python3 -I -B platform/scripts/lib.py setting local PROJECT_NAME)-test
db=
cleanup() { [ -z "$db" ] || { docker rm -f "$db" >/dev/null; docker network rm "$project" >/dev/null; }; }
trap cleanup EXIT INT TERM
# Started once, for the first module that needs it; each module gets a database of its own.
postgres() {
	[ -z "$db" ] || return 0
	docker network create "$project" >/dev/null
	db=$project-postgres
	docker run -d --rm --name "$db" --network "$project" -e POSTGRES_USER=t10 -e POSTGRES_PASSWORD=test \
		"$(python3 -I -B platform/scripts/lib.py version local POSTGRES_IMAGE)" >/dev/null
	i=0
	until docker exec "$db" pg_isready -q -U t10 -h 127.0.0.1 2>/dev/null; do
		i=$((i + 1)); [ $i -lt 60 ] || { echo "the test Postgres didn't start" >&2; exit 1; }; sleep 1
	done
}
# Not a pipeline, so postgres() sets db in this shell, where cleanup reads it.
while read -r id src _; do
	echo "== $id: $src"
	image=$project-$id
	docker build --target test -t "$image" "$src"
	if [ "$(docker image inspect -f '{{index .Config.Labels "t10.test"}}' "$image")" = run ]; then
		postgres
		name=test_$(echo "$id" | tr -c 'a-z0-9\n' '_')
		docker exec "$db" sh -c "dropdb -U t10 --if-exists $name 2>/dev/null; createdb -U t10 $name"
		docker run --rm --network "$project" -e TEST_DATABASE_URL="postgres://t10:test@$db:5432/$name?sslmode=disable" "$image"
	fi
done <<EOF
$list
EOF

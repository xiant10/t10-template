#!/bin/sh
# Publishes a module built from src/, so a server runs the code that was tested here: builds its
# image, pushes it, and pins it in modules/<id>/versions.env, for you to commit.
#
#   MODULE=<id> scripts/release.sh
#
# The image is $IMAGE_REGISTRY/<service>:sha-<commit>. IMAGE_REGISTRY is a setting, such as
# ghcr.io/<owner> in site/config/settings.env, and `docker login` must reach it. The commit is
# the last one that changed modules/<id>/<SRC>/, which must have no uncommitted changes, so the tag
# names the source exactly. PLATFORM is the servers' (default linux/amd64).
set -eu
cd "$(dirname "$0")/../.."
[ -n "${MODULE:-}" ] || { echo "say which module: MODULE=<id>" >&2; exit 1; }
# shellcheck disable=SC2046
set -- $(python3 -I -B platform/scripts/lib.py built "$MODULE")
id=$1 src=$2 service=$3
registry=$(python3 -I -B platform/scripts/lib.py setting local IMAGE_REGISTRY)
[ -n "$registry" ] || { echo "set IMAGE_REGISTRY in site/config/settings.env, such as ghcr.io/<owner>" >&2; exit 1; }
[ -z "$(git status --porcelain -- "$src")" ] || { echo "commit $src first, so the image's tag names its source" >&2; exit 1; }
commit=$(git log -1 --format=%h -- "$src")
[ -n "$commit" ] || { echo "$src has no commit yet" >&2; exit 1; }

image=$registry/$service:sha-$commit
docker build --platform "${PLATFORM:-linux/amd64}" --tag "$image" "$src"
docker push "$image"
digest=$(docker inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$image" | grep "^$registry/$service@" | head -1 | cut -d@ -f2)
[ -n "$digest" ] || { echo "no digest for $image after the push" >&2; exit 1; }

var=T10_$(echo "$id" | tr '[:lower:]-' '[:upper:]_')
file=modules/$id/versions.env
if grep -q "^$var=" "$file"; then
	sed -i.bak "s|^$var=.*|$var=$image@$digest|" "$file" && rm "$file.bak"
else
	echo "$var=$image@$digest" >>"$file"
fi
echo "pinned $var=$image@$digest in $file: commit it, then make check ENV=<env> and make deploy ENV=<env>"

#!/bin/sh
# sops or age-keygen, as installed on this machine, or else from a small image built from
# scripts/tools/Dockerfile, so nothing needs installing. The age key is SOPS_AGE_KEY_FILE,
# ~/.config/sops/age/keys.txt unless set, and never leaves this machine.
#
#   scripts/sops.sh sops decrypt site/secrets/prod.enc.env
#   scripts/sops.sh age-keygen -o ~/.config/sops/age/keys.txt
set -eu
cd "$(dirname "$0")/.."
SOPS_AGE_KEY_FILE=${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}
export SOPS_AGE_KEY_FILE
tool=$1
shift
if command -v "$tool" >/dev/null 2>&1; then
	exec "$tool" "$@"
fi

image=t10-template-tools:$(cksum <scripts/tools/Dockerfile | cut -d' ' -f1)
docker image inspect "$image" >/dev/null 2>&1 || docker build -q -t "$image" scripts/tools >/dev/null
keys=$(dirname "$SOPS_AGE_KEY_FILE")
mkdir -p "$keys"
tty=""
[ ! -t 0 ] || [ ! -t 1 ] || tty=-t
# shellcheck disable=SC2086
exec docker run --rm -i $tty --user "$(id -u):$(id -g)" -v "$PWD:/w" -w /w -v "$keys:/keys" \
	-e SOPS_AGE_KEY_FILE="/keys/$(basename "$SOPS_AGE_KEY_FILE")" -e EDITOR=vi --entrypoint "$tool" "$image" "$@"

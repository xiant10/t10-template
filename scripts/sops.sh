#!/bin/sh
# sops or age-keygen, as installed on this machine, or else from a small image built from
# scripts/tools/Dockerfile, so nothing needs installing. The age key is SOPS_AGE_KEY_FILE,
# ~/.config/sops/age/keys.txt unless set, and never leaves this machine.
#
#   scripts/sops.sh sops decrypt site/secrets/prod.enc.env
#   scripts/sops.sh age-keygen
#   scripts/sops.sh age -d -i @key backup.sql.gz.age   # @key is the age key
set -eu
cd "$(dirname "$0")/.."
SOPS_AGE_KEY_FILE=${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}
export SOPS_AGE_KEY_FILE
tool=$1
shift
# An argument @key stands for the age key, wherever the tool runs (age -d -i @key).
if command -v "$tool" >/dev/null 2>&1; then
	for a in "$@"; do shift; [ "$a" = @key ] && a=$SOPS_AGE_KEY_FILE; set -- "$@" "$a"; done
	exec "$tool" "$@"
fi
for a in "$@"; do shift; [ "$a" = @key ] && a=/keys/$(basename "$SOPS_AGE_KEY_FILE"); set -- "$@" "$a"; done

image=t10-template-tools:$(cksum <scripts/tools/Dockerfile | cut -d' ' -f1)
docker image inspect "$image" >/dev/null 2>&1 || docker build -q -t "$image" scripts/tools >/dev/null
keys=$(dirname "$SOPS_AGE_KEY_FILE")
mkdir -p "$keys"
tty=""
[ ! -t 0 ] || [ ! -t 1 ] || tty=-t
# shellcheck disable=SC2086
exec docker run --rm -i $tty --user "$(id -u):$(id -g)" -v "$PWD:/w" -w /w -v "$keys:/keys" \
	-e SOPS_AGE_KEY_FILE="/keys/$(basename "$SOPS_AGE_KEY_FILE")" -e EDITOR=vi --entrypoint "$tool" "$image" "$@"

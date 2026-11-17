#!/bin/sh
# docker compose for this deployment. Checks the secrets, renders the bundle in generated/<env>/
# (scripts/render.py), then runs the bundle's own compose.sh, which `make deploy` runs on a host.
#
#   scripts/compose.sh up -d --wait          # ENV=local by default
#   DEV=1 scripts/compose.sh up -d --build   # adds each part's compose/build.yml: modules built from src/
#   SCRIPTED=1 scripts/compose.sh up -d      # adds compose/scripted.yml: a scripted model; no LLM_API_KEY needed
#                                            # (make turns it on by itself on local while there's no LLM_API_KEY)
#   ENV=dev scripts/compose.sh config         # any environment: local, dev, prod, or one in site/config/
#   ENV=prod scripts/compose.sh logs -f auth-server   # a server's: run on its host, over SSH
#
# For a server environment, `config` runs here, on its bundle; every other command runs on its
# host (DEPLOY_HOST, with DEPLOY_SSH's options) on the bundle `make deploy` put there, and `up`
# is `make deploy`. Deleting its data (`down -v`) needs CONFIRM=<env>.
set -eu
cd "$(dirname "$0")/.."
env=${ENV:-local}

# An environment's secrets are site/secrets/<env>.env, or for a server <env>.enc.env, decrypted
# in memory (scripts/lib.py). render.py writes them into the bundle.
secrets=site/secrets/$env.env
shape=$(python3 -I -B scripts/lib.py shape "$env")
if [ "$shape" = local ]; then
	# Every local run fills in generated values that are missing, such as a new module's.
	python3 -I -B scripts/secrets.py init "$env" | grep -v ': 0 added' >&2 || true
elif [ ! -f "$secrets" ] && [ ! -f "site/secrets/$env.enc.env" ]; then
	echo "$env has no secrets: make secrets-init ENV=$env, then make secrets-set or secrets-edit for the empty ones" >&2; exit 1
fi

allow=""
if [ -n "${SCRIPTED:-}" ]; then
	[ "${1:-}" != up ] || echo "using the scripted model (SCRIPTED=1): put a key in $secrets as LLM_API_KEY for a real one" >&2
	allow=--allow-empty=LLM_API_KEY
	export LLM_API_KEY="${LLM_API_KEY:-scripted}"
fi
# Missing secrets stop only commands that start containers; `config`, `ps` and `logs` still work.
if ! python3 -I -B scripts/secrets.py check "$env" $allow >&2; then
	case "${1:-}" in
	up | create | run | start | restart) echo "fix $env's secrets first" >&2; exit 1 ;;
	esac
fi

if [ "$shape" = local ]; then
	python3 -I -B scripts/render.py "$env"
	exec "generated/$env/compose.sh" "$@"
fi
if [ "${1:-}" != config ]; then
	case " $* " in
	" up "*) echo "on $env, make deploy ENV=$env starts it, after make check" >&2; exit 1 ;;
	*" -v "* | *" --volumes "*) [ "${CONFIRM:-}" = "$env" ] || { echo "this deletes $env's data: run it again with CONFIRM=$env" >&2; exit 1; } ;;
	esac
	setting() { python3 -I -B scripts/lib.py setting "$env" "$1"; }
	host=$(setting DEPLOY_HOST)
	dir=$(setting DEPLOY_DIR)
	# Each argument single-quoted for the host's shell.
	args=""
	for a in "$@"; do args="$args '$(printf %s "$a" | sed "s/'/'\\\\''/g")'"; done
	tty=""
	[ ! -t 0 ] || [ ! -t 1 ] || tty=-t
	opts=$(setting DEPLOY_SSH)
	# shellcheck disable=SC2086
	exec ssh $tty $opts "$host" "'$dir/compose.sh'$args"
fi
# A server environment's bundle holds its secrets only while Compose runs here.
T10_BUNDLE_SECRETS=1 python3 -I -B scripts/render.py "$env"
status=0
"generated/$env/compose.sh" "$@" || status=$?
python3 -I -B scripts/render.py "$env"
exit "$status"

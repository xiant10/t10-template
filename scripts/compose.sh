#!/bin/sh
# docker compose for this deployment. Checks the secrets, renders the bundle in generated/<env>/
# (scripts/render.py), then runs the bundle's own compose.sh, which `make deploy` runs on a host.
#
#   scripts/compose.sh up -d --wait          # ENV=local by default
#   DEV=1 scripts/compose.sh up -d --build   # adds each part's compose/build.yml: modules built from src/
#   SCRIPTED=1 scripts/compose.sh up -d      # adds compose/scripted.yml: a scripted model; no LLM_API_KEY needed
#                                            # (make turns it on by itself on local while there's no LLM_API_KEY)
#   ENV=dev scripts/compose.sh config         # any environment: local, dev, prod, or one in site/config/
set -eu
cd "$(dirname "$0")/.."
env=${ENV:-local}

# The only place an environment's secrets are read from. render.py copies them into the bundle.
secrets=site/secrets/$env.env
if [ "$env" = local ]; then
	# Every local run fills in generated values that are missing, such as a new module's.
	python3 -I -B scripts/secrets.py init local | grep -v ': 0 added' >&2 || true
elif [ ! -f "$secrets" ]; then
	echo "$secrets is missing: make secrets-init ENV=$env, then fill it in" >&2; exit 1
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
	up | create | run | start | restart) echo "fix $secrets first" >&2; exit 1 ;;
	esac
fi

python3 -I -B scripts/render.py "$env"
exec "generated/$env/compose.sh" "$@"

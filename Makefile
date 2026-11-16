# A project on the published t10 foundation images: foundation/, modules/<id>/ and site/.
# See README.md.
#
# ENV=local (default), dev, prod, or another in site/config/. DEV=1 builds each module from its
# checkout in src/ (local only).
# SCRIPTED=1 uses a scripted model, so nothing needs LLM_API_KEY.

ENV ?= local
export ENV DEV SCRIPTED MODULE IMAGE
COMPOSE := scripts/compose.sh
PY := python3 -I -B

.PHONY: help clone status secrets-init render up down down-all ps logs deploy seed-demo smoke check config-show routes-publish new-module sync-module pin rotate

help: ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

clone: ## Clone each module's repo (its source.env) into src/, if missing
	@$(PY) scripts/lib.py sources | while read -r dir url; do [ -d "src/$$dir" ] || git clone "$$url" "src/$$dir"; done

status: ## Branch and changes in this repo and each module repo in src/
	@git status -sb | head -1; git status --short
	@$(PY) scripts/lib.py sources | while read -r dir url; do [ ! -d "src/$$dir" ] || { printf '\n%s: ' "src/$$dir"; git -C "src/$$dir" status -sb | head -1; git -C "src/$$dir" status --short; }; done

secrets-init: ## Add missing secrets to site/secrets/<env>.env, keeping existing ones
	@$(PY) scripts/secrets.py init $(ENV)

render: ## Write the bundle in generated/<env>/ that up and deploy run; every command does this first
	@$(PY) scripts/render.py $(ENV)

# --remove-orphans: containers of a service no longer in the stack, such as a component left out
# of FOUNDATION, go too.
up: ## Start the stack and wait until it's healthy
	@$(COMPOSE) up -d --wait --wait-timeout 300 --remove-orphans $(if $(DEV),--build)

down: ## Stop the stack and keep its data (down-all also deletes the data)
	@$(COMPOSE) down --remove-orphans

down-all:
	@$(COMPOSE) down -v --remove-orphans

ps: ## Show containers
	@$(COMPOSE) ps -a

logs: ## Follow logs: make logs SVC=agent-ti
	@$(COMPOSE) logs -f --tail=100 $(SVC)

deploy: ## Copy generated/<env>/ to its host and start it there (ENV=prod; runs check first)
	@scripts/deploy.sh

seed-demo: ## Sample accounts, then each module's hooks/seed-demo.sh (local only)
	@scripts/seed-demo.sh

smoke: ## Check the running stack end to end
	@$(PY) scripts/smoke.py

check: ## Checks that need no running stack
	@$(PY) scripts/check.py

config-show: ## A service's settings and where each came from: make config-show SVC=auth-server
	@$(PY) scripts/config-show.py $(SVC)

routes-publish: ## Publish generated/<env>/agent-routes.json to t10-agent-control, after an agent changes
	@$(COMPOSE) run --rm --quiet-pull --entrypoint sh agent-routes -c \
		'out=$$(agentctl import /routes.json --reason "make routes-publish" 2>&1); s=$$?; echo "$$out"; \
		[ $$s -eq 0 ] || echo "$$out" | grep -q "changes nothing"'

new-module: ## Make modules/<id>/ for a new module: ID=crm SERVICE=t10-crm PORT=18076 (REPO=…), see docs/module.md
	@$(PY) scripts/new-module.py "$(ID)" "$(SERVICE)" "$(PORT)" $(REPO)

sync-module: ## Copy a module's pack out of its pinned image into modules/<id>/pack/ (MODULE=<id>, IMAGE=…)
	@scripts/sync-module.sh

pin: ## Show what each foundation image's latest is; WRITE=1 rewrites the versions.env that pins it
	@$(PY) scripts/resolve-tags.py $(if $(WRITE),--write)

rotate: ## How to rotate one secret: make rotate NAME=AUTH_ADMIN_PASSWORD
	@$(PY) scripts/secrets.py rotate $(NAME)

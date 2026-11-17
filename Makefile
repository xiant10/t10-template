# A project on the published t10 foundation images: foundation/, modules/<id>/ and site/.
# See README.md.
#
# ENV=local (default), dev, prod, k8s-local (local on this machine's Kubernetes), or another in
# site/config/. A module whose code is in src/ is always built from there on local and k8s-local;
# DEV=1 also builds each module in a repo of its own from its checkout in src/ (local only).
# SCRIPTED=1 uses a scripted model, so nothing needs LLM_API_KEY. On local and k8s-local it's on
# by itself while site/secrets/<env>.env has no LLM_API_KEY; SCRIPTED= (empty) turns it off.
# A project adds its own commands in site/project.mk, and a module in modules/<id>/module.mk
# (included at the end); a `## ` comment after a target lists it in `make help`.

ENV ?= local
ifeq ($(shell python3 -I -B scripts/lib.py shape $(ENV) 2>/dev/null),local)
SCRIPTED ?= $(if $(shell sed -n 's/^LLM_API_KEY=..*/x/p' site/secrets/$(ENV).env 2>/dev/null),,1)
endif
export ENV DEV SCRIPTED MODULE IMAGE CONFIRM SCAFFOLD
COMPOSE := scripts/compose.sh
PY := python3 -I -B
# The linters `make lint` runs, in Docker so nothing needs installing.
RUFF := ghcr.io/astral-sh/ruff:0.8.4
SHELLCHECK := koalaman/shellcheck:v0.10.0

.PHONY: help doctor clone status secrets-init render up down down-all ps logs deploy seed-demo smoke check test reload verify release config-show routes-publish new-module template-update sync-module pin rotate secrets-key secrets-set secrets-edit lint test-template alone alone-down contract backup backup-pull restore

help: ## List the commands
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

doctor: ## Whether this machine can run the project: Docker, Compose, Python, free ports (and kubectl, for k8s-local)
	@$(PY) scripts/doctor.py

clone: ## Clone each module that has a repo of its own (its source.env) into src/, kept out of git
	@$(PY) scripts/lib.py sources | while read -r dir url; do \
		grep -qxF "/src/$$dir/" .git/info/exclude 2>/dev/null || echo "/src/$$dir/" >>.git/info/exclude; \
		[ -d "src/$$dir" ] || git clone "$$url" "src/$$dir"; done

status: ## Branch and changes in this repo and in each module repo cloned into src/
	@git status -sb | head -1; git status --short
	@$(PY) scripts/lib.py sources | while read -r dir url; do [ ! -d "src/$$dir" ] || { printf '\n%s: ' "src/$$dir"; git -C "src/$$dir" status -sb | head -1; git -C "src/$$dir" status --short; }; done

secrets-init: ## Add missing secrets for ENV, keeping existing ones (a server's encrypted, once secrets-key is done)
	@$(PY) scripts/secrets.py init $(ENV)

render: ## Write the bundle in generated/<env>/ that up and deploy run; every command does this first
	@$(PY) scripts/render.py $(ENV)

# --remove-orphans: containers of a service no longer in the stack, such as a component left out
# of FOUNDATION, go too.
# --build: builds what has a build: section, each module whose code is in src/ (and with DEV=1,
# the others' checkouts); Docker's cache makes it quick when nothing changed. Then publishes the
# route document if it changed, so a new module's agent is routed (upstream U12). Then each
# part's hooks/post-up.
up: ## Start the stack and wait until it's healthy; modules in src/ are built first
	@$(COMPOSE) up -d --wait --wait-timeout 300 --remove-orphans --build
	@$(MAKE) --no-print-directory routes-publish
	@$(PY) scripts/hook.py post-up

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

seed-demo: ## Sample accounts, then each part's hooks/seed-demo (local only)
	@scripts/seed-demo.sh

smoke: ## Check the running stack end to end
	@$(PY) scripts/smoke.py

check: ## Checks that need no running stack
	@$(PY) scripts/check.py

test: ## Each module's own tests, from src/, in Docker: make test (MODULE=<id> for one)
	@scripts/test.sh

alone: ## Run one module by itself, with its own Postgres and no foundation: MODULE=<id> (alone-down stops it)
	@$(PY) scripts/alone.py "$(MODULE)" up

alone-down:
	@$(PY) scripts/alone.py "$(MODULE)" down

contract: ## Check one module keeps the module contract on its own: its pack, then its service run alone (MODULE=<id>)
	@QUIET=1 $(PY) scripts/alone.py "$(MODULE)" up >/dev/null
	@$(PY) scripts/contract.py "$(MODULE)"; s=$$?; $(PY) scripts/alone.py "$(MODULE)" down >/dev/null 2>&1; exit $$s

reload: ## After changing a module in src/: rebuild and restart it, and what reads its pack: MODULE=<id>
	@scripts/reload.sh

verify: ## Every gate, from empty volumes: test, each module alone (contract), then down-all, up, seed-demo, check, smoke
	@$(MAKE) --no-print-directory test
	@$(PY) scripts/lib.py built | while read -r id src service; do \
		$(MAKE) --no-print-directory contract MODULE=$$id || exit 1; done
	@$(MAKE) --no-print-directory down-all
	@$(MAKE) --no-print-directory up
	@$(MAKE) --no-print-directory seed-demo
	@$(MAKE) --no-print-directory check
	@$(MAKE) --no-print-directory smoke

release: ## Build, push and pin a module from src/ for servers: MODULE=<id> (IMAGE_REGISTRY setting)
	@scripts/release.sh

config-show: ## A service's settings and where each came from: make config-show SVC=auth-server
	@$(PY) scripts/config-show.py $(SVC)

# upstream U17: t10-agent-control won't drop the pool of a module that was removed, and agentctl
# can't retire one, so that import is refused; it says so rather than failing `make up`.
routes-publish: ## Publish generated/<env>/agent-routes.json to t10-agent-control, after an agent changes
	@$(COMPOSE) run --rm --no-deps --quiet-pull --entrypoint sh agent-routes -c \
		'out=$$(agentctl import /routes.json --reason "make routes-publish" 2>&1); s=$$?; echo "$$out"; \
		[ $$s -eq 0 ] || echo "$$out" | grep -q "changes nothing" || { echo "$$out" | grep -q "until it.s retired" && \
		echo "warn: a removed module'"'"'s agent pool is still routed, so the routes weren'"'"'t published (upstream U17); on local, make down-all && make up starts afresh"; }'

new-module: ## A new module, its code in src/<id>/: ID=crm (SERVICE=t10-crm PORT=… SCAFFOLD=go optional; REPO=… for its own repo)
	@$(PY) scripts/new-module.py "$(ID)" "$(SERVICE)" "$(PORT)" $(REPO)

template-update: ## Merge the template's latest (git remote template); README.md, modules/, site/ and src/ stay yours
	@scripts/template-update.sh

sync-module: ## For a module in its own repo: copy its pack out of its pinned image (MODULE=<id>, IMAGE=…)
	@scripts/sync-module.sh

pin: ## Show what each foundation image's latest is; WRITE=1 rewrites the versions.env that pins it
	@$(PY) scripts/resolve-tags.py $(if $(WRITE),--write)

backup: ## Dump every database now into ENV's backups volume (on its host, for a server)
	@$(PY) scripts/backup.py now $(ENV)

backup-pull: ## Copy ENV's newest backup here, to backups/<env>/, checked and encrypted for .sops.yaml's keys
	@$(PY) scripts/backup.py pull $(ENV)

restore: ## Put a backup back, replacing every database: FILE=backups/<env>/… CONFIRM=<env>
	@CONFIRM=$(CONFIRM) $(PY) scripts/backup.py restore $(ENV) "$(FILE)"

rotate: ## How to rotate one secret: NAME=…; APPLY=1 rotates it in ENV (then FINISH=1 for a two-phase one)
	@$(PY) scripts/secrets.py rotate $(NAME) $(if $(APPLY),$(ENV)) $(if $(FINISH),--finish)

secrets-key: ## This machine's age key and site/secrets/.sops.yaml; RECIPIENT=age1… adds a key, BREAKGLASS=1 makes one
	@$(PY) scripts/secrets.py $(if $(RECIPIENT),recipient $(RECIPIENT),key $(if $(BREAKGLASS),--breakglass))

secrets-set: ## Set one secret, typed in, not shown: make secrets-set ENV=prod NAME=LLM_API_KEY
	@$(PY) scripts/secrets.py set $(ENV) $(NAME)

secrets-edit: ## Edit an environment's encrypted secrets in an editor: make secrets-edit ENV=prod
	@$(PY) scripts/secrets.py edit $(ENV)

lint: ## Lint the template's Python and shell scripts, in Docker
	@docker run --rm -v "$(CURDIR):/w" -w /w $(RUFF) check --quiet scripts tests
	@docker run --rm -v "$(CURDIR):/w" -w /w $(SHELLCHECK) -S warning scripts/*.sh foundation/*.sh

test-template: ## The template's own tests: its scripts (tests/) and its Go kit (kit/go/), no stack needed
	@$(PY) tests/test_template.py $(if $(V),-v)
	@docker build -q kit/go >/dev/null && echo "kit/go: vet and tests passed"

# A project's own commands, and each module's: the project's files, which template updates leave alone.
-include site/project.mk $(wildcard modules/*/module.mk)

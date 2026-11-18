"""The template's own tests: its scripts, run on throwaway copies of this checkout, with no stack.

    make test-template              # these, and the Go kit's tests
    UPDATE_GOLDEN=1 make test-template   # rewrite tests/golden/ after a deliberate change, then review its diff

Each test copies the checkout's files (as git sees them, without generated/ or secrets) into a
temporary folder and runs the scripts there, as a project would. The golden files are the
bundle's module wiring for one scaffolded module: a change to them is a change every project
gets, so it should show in review. Compose is checked only where Docker is installed.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
GOLDEN = ROOT / "platform" / "tests" / "golden"
DOCKER = shutil.which("docker") is not None
PY = [sys.executable, "-I", "-B"]


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.split("\0") if f and not f.startswith(("generated/", "modules/")) and (ROOT / f).is_file()]


class Project:
    """A throwaway project made from this checkout."""

    def __init__(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="t10-template-test-")).resolve()
        for f in tracked_files():
            dest = self.dir / f
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, dest)
        for f in (self.dir / "site" / "secrets").glob("*.env"):
            f.unlink()
        # A stand-in signing key, which `secrets.py init` keeps, so local tests don't each run
        # auth-server's image to make one.
        (self.dir / "site" / "secrets" / "local.env").write_text('AUTH_SIGNING_KEY_CURRENT="stand-in"\n')

    def run(self, *cmd, check=True, **env):
        r = subprocess.run(cmd, cwd=self.dir, capture_output=True, text=True,
                           env={**os.environ, "ENV": "local", "SCRIPTED": "", "DEV": "", **env})
        if check and r.returncode != 0:
            raise AssertionError(f"{' '.join(cmd)} failed:\n{r.stdout}\n{r.stderr}")
        return r

    def script(self, name, *args, **env):
        return self.run(*PY, f"platform/scripts/{name}", *args, **env)

    def new_module(self, *args):
        return self.script("new-module.py", *args)

    def secrets(self, env="local"):
        """Every secret set, to a value named after it, so rendered files don't change between runs."""
        self.script("secrets.py", "init", env)
        path = self.dir / "site" / "secrets" / f"{env}.env"
        lines = [line if line.startswith("#") or "=" not in line else f"{line.split('=')[0]}=S_{line.split('=')[0]}"
                 for line in path.read_text().splitlines()]
        path.write_text("\n".join(lines) + "\n")

    def render(self, env="local"):
        self.secrets(env)
        self.script("render.py", env)
        return self.dir / "generated" / env

    def read(self, rel):
        return (self.dir / rel).read_text()

    def write(self, rel, text):
        (self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.dir / rel).write_text(text)

    def compose_config(self, env="local", **extra):
        r = self.run("platform/scripts/compose.sh", "config", "--format", "json", ENV=env, **extra)
        return json.loads(r.stdout)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestCase(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.close)


class FoundationOnly(TestCase):
    def test_renders_every_environment(self):
        for env in ("local", "dev", "prod"):
            bundle = self.p.render(env)
            self.assertTrue((bundle / "compose.sh").exists(), env)
            self.assertIn("MODULE_TOOL_MODULE_SERVERS=\n", (bundle / "modules.env").read_text())
        self.assertTrue((self.p.dir / "generated" / "prod" / "Caddyfile").exists())

    def test_core_alone(self):
        self.p.write("site/config/settings.env", "PROJECT_NAME=test\nFOUNDATION=\n")
        bundle = self.p.render()
        self.assertNotIn("agent-pi", (bundle / "clients.yaml").read_text())

    def test_unknown_component_is_refused(self):
        self.p.write("site/config/settings.env", "PROJECT_NAME=test\nFOUNDATION=nothing\n")
        r = self.p.run(*PY, "platform/scripts/render.py", "local", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FOUNDATION names nothing", r.stderr)

    def test_each_service_gets_only_its_own_secrets(self):
        bundle = self.p.render()
        workbench = (bundle / "secrets/workbench.env").read_text()
        self.assertIn("WORKBENCH_SESSION_KEY=S_WORKBENCH_SESSION_KEY", workbench)
        self.assertIn("DATABASE_URL=postgres://t10:S_POSTGRES_PASSWORD@postgres:5432/workbench?sslmode=disable", workbench)
        self.assertNotIn("AUTH_TOTP_KEY", workbench)
        self.assertEqual((bundle / "secrets/workbench.env").stat().st_mode & 0o777, 0o600)
        self.assertIn("path: ./secrets/workbench.env", (bundle / "secrets.yml").read_text())

    def test_a_secret_keeps_its_quoting(self):
        self.p.secrets()
        path = self.p.dir / "site/secrets/local.env"
        path.write_text(path.read_text() + 'AUTH_SIGNING_KEY_CURRENT="-----BEGIN-----\\nabc\\n-----END-----"\n')
        self.p.script("render.py", "local")
        self.assertIn('AUTH_SIGNING_KEY_CURRENT="-----BEGIN-----\\nabc\\n-----END-----"', self.p.read("generated/local/secrets/auth-server.env"))

    def test_no_livekit_without_the_component(self):
        self.p.write("site/config/settings.env", "PROJECT_NAME=test\nFOUNDATION=\n")
        bundle = self.p.render()
        self.assertNotIn("LIVEKIT", (bundle / "secrets/auth-server.env").read_text())
        self.assertFalse((bundle / "secrets/t10-livekit-agent.env").exists())

    @unittest.skipUnless(DOCKER, "needs docker")
    def test_compose_renders(self):
        self.p.secrets()
        self.assertIn("auth-server", self.p.compose_config()["services"])

    def test_port_offset_moves_local_ports_but_not_sites(self):
        self.p.write("site/config/settings.env", self.p.read("site/config/settings.env") + "PORT_OFFSET=-10000\n")
        self.p.write("site/config/local/settings.env", "COLLAB_PORT=40000\n")
        self.p.secrets()
        ports = self.p.compose_config()["services"]["auth-server"]["ports"]
        self.assertEqual([x["published"] for x in ports], ["28081"])
        moved = (self.p.dir / "generated/local/ports.env").read_text()
        self.assertIn("AUTH_PUBLIC_URL=http://localhost:28081\n", moved)
        self.assertNotIn("COLLAB_PORT", moved)
        self.assertEqual(self.p.render("prod").joinpath("ports.env").read_text().count("\n"), 1)
        self.p.write("site/config/settings.env", self.p.read("site/config/settings.env") + "PORT_OFFSET=30000\n")
        r = self.p.run(*PY, "platform/scripts/render.py", "local", check=False)
        self.assertIn("past 65535", r.stderr)


class Parts(TestCase):
    """Every part adds to the foundation's inputs the same way, site/ too."""

    def test_site_adds_and_changes_clients_routes_permissions_and_lists(self):
        self.p.write("site/clients.json", json.dumps({
            "clients": [{"id": "wechat-mini", "name": "Mini program", "type": "public", "tenant": "required",
                         "redirect_uris": ["https://mini.example/cb"]},
                        {"id": "t10-workbench", "_merge": True, "redirect_uris": ["https://wb.example/auth/callback"]}],
            "runtime_grants": {"runtimes": ["agent-ti"], "actions": ["site:read"], "audiences": ["site-svc"]}}))
        self.p.write("site/agent-routes.json", json.dumps({"agents": {"helper": {"title": "Helper", "open": True, "routes": [{"pool": "ti"}]}}}))
        self.p.write("site/permissions/site.yaml", json.dumps({"module": "site", "prefix": "site", "permissions": []}))
        self.p.write("site/part.env", "WORKBENCH_URLS=extra=http://extra:1\n")
        bundle = self.p.render()
        clients = json.loads((bundle / "clients.yaml").read_text().split("\n", 1)[1])
        by_id = {c["id"]: c for c in clients["clients"]}
        self.assertIn("wechat-mini", by_id)
        self.assertIn("https://wb.example/auth/callback", by_id["t10-workbench"]["redirect_uris"])
        self.assertGreater(len(by_id["t10-workbench"]["redirect_uris"]), 1)
        agent_ti = {r["name"]: r for r in clients["runtimes"]}["agent-ti"]
        self.assertIn("site:read", agent_ti["actions"])
        self.assertIn("helper", json.loads((bundle / "agent-routes.json").read_text())["agents"])
        self.assertTrue((bundle / "permissions/site.yaml").exists())
        self.assertIn("extra=http://extra:1", (bundle / "modules.env").read_text())

    def test_a_second_definition_needs_merge(self):
        self.p.write("site/clients.json", json.dumps({"clients": [{"id": "t10-workbench", "name": "again"}]}))
        r = self.p.run(*PY, "platform/scripts/render.py", "local", check=False)
        self.assertIn("is already defined", r.stderr)

    def test_hooks_from_every_part(self):
        self.p.write("site/hooks/post-up.sh", 'echo "$T10_PART $ENV" > site/hooks/ran\n')
        self.p.run(*PY, "platform/scripts/hook.py", "post-up")
        self.assertEqual(self.p.read("site/hooks/ran"), "site local\n")
        self.p.write("site/hooks/pre-deploy.py", "import sys; sys.exit(3)\n")
        r = self.p.run(*PY, "platform/scripts/hook.py", "pre-deploy", check=False)
        self.assertIn("site/hooks/pre-deploy.py failed (3)", r.stderr)

    def test_layers(self):
        self.p.write("site/config/uat/settings.env", "SHAPE=prod\nLAYERS=server,staging\n")
        self.p.write("site/config/staging/t10-collab.env", "FROM_STAGING=1\n")
        bundle = self.p.render("uat")
        self.assertIn("FROM_STAGING=1", (bundle / "env/t10-collab.env").read_text())
        self.p.write("site/config/uat/settings.env", "SHAPE=prod\nLAYERS=staging\n")
        r = self.p.run(*PY, "platform/scripts/lib.py", "setting", "uat", "PROJECT_NAME", check=False)
        self.assertIn("LAYERS must include server", r.stderr)

    def test_owned(self):
        self.assertEqual(self.p.script("lib.py", "owned").stdout.split(), ["README.md", "modules", "site", ".github/workflows/ci.yml"])

    def test_project_makefile(self):
        self.p.write("site/project.mk", "hello: ## Say hello\n\t@echo hello from the project\n")
        self.assertIn("hello from the project", self.p.run("make", "-s", "hello").stdout)
        listed = self.p.run("make", "-s", "help").stdout
        self.assertRegex(listed, r"(?m)^  hello +Say hello$")
        self.assertRegex(listed, r"(?m)^  up +Start the stack")


class NewModule(TestCase):
    def test_writes_only_what_is_particular_to_it(self):
        self.p.new_module("crm")
        files = sorted(str(f.relative_to(self.p.dir / "modules" / "crm")) for f in (self.p.dir / "modules" / "crm").rglob("*")
                       if f.is_file() and not f.relative_to(self.p.dir / "modules" / "crm").parts[0] == "src")
        self.assertEqual(files, ["README.md", "config/k8s-local/settings.env", "config/local/settings.env", "config/server/settings.env",
                                 "config/t10-crm.env", "source.env", "versions.env"])
        self.assertEqual(self.p.read("modules/crm/source.env").split("SRC=")[1].strip(), "src")
        self.assertIn("PORT=18100", self.p.read("modules/crm/src/module/module.env"))
        self.assertFalse((self.p.dir / "modules/crm/src/module/clients.fragment.json").exists())
        self.assertNotIn("__", self.p.read("modules/crm/src/main.go"))
        self.assertEqual(broken_links(self.p.dir, ["modules/crm/README.md", "modules/crm/src/README.md"]), [])

    def test_next_module_gets_the_next_port(self):
        self.p.new_module("crm")
        self.p.new_module("shop")
        self.assertIn("PORT=18101", self.p.read("modules/shop/src/module/module.env"))
        self.assertIn("SHOP_PORT=38101", self.p.read("modules/shop/config/local/settings.env"))

    def test_unknown_scaffold(self):
        r = self.p.run(*PY, "platform/scripts/new-module.py", "crm", check=False, SCAFFOLD="cobol")
        self.assertIn("the scaffolds are go", r.stderr)

    def test_refuses_bad_or_existing(self):
        r = self.p.run(*PY, "platform/scripts/new-module.py", "Bad_ID", check=False)
        self.assertIn("an ID is lowercase", r.stderr)
        self.p.new_module("crm")
        r = self.p.run(*PY, "platform/scripts/new-module.py", "crm", check=False)
        self.assertIn("already exists", r.stderr)

    def test_own_repo_waits_for_its_pack(self):
        self.p.new_module("crm", "t10-crm", "18076", "https://example.com/t10-crm.git")
        self.assertIn("REPO=https://example.com/t10-crm.git", self.p.read("modules/crm/source.env"))
        self.assertFalse((self.p.dir / "modules" / "crm" / "src").exists())
        bundle = self.p.render()
        self.assertNotIn("crm", (bundle / "modules.env").read_text())


class StandardWiring(TestCase):
    def setUp(self):
        super().setUp()
        self.p.new_module("crm")

    def test_golden(self):
        """The bundle's wiring for one module. UPDATE_GOLDEN=1 rewrites it."""
        bundle = self.p.render()
        names = ["modules/crm/standard/base.yml", "modules/crm/standard/local.yml", "secrets/t10-crm.env", "secrets/crm-seed.env", "modules.env",
                 "agent-routes.json", "clients.yaml", "modules/crm/pack/agents/crm/agent.json"]
        for name in names:
            got = (bundle / name).read_text()
            golden = GOLDEN / "local" / name
            if os.environ.get("UPDATE_GOLDEN"):
                golden.parent.mkdir(parents=True, exist_ok=True)
                golden.write_text(got)
            with self.subTest(name):
                self.assertEqual(got, golden.read_text(), f"{name} changed: UPDATE_GOLDEN=1 make test-template, then review the diff")

    def test_standard_secrets(self):
        self.p.script("secrets.py", "init", "local")
        values = self.p.read("site/secrets/local.env")
        for name in ("CRM_DB_PASSWORD", "T10_CRM_SECRET", "AGENT_TI_CRM_SECRET", "CRM_WEB_CLIENT_SECRET", "CRM_SESSION_KEY"):
            self.assertRegex(values, rf"(?m)^{name}=.+$")

    def test_module_secrets_json_adds_and_replaces(self):
        self.p.write("modules/crm/secrets.json", json.dumps({"secrets": [
            {"name": "CRM_DATA_KEY", "generate": "b64key", "consumers": ["t10-crm"], "rotate": "Never."},
            {"name": "CRM_SESSION_KEY", "generate": "hex32", "consumers": ["t10-crm"], "rotate": "Roll."}]}))
        r = self.p.script("secrets.py", "rotate", "CRM_SESSION_KEY")
        self.assertIn("Roll.", r.stdout)
        self.p.script("secrets.py", "init", "local")
        self.assertRegex(self.p.read("site/secrets/local.env"), r"(?m)^CRM_DATA_KEY=.+$")

    def capabilities(self, value, extra=""):
        env = self.p.read("modules/crm/src/module/module.env")
        self.p.write("modules/crm/src/module/module.env", env.replace("CAPABILITIES=web,tools,agent,database", f"CAPABILITIES={value}") + extra)

    def test_without_database(self):
        self.capabilities("web,tools,agent")
        bundle = self.p.render()
        base = (bundle / "modules/crm/standard/base.yml").read_text()
        self.assertNotIn("crm-db", base)
        self.assertNotIn("CRM_DB_PASSWORD", base)
        self.assertNotIn("CRM_DB_PASSWORD", self.p.read("site/secrets/local.env"))

    def test_a_pack_before_capabilities(self):
        """A pack written before v0.6.0: no PACK_VERSION or CAPABILITIES, AGENT and DATABASE=false."""
        env = self.p.read("modules/crm/src/module/module.env")
        env = "\n".join(line for line in env.splitlines() if not line.startswith(("PACK_VERSION", "CAPABILITIES", "AGENTS", "AGENT_TITLE_")))
        self.p.write("modules/crm/src/module/module.env", env + "\nAGENT=crm\nAGENT_TITLE=Crm\nAGENT_RUNTIME=agent-ti-crm\nDATABASE=false\n")
        bundle = self.p.render()
        self.assertNotIn("crm-db", (bundle / "modules/crm/standard/base.yml").read_text())
        self.assertIn('"crm"', (bundle / "agent-routes.json").read_text())
        self.assertIn("MODULE_TOOL_MODULE_SERVERS=crm", (bundle / "modules.env").read_text())

    def test_capabilities_and_database_together_are_refused(self):
        self.capabilities("web,tools,agent", "DATABASE=false\n")
        r = self.p.run(*PY, "platform/scripts/render.py", "local", check=False)
        self.assertIn("drop DATABASE", r.stderr)

    def test_unknown_pack_version_is_refused(self):
        env = self.p.read("modules/crm/src/module/module.env")
        self.p.write("modules/crm/src/module/module.env", env.replace("PACK_VERSION=1", "PACK_VERSION=99"))
        r = self.p.run(*PY, "platform/scripts/render.py", "local", check=False)
        self.assertIn("its pack is version 99", r.stderr)

    def test_tools_only(self):
        """No web app, agent or database: none of their wiring, secrets or list entries."""
        self.capabilities("tools")
        bundle = self.p.render()
        lists = (bundle / "modules.env").read_text()
        self.assertIn("MODULE_TOOL_MODULE_SERVERS=crm", lists)
        self.assertIn("MODULE_WORKBENCH_URLS=automations=", lists)
        self.assertNotIn("crm=http://t10-crm", lists.split("MODULE_WORKBENCH_URLS=")[1].split("\n")[0])
        self.assertNotIn("MODULE_APP_URLS=crm", lists)
        self.assertNotIn('"crm"', (bundle / "agent-routes.json").read_text())
        self.assertNotIn("t10-crm-web", (bundle / "clients.yaml").read_text())
        self.assertNotIn("agent-ti-crm", (bundle / "clients.yaml").read_text())
        self.assertIn("SCRIPTED_TOOL_CRM", (bundle / "modules/crm/standard/scripted.yml").read_text())
        base = (bundle / "modules/crm/standard/base.yml").read_text()
        self.assertNotIn("CRM_PUBLIC_URL", base)
        self.assertNotIn("workbench:", base)
        self.assertNotIn("t10-agents", base)
        values = self.p.read("site/secrets/local.env")
        self.assertNotRegex(values, r"(?m)^CRM_WEB_CLIENT_SECRET=")
        self.assertNotRegex(values, r"(?m)^CRM_SESSION_KEY=")
        self.assertNotRegex(values, r"(?m)^AGENT_TI_CRM_SECRET=")

    def test_web_only(self):
        """No tools: nothing for the tools gateway or the harnesses' grants."""
        self.capabilities("web,database")
        bundle = self.p.render()
        lists = (bundle / "modules.env").read_text()
        self.assertIn("MODULE_TOOL_MODULE_SERVERS=\n", lists)
        self.assertIn("MODULE_GRANT_ACTIONS=\n", lists)
        self.assertIn("MODULE_APP_URLS=crm=", lists)
        self.assertNotIn("ai-gateway-tools", (bundle / "modules/crm/standard/base.yml").read_text())
        self.assertFalse((bundle / "modules/crm/standard/scripted.yml").exists())

    def test_two_agents_and_a_worker(self):
        catalog = self.p.dir / "modules/crm/src/module/permissions/crm.yaml"
        doc = json.loads(catalog.read_text())
        doc["agent"]["actions"] = ["crm:read", "crm:write"]
        catalog.write_text(json.dumps(doc))
        self.capabilities("web,tools,agent,database",
                          "AGENTS=crm,crm-intake\nAGENT_TITLE_CRM_INTAKE=Intake\nAGENT_ACTIONS_CRM_INTAKE=crm:read\nSERVICES=t10-crm-worker\n")
        shutil.copytree(self.p.dir / "modules/crm/src/module/agents/crm", self.p.dir / "modules/crm/src/module/agents/crm-intake")
        bundle = self.p.render()
        routes = json.loads((bundle / "agent-routes.json").read_text())
        self.assertEqual(routes["agents"]["crm-intake"]["title"], "Intake")
        self.assertEqual(routes["pools"]["crm-intake"]["audience"], "agent-ti-crm-intake")
        main_agent = json.loads((bundle / "modules/crm/pack/agents/crm/agent.json").read_text())
        self.assertIn("crm:write", main_agent["grants"]["actions"].split(","))
        intake = json.loads((bundle / "modules/crm/pack/agents/crm-intake/agent.json").read_text())
        self.assertIn("crm:read", intake["grants"]["actions"].split(","))
        self.assertNotIn("crm:write", intake["grants"]["actions"].split(","))
        runtimes = {r["name"]: r for r in json.loads((bundle / "clients.yaml").read_text().split("\n", 1)[1])["runtimes"]}
        self.assertIn("crm:write", runtimes["agent-ti-crm"]["actions"])
        self.assertIn("crm:read", runtimes["agent-ti-crm-intake"]["actions"])
        self.assertNotIn("crm:write", runtimes["agent-ti-crm-intake"]["actions"])
        agent_ti = (bundle / "secrets/agent-ti.env").read_text()
        self.assertIn("CRM_AUTH_CLIENT_SECRET=S_AGENT_TI_CRM_SECRET", agent_ti)
        self.assertIn("CRM_INTAKE_AUTH_CLIENT_SECRET=S_AGENT_TI_CRM_INTAKE_SECRET", agent_ti)
        worker = (bundle / "secrets/t10-crm-worker.env").read_text()
        self.assertIn("DATABASE_URL=postgres://crm:S_CRM_DB_PASSWORD@", worker)
        self.assertIn("AUTH_CLIENT_SECRET=S_T10_CRM_SECRET", worker)
        self.assertNotIn("SESSION_KEY", worker)
        base = (bundle / "modules/crm/standard/base.yml").read_text()
        self.assertIn("/module-agents/crm-intake:ro", base)
        self.assertIn("  t10-crm-worker:\n", base)
        self.assertIn("  t10-crm-worker:\n", (bundle / "modules/crm/standard/local.yml").read_text())
        self.assertIn("  t10-crm-worker:\n", (self.p.render("prod") / "modules/crm/standard/server.yml").read_text())

    def test_pack_secrets_init_db_and_hooks(self):
        """A module pack can ship its own secrets.json, init-db.sh and hooks/."""
        self.p.write("modules/crm/src/module/secrets.json", json.dumps({"secrets": [
            {"name": "CRM_DATA_KEY", "generate": "b64key", "consumers": ["t10-crm"], "rotate": "Keep.",
             "env": {"t10-crm": {"CRM_DATA_KEY": "${CRM_DATA_KEY}"}}}]}))
        self.p.write("modules/crm/src/module/init-db.sh", "echo init-db\n")
        self.p.write("modules/crm/src/module/hooks/post-up.sh", 'echo "$T10_MODULE" > site/pack-hook\n')
        bundle = self.p.render()
        self.assertIn("CRM_DATA_KEY=S_CRM_DATA_KEY", (bundle / "secrets/t10-crm.env").read_text())
        self.assertIn("./modules/crm/pack/init-db.sh:/module-init-db.sh:ro", (bundle / "modules/crm/standard/base.yml").read_text())
        self.p.run(*PY, "platform/scripts/hook.py", "post-up")
        self.assertEqual(self.p.read("site/pack-hook"), "crm\n")

    def test_requires(self):
        self.p.write("site/config/settings.env", "PROJECT_NAME=test\nFOUNDATION=\n")
        self.capabilities("web,tools,agent,database", "REQUIRES=livekit\n")
        r = self.p.run(*PY, "platform/scripts/render.py", "local", check=False)
        self.assertIn("modules/crm needs livekit", r.stderr)
        self.p.write("site/config/settings.env", "PROJECT_NAME=test\nFOUNDATION=assistant,livekit\n")
        self.p.render()

    def test_grant_said_once_reaches_every_place(self):
        catalog = self.p.dir / "modules/crm/src/module/permissions/crm.yaml"
        doc = json.loads(catalog.read_text())
        doc["agent"]["actions"].append("crm:write")
        catalog.write_text(json.dumps(doc))
        bundle = self.p.render()
        self.assertIn("crm:read,crm:write", (bundle / "modules.env").read_text())
        agent = json.loads((bundle / "modules/crm/pack/agents/crm/agent.json").read_text())
        self.assertIn("crm:write", agent["grants"]["actions"].split(","))
        runtimes = {r["name"]: r for r in json.loads((bundle / "clients.yaml").read_text().split("\n", 1)[1])["runtimes"]}
        for name in ("agent-ti-crm", "agent-ti", "agent-pi"):
            self.assertIn("crm:write", runtimes[name]["actions"], name)
            self.assertIn("t10-crm", runtimes[name]["audiences"], name)
        # The pack in modules/<id>/src/ is read as it is: only the bundle's copy changes.
        self.assertNotIn("crm:write", self.p.read("modules/crm/src/module/agents/crm/agent.json"))

    @unittest.skipUnless(DOCKER, "needs docker")
    def test_module_compose_overrides_standard(self):
        self.p.write("modules/crm/compose/base.yml", "services:\n  t10-crm:\n    read_only: false\n    environment:\n      EXTRA: yes-please\n")
        self.p.secrets()
        svc = self.p.compose_config()["services"]["t10-crm"]
        self.assertFalse(svc.get("read_only", False))
        self.assertEqual(svc["environment"]["EXTRA"], "yes-please")
        self.assertIn("DATABASE_URL", svc["environment"])
        self.assertEqual(svc["build"]["additional_contexts"]["kit"], str(self.p.dir / "platform" / "kit" / "go"))

    @unittest.skipUnless(DOCKER, "needs docker")
    def test_check_passes(self):
        self.p.secrets()
        r = self.p.run(*PY, "platform/scripts/check.py", check=False, SCRIPTED="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(DOCKER, "needs docker, for docker compose config")
class Kubernetes(TestCase):
    """k8s-local's objects, written by platform/scripts/kube.py from the Compose bundle; no cluster needed."""

    def setUp(self):
        super().setUp()
        self.p.new_module("crm")
        self.p.secrets("k8s-local")
        self.bundle = self.p.render("k8s-local")

    def objects(self, service):
        """A service's objects, by kind, as kube.py makes them before writing them as YAML."""
        code = ("import json, sys; sys.path.insert(0, 'platform/scripts'); import kube; "
                f"print(json.dumps(kube.manifests('k8s-local')[0]['k8s/{service}.yaml']))")
        return {f"{o['kind']}/{o['metadata']['name']}": o for o in json.loads(self.p.run(*PY, "-c", code, ENV="k8s-local").stdout)}

    def test_each_service_as_its_kind(self):
        crm = self.objects("t10-crm")
        container = crm["Deployment/t10-crm"]["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["imagePullPolicy"], "Never")
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        # Headless: the name resolves to the pod, so any port answers, as on Compose's network.
        self.assertEqual(crm["Service/t10-crm"]["spec"]["clusterIP"], "None")
        self.assertEqual(crm["Service/t10-crm-public"]["spec"]["ports"][0]["port"], 36100)
        self.assertEqual(set(self.objects("crm-db")), {"Job/crm-db"})
        self.assertEqual(set(self.objects("seed")), {"Job/seed"})

    def test_published_on_its_own_ports(self):
        text = (self.bundle / "k8s" / "t10-crm.yaml").read_text()
        self.assertIn("name: t10-crm-public", text)
        self.assertIn("port: 36100", text)
        self.assertIn("http://localhost:36081", (self.bundle / "k8s" / "auth-server.yaml").read_text())

    def test_no_secret_on_disk(self):
        written = "".join(f.read_text() for f in [self.bundle / "kustomization.yaml", *(self.bundle / "k8s").glob("*.yaml")])
        self.assertNotIn("S_CRM_DB_PASSWORD", written)
        self.assertIn("name: t10-crm-secrets", written)
        code = ("import json, sys; sys.path.insert(0, 'platform/scripts'); import kube; "
                "print(json.dumps(kube.secrets('k8s-local', kube.compose_config('k8s-local'))))")
        made = {s["metadata"]["name"]: s["stringData"] for s in json.loads(self.p.run(*PY, "-c", code, ENV="k8s-local").stdout)}
        self.assertIn("S_CRM_DB_PASSWORD", made["t10-crm-secrets"]["DATABASE_URL"])

    def test_agent_folder_mounted_from_a_config_map(self):
        spec = self.objects("t10-agents")["Job/t10-agents"]["spec"]["template"]["spec"]
        items = {i["path"] for v in spec["volumes"] if "configMap" in v for i in v["configMap"]["items"]}
        self.assertIn("agent.json", items)
        self.assertIn("files-modules-crm-pack-agents-crm", (self.bundle / "kustomization.yaml").read_text())

    def test_local_has_none(self):
        self.assertFalse((self.p.render("local") / "kustomization.yaml").exists())

    def test_a_server_cluster_is_refused(self):
        self.p.write("site/config/dev/settings.env", self.p.read("site/config/dev/settings.env") + "TARGET=k8s\n")
        r = self.p.run(*PY, "platform/scripts/render.py", "dev", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SHAPE=local", r.stderr)

    @unittest.skipUnless(shutil.which("kubectl"), "needs kubectl")
    def test_check_passes(self):
        r = self.p.run(*PY, "platform/scripts/check.py", check=False, ENV="k8s-local", SCRIPTED="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(DOCKER, "needs docker, for sops and age")
class EncryptedSecrets(TestCase):
    """A server environment's secrets, encrypted with SOPS and age, with a throwaway key."""

    def setUp(self):
        super().setUp()
        self.key = self.p.dir / "age" / "keys.txt"
        self.env = {"SOPS_AGE_KEY_FILE": str(self.key)}
        self.p.script("secrets.py", "key", **self.env)

    def test_init_encrypts_and_nothing_decrypted_stays(self):
        self.assertTrue(self.key.exists())
        self.assertIn("age1", self.p.read("site/secrets/.sops.yaml"))
        self.p.script("secrets.py", "init", "prod", **self.env)
        enc = self.p.read("site/secrets/prod.enc.env")
        self.assertIn("POSTGRES_PASSWORD=ENC[AES256_GCM", enc)
        self.assertIn("AUTH_SIGNING_KEY_CURRENT=ENC[", enc)
        self.assertFalse((self.p.dir / "site/secrets/prod.env").exists())
        self.p.script("render.py", "prod", **self.env)
        self.assertFalse((self.p.dir / "generated/prod/secrets.env").exists())
        self.assertFalse((self.p.dir / "generated/prod/secrets").exists())
        self.p.script("render.py", "prod", T10_BUNDLE_SECRETS="1", **self.env)
        auth = self.p.read("generated/prod/secrets/auth-server.env")
        self.assertRegex(auth, r'AUTH_SIGNING_KEY_CURRENT="-----BEGIN EC PRIVATE KEY-----\\n')

    def test_set_check_and_rotate(self):
        self.p.script("secrets.py", "init", "prod", **self.env)
        r = self.p.run(*PY, "platform/scripts/secrets.py", "check", "prod", check=False, **self.env)
        self.assertIn("LLM_API_KEY is not set", r.stderr)
        subprocess.run([*PY, "platform/scripts/secrets.py", "set", "prod", "LLM_API_KEY"], input="sk-test\n", text=True, check=True,
                       cwd=self.p.dir, capture_output=True, env={**os.environ, **self.env})
        values = "import sys, json; sys.path.insert(0, 'platform/scripts'); import lib; print(json.dumps(lib.secret_values('prod')))"
        before = json.loads(self.p.run(*PY, "-c", values, **self.env).stdout)
        self.p.script("secrets.py", "rotate", "WORKBENCH_SESSION_KEY", "prod", **self.env)
        after = json.loads(self.p.run(*PY, "-c", values, **self.env).stdout)
        self.assertEqual([k for k in after if after[k] != before.get(k)], ["WORKBENCH_SESSION_KEY"])
        self.assertEqual(after["LLM_API_KEY"], "sk-test")
        r = self.p.run(*PY, "platform/scripts/secrets.py", "check", "prod", check=False, **self.env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_compose_runs_with_them_then_drops_them(self):
        self.p.script("secrets.py", "init", "prod", **self.env)
        svc = self.p.compose_config("prod", **self.env)["services"]["auth-server"]
        self.assertTrue(svc["environment"]["AUTH_SIGNING_KEY_CURRENT"].startswith("-----BEGIN EC PRIVATE KEY-----\n"))
        self.assertTrue(svc["environment"]["DATABASE_URL"].startswith("postgres://t10:"))
        self.assertFalse((self.p.dir / "generated/prod/secrets").exists())
        self.assertFalse((self.p.dir / "generated/prod/secrets.env").exists())

    def test_signing_key_rotation(self):
        self.p.script("secrets.py", "init", "prod", **self.env)
        values = "import sys, json; sys.path.insert(0, 'platform/scripts'); import lib; print(json.dumps(lib.secret_values('prod')))"
        first = json.loads(self.p.run(*PY, "-c", values, **self.env).stdout)
        self.p.script("secrets.py", "rotate", "AUTH_SIGNING_KEY_CURRENT", "prod", **self.env)
        middle = json.loads(self.p.run(*PY, "-c", values, **self.env).stdout)
        self.assertEqual(middle["AUTH_SIGNING_KEY_CURRENT"], first["AUTH_SIGNING_KEY_CURRENT"])
        self.assertTrue(middle["AUTH_SIGNING_KEY_NEXT"].startswith("-----BEGIN EC PRIVATE KEY-----"))
        self.p.script("secrets.py", "rotate", "AUTH_SIGNING_KEY_CURRENT", "prod", "--finish", **self.env)
        last = json.loads(self.p.run(*PY, "-c", values, **self.env).stdout)
        self.assertEqual(last["AUTH_SIGNING_KEY_CURRENT"], middle["AUTH_SIGNING_KEY_NEXT"])
        self.assertEqual(last["AUTH_SIGNING_KEY_NEXT"], "")

    def test_plain_server_secrets_fail_check(self):
        (self.p.dir / "site/secrets/.sops.yaml").unlink()
        self.p.script("secrets.py", "init", "dev", **self.env)
        r = self.p.run(*PY, "platform/scripts/secrets.py", "check", "dev", check=False, **self.env)
        self.assertIn("is plain text", r.stderr)

    def test_another_recipient(self):
        self.p.script("secrets.py", "init", "prod", **self.env)
        other = subprocess.run([str(self.p.dir / "platform/scripts/sops.sh"), "age-keygen"], capture_output=True, text=True, check=True).stdout
        pub = next(line.split(":", 1)[1].strip() for line in other.splitlines() if line.startswith("# public key:"))
        self.p.script("secrets.py", "recipient", pub, **self.env)
        self.assertIn(pub, self.p.read("site/secrets/.sops.yaml"))
        self.assertIn(pub, self.p.read("site/secrets/prod.enc.env"))
        other_key = self.p.dir / "age" / "other.txt"
        other_key.write_text(other)
        r = self.p.run(*PY, "-c", "import sys; sys.path.insert(0, 'platform/scripts'); import lib; print(lib.secret_values('prod')['POSTGRES_PASSWORD'][:4])",
                       SOPS_AGE_KEY_FILE=str(other_key))
        self.assertEqual(len(r.stdout.strip()), 4)


@unittest.skipUnless(DOCKER, "needs docker")
class Alone(TestCase):
    """Gate 2: a module run alone keeps the contract, and its pack is checked."""

    def test_new_module_keeps_the_contract_alone(self):
        self.p.write("site/config/settings.env", f"PROJECT_NAME=test{os.getpid()}\nFOUNDATION=\n")
        self.p.new_module("crm")
        self.addCleanup(self.p.run, *PY, "platform/scripts/alone.py", "crm", "down", check=False)
        self.p.run(*PY, "platform/scripts/alone.py", "crm", "up", QUIET="1")
        r = self.p.run(*PY, "platform/scripts/contract.py", "crm", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("crm_whoami: an agent with the catalog's actions may call it", r.stdout)

    def test_a_broken_pack_fails(self):
        self.p.new_module("crm")
        env = self.p.dir / "modules/crm/src/module/module.env"
        env.write_text(env.read_text().replace("PUBLIC_URL_SETTING=CRM_PUBLIC_URL", "PUBLIC_URL_SETTING=APP_URL"))
        r = self.p.run(*PY, "platform/scripts/contract.py", "crm", "http://127.0.0.1:9", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL PUBLIC_URL_SETTING is CRM_PUBLIC_URL", r.stdout)


def broken_links(root, files):
    """Each relative Markdown link in files that names no file, as "file: link"."""
    out = []
    for f in files:
        for link in re.findall(r"\]\(([^)\s]+)\)", (root / f).read_text()):
            target = link.split("#")[0]
            if target and "://" not in target and "<" not in target and not (root / f).parent.joinpath(target).exists():
                out.append(f"{f}: {link}")
    return out


class Docs(unittest.TestCase):
    """The docs say where things are now: no link to a file that isn't there, and no path from
    before a layout change. The CHANGELOG is history, so it keeps the old paths."""

    STALE = (
        # src/<id>, src/<repo> or src/crm at the root, not inside modules/<id>/.
        (re.compile(r"(?<![\w/])src/(?:<\w+>|crm\b)"), "modules/<id>/src/"),
        (re.compile(r"\.\./\.\./kit/go"), "../../../platform/kit/go"),
    )

    def setUp(self):
        self.files = [f for f in tracked_files() if f.endswith((".md", ".py", ".sh", ".yml", "Dockerfile", "go.mod"))
                      and f != "platform/CHANGELOG.md" and f != "platform/tests/test_template.py"]

    def test_links_resolve(self):
        # A scaffold's README is read from modules/<id>/src/, where NewModule checks its links.
        md = [f for f in self.files if f.endswith(".md") and not f.startswith("platform/scripts/scaffold/")]
        self.assertEqual(broken_links(ROOT, md), [])

    def test_no_stale_paths(self):
        found = [f"{f}:{n}: {line.strip()[:120]} (now {now})" for f in self.files
                 for n, line in enumerate((ROOT / f).read_text().splitlines(), 1)
                 for pattern, now in self.STALE if pattern.search(line)]
        self.assertEqual(found, [])


class TemplateUpdate(unittest.TestCase):
    """make template-update: the template's files come from it; the project's stay its own."""

    def git(self, cwd, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                              cwd=cwd, capture_output=True, text=True, check=True).stdout

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="t10-template-update-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.template = Project()
        self.addCleanup(self.template.close)
        self.git(self.template.dir, "init", "-q", "-b", "main")
        self.git(self.template.dir, "add", "-A")
        self.git(self.template.dir, "commit", "-qm", "template")
        self.project = self.tmp / "project"
        self.git(self.tmp, "clone", "-q", "-o", "template", str(self.template.dir), "project")

    def update(self, **env):
        return subprocess.run(["platform/scripts/template-update.sh"], cwd=self.project, capture_output=True, text=True, check=True,
                              env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", **env}).stdout

    def test_takes_the_latest_release_and_shows_its_notes(self):
        changelog = self.template.dir / "platform/CHANGELOG.md"
        changelog.write_text(changelog.read_text() + "\n## v9.0.0\n\n- Do this first.\n")
        self.git(self.template.dir, "commit", "-qam", "v9")
        self.git(self.template.dir, "tag", "v9.0.0")
        (self.template.dir / "platform/docs/guide.md").write_text("unreleased\n")
        self.git(self.template.dir, "commit", "-qam", "after v9")
        out = self.update()
        self.assertIn("merged template/tags/v9.0.0", out)
        self.assertIn("Do this first.", out)
        self.assertNotEqual((self.project / "platform/docs/guide.md").read_text(), "unreleased\n")
        self.assertIn("merged template/main", self.update(REF="main"))
        self.assertEqual((self.project / "platform/docs/guide.md").read_text(), "unreleased\n")

    def test_merges_template_and_keeps_project(self):
        (self.project / "site/config/settings.env").write_text("PROJECT_NAME=mine\n")
        (self.project / "README.md").write_text("# Mine\n")
        self.git(self.project, "commit", "-qam", "project")
        (self.template.dir / "platform/docs/guide.md").write_text("new guide\n")
        (self.template.dir / "site/config/settings.env").write_text("PROJECT_NAME=changed-in-template\n")
        (self.template.dir / "README.md").write_text("# Template\n")
        self.git(self.template.dir, "commit", "-qam", "update")
        self.update()
        self.assertEqual((self.project / "platform/docs/guide.md").read_text(), "new guide\n")
        self.assertEqual((self.project / "site/config/settings.env").read_text(), "PROJECT_NAME=mine\n")
        self.assertEqual((self.project / "README.md").read_text(), "# Mine\n")


if __name__ == "__main__":
    unittest.main()

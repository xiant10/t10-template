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
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden"
DOCKER = shutil.which("docker") is not None
PY = [sys.executable, "-I", "-B"]


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.split("\0") if f and not f.startswith(("generated/", "src/", "modules/")) and (ROOT / f).is_file()]


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

    def run(self, *cmd, check=True, **env):
        r = subprocess.run(cmd, cwd=self.dir, capture_output=True, text=True,
                           env={**os.environ, "ENV": "local", "SCRIPTED": "", "DEV": "", **env})
        if check and r.returncode != 0:
            raise AssertionError(f"{' '.join(cmd)} failed:\n{r.stdout}\n{r.stderr}")
        return r

    def script(self, name, *args, **env):
        return self.run(*PY, f"scripts/{name}", *args, **env)

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
        r = self.run("scripts/compose.sh", "config", "--format", "json", ENV=env, **extra)
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
        r = self.p.run(*PY, "scripts/render.py", "local", check=False)
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

    def test_livekit_placeholder_without_the_component(self):
        self.p.write("site/config/settings.env", "PROJECT_NAME=test\nFOUNDATION=\n")
        bundle = self.p.render()
        self.assertIn("LIVEKIT_API_SECRET=livekit-off", (bundle / "secrets/auth-server.env").read_text())
        self.assertFalse((bundle / "secrets/t10-livekit-agent.env").exists())

    @unittest.skipUnless(DOCKER, "needs docker")
    def test_compose_renders(self):
        self.p.secrets()
        self.assertIn("auth-server", self.p.compose_config()["services"])


class NewModule(TestCase):
    def test_writes_only_what_is_particular_to_it(self):
        self.p.new_module("crm")
        files = sorted(str(f.relative_to(self.p.dir / "modules" / "crm")) for f in (self.p.dir / "modules" / "crm").rglob("*") if f.is_file())
        self.assertEqual(files, ["README.md", "compose/scripted.yml", "config/k8s-local/settings.env", "config/local/settings.env", "config/server/settings.env",
                                 "config/t10-crm.env", "source.env", "versions.env"])
        self.assertEqual(self.p.read("modules/crm/source.env").split("SRC=")[1].strip(), "crm")
        self.assertIn("PORT=18100", self.p.read("src/crm/module/module.env"))
        self.assertNotIn("__", self.p.read("src/crm/main.go"))

    def test_next_module_gets_the_next_port(self):
        self.p.new_module("crm")
        self.p.new_module("shop")
        self.assertIn("PORT=18101", self.p.read("src/shop/module/module.env"))
        self.assertIn("SHOP_PORT=38101", self.p.read("modules/shop/config/local/settings.env"))

    def test_refuses_bad_or_existing(self):
        r = self.p.run(*PY, "scripts/new-module.py", "Bad_ID", check=False)
        self.assertIn("an ID is lowercase", r.stderr)
        self.p.new_module("crm")
        r = self.p.run(*PY, "scripts/new-module.py", "crm", check=False)
        self.assertIn("already exists", r.stderr)

    def test_own_repo_waits_for_its_pack(self):
        self.p.new_module("crm", "t10-crm", "18076", "https://example.com/t10-crm.git")
        self.assertIn("REPO=https://example.com/t10-crm.git", self.p.read("modules/crm/source.env"))
        self.assertFalse((self.p.dir / "src" / "crm").exists())
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

    def test_without_database(self):
        self.p.write("src/crm/module/module.env", self.p.read("src/crm/module/module.env") + "DATABASE=false\n")
        bundle = self.p.render()
        base = (bundle / "modules/crm/standard/base.yml").read_text()
        self.assertNotIn("crm-db", base)
        self.assertNotIn("CRM_DB_PASSWORD", base)
        self.assertNotIn("CRM_DB_PASSWORD", self.p.read("site/secrets/local.env"))

    def test_grant_said_once_reaches_every_place(self):
        catalog = self.p.dir / "src/crm/module/permissions/crm.yaml"
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
        # The pack in src/ is read as it is: only the bundle's copy changes.
        self.assertNotIn("crm:write", self.p.read("src/crm/module/agents/crm/agent.json"))

    @unittest.skipUnless(DOCKER, "needs docker")
    def test_module_compose_overrides_standard(self):
        self.p.write("modules/crm/compose/base.yml", "services:\n  t10-crm:\n    read_only: false\n    environment:\n      EXTRA: yes-please\n")
        self.p.secrets()
        svc = self.p.compose_config()["services"]["t10-crm"]
        self.assertFalse(svc.get("read_only", False))
        self.assertEqual(svc["environment"]["EXTRA"], "yes-please")
        self.assertIn("DATABASE_URL", svc["environment"])
        self.assertEqual(svc["build"]["additional_contexts"]["kit"], str(self.p.dir / "kit" / "go"))

    @unittest.skipUnless(DOCKER, "needs docker")
    def test_check_passes(self):
        self.p.secrets()
        r = self.p.run(*PY, "scripts/check.py", check=False, SCRIPTED="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(DOCKER, "needs docker, for docker compose config")
class Kubernetes(TestCase):
    """k8s-local's objects, written by scripts/kube.py from the Compose bundle; no cluster needed."""

    def setUp(self):
        super().setUp()
        self.p.new_module("crm")
        self.p.secrets("k8s-local")
        self.bundle = self.p.render("k8s-local")

    def objects(self, service):
        """A service's objects, by kind, as kube.py makes them before writing them as YAML."""
        code = ("import json, sys; sys.path.insert(0, 'scripts'); import kube; "
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
        code = ("import json, sys; sys.path.insert(0, 'scripts'); import kube; "
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
        r = self.p.run(*PY, "scripts/render.py", "dev", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SHAPE=local", r.stderr)

    @unittest.skipUnless(shutil.which("kubectl"), "needs kubectl")
    def test_check_passes(self):
        r = self.p.run(*PY, "scripts/check.py", check=False, ENV="k8s-local", SCRIPTED="1")
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
        r = self.p.run(*PY, "scripts/secrets.py", "check", "prod", check=False, **self.env)
        self.assertIn("LLM_API_KEY is not set", r.stderr)
        subprocess.run([*PY, "scripts/secrets.py", "set", "prod", "LLM_API_KEY"], input="sk-test\n", text=True, check=True,
                       cwd=self.p.dir, capture_output=True, env={**os.environ, **self.env})
        values = "import sys, json; sys.path.insert(0, 'scripts'); import lib; print(json.dumps(lib.secret_values('prod')))"
        before = json.loads(self.p.run(*PY, "-c", values, **self.env).stdout)
        self.p.script("secrets.py", "rotate", "WORKBENCH_SESSION_KEY", "prod", **self.env)
        after = json.loads(self.p.run(*PY, "-c", values, **self.env).stdout)
        self.assertEqual([k for k in after if after[k] != before.get(k)], ["WORKBENCH_SESSION_KEY"])
        self.assertEqual(after["LLM_API_KEY"], "sk-test")
        r = self.p.run(*PY, "scripts/secrets.py", "check", "prod", check=False, **self.env)
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
        values = "import sys, json; sys.path.insert(0, 'scripts'); import lib; print(json.dumps(lib.secret_values('prod')))"
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
        r = self.p.run(*PY, "scripts/secrets.py", "check", "dev", check=False, **self.env)
        self.assertIn("is plain text", r.stderr)

    def test_another_recipient(self):
        self.p.script("secrets.py", "init", "prod", **self.env)
        other = subprocess.run([str(self.p.dir / "scripts/sops.sh"), "age-keygen"], capture_output=True, text=True, check=True).stdout
        pub = next(line.split(":", 1)[1].strip() for line in other.splitlines() if line.startswith("# public key:"))
        self.p.script("secrets.py", "recipient", pub, **self.env)
        self.assertIn(pub, self.p.read("site/secrets/.sops.yaml"))
        self.assertIn(pub, self.p.read("site/secrets/prod.enc.env"))
        other_key = self.p.dir / "age" / "other.txt"
        other_key.write_text(other)
        r = self.p.run(*PY, "-c", "import sys; sys.path.insert(0, 'scripts'); import lib; print(lib.secret_values('prod')['POSTGRES_PASSWORD'][:4])",
                       SOPS_AGE_KEY_FILE=str(other_key))
        self.assertEqual(len(r.stdout.strip()), 4)


@unittest.skipUnless(DOCKER, "needs docker")
class Alone(TestCase):
    """Gate 2: a module run alone keeps the contract, and its pack is checked."""

    def test_new_module_keeps_the_contract_alone(self):
        self.p.write("site/config/settings.env", f"PROJECT_NAME=test{os.getpid()}\nFOUNDATION=\n")
        self.p.new_module("crm")
        self.addCleanup(self.p.run, *PY, "scripts/alone.py", "crm", "down", check=False)
        self.p.run(*PY, "scripts/alone.py", "crm", "up", QUIET="1")
        r = self.p.run(*PY, "scripts/contract.py", "crm", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("crm_whoami: an agent with the catalog's actions may call it", r.stdout)

    def test_a_broken_pack_fails(self):
        self.p.new_module("crm")
        env = self.p.dir / "src/crm/module/module.env"
        env.write_text(env.read_text().replace("PUBLIC_URL_SETTING=CRM_PUBLIC_URL", "PUBLIC_URL_SETTING=APP_URL"))
        r = self.p.run(*PY, "scripts/contract.py", "crm", "http://127.0.0.1:9", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL PUBLIC_URL_SETTING is CRM_PUBLIC_URL", r.stdout)


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
        return subprocess.run(["scripts/template-update.sh"], cwd=self.project, capture_output=True, text=True, check=True,
                              env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", **env}).stdout

    def test_takes_the_latest_release_and_shows_its_notes(self):
        changelog = self.template.dir / "CHANGELOG.md"
        changelog.write_text(changelog.read_text() + "\n## v9.0.0\n\n- Do this first.\n")
        self.git(self.template.dir, "commit", "-qam", "v9")
        self.git(self.template.dir, "tag", "v9.0.0")
        (self.template.dir / "docs/guide.md").write_text("unreleased\n")
        self.git(self.template.dir, "commit", "-qam", "after v9")
        out = self.update()
        self.assertIn("merged template/tags/v9.0.0", out)
        self.assertIn("Do this first.", out)
        self.assertNotEqual((self.project / "docs/guide.md").read_text(), "unreleased\n")
        self.assertIn("merged template/main", self.update(REF="main"))
        self.assertEqual((self.project / "docs/guide.md").read_text(), "unreleased\n")

    def test_merges_template_and_keeps_project(self):
        (self.project / "site/config/settings.env").write_text("PROJECT_NAME=mine\n")
        (self.project / "README.md").write_text("# Mine\n")
        self.git(self.project, "commit", "-qam", "project")
        (self.template.dir / "docs/guide.md").write_text("new guide\n")
        (self.template.dir / "site/config/settings.env").write_text("PROJECT_NAME=changed-in-template\n")
        (self.template.dir / "README.md").write_text("# Template\n")
        self.git(self.template.dir, "commit", "-qam", "update")
        self.update()
        self.assertEqual((self.project / "docs/guide.md").read_text(), "new guide\n")
        self.assertEqual((self.project / "site/config/settings.env").read_text(), "PROJECT_NAME=mine\n")
        self.assertEqual((self.project / "README.md").read_text(), "# Mine\n")


if __name__ == "__main__":
    unittest.main()

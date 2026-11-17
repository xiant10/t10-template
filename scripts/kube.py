#!/usr/bin/env python3
"""Kubernetes for an environment with TARGET=k8s, such as k8s-local: the services, settings and
secrets of its Compose bundle, as Kubernetes objects in a namespace of their own, so what runs
there is what `make check` and `make smoke` test on Compose.

scripts/render.py writes them (write()), from `docker compose config` on the bundle:

    kustomization.yaml   the namespace, k8s/*.yaml, a ConfigMap for each file or folder the
                         bundle mounts (named by its content's hash, so a change rolls the pods that
                         use it), and each part's k8s/<layer>/ as a kustomize component, layered as
                         compose/ is: k8s/base/, then k8s/local/, then k8s/<env>/
    k8s/<service>.yaml   its Deployment or Job, its Service, and its published ports
    k8s/volumes.yaml     the namespace, and a PersistentVolumeClaim for each named volume

Secrets never go on disk: `up` makes one Secret per service, <service>-secrets, in memory, from
the same values Compose gives it; a hash of them on the pod rolls it when they change.

How Compose maps:
- A service another waits on to complete (service_completed_successfully) is a Job; any other
  is a Deployment with one replica, replaced rather than rolled, as its volumes allow one writer.
- Its name is a headless Service, so every port answers at the name, as on Compose's network.
- A published port is a LoadBalancer Service, <service>-public, on the same port: Docker
  Desktop publishes it on localhost.
- A named volume is a PersistentVolumeClaim. Docker Desktop has one node, so pods share one.
- healthcheck is the readinessProbe. depends_on is the order: `up` applies the services in
  waves, each once the ones it waits on are ready or complete.
- read_only, tmpfs and user are the securityContext and an emptyDir.

scripts/compose.sh runs it for every command on such an environment, as Compose's:

    scripts/kube.py ENV up [--build] [--wait-timeout N]   the Jobs run again, as Compose's one-off services do
    scripts/kube.py ENV down [-v]                          -v deletes the namespace, so its data
    scripts/kube.py ENV ps | logs [-f] [--tail=N] [SERVICE]
    scripts/kube.py ENV exec [-T] SERVICE CMD...
    scripts/kube.py ENV run --rm [--entrypoint X] SERVICE ARGS...   a one-off pod of SERVICE
    scripts/kube.py ENV config ...                        Compose's, on the bundle
"""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402
import wiring  # noqa: E402

DONE = "service_completed_successfully"
NAME = "app.kubernetes.io/name"
PART_OF = "app.kubernetes.io/part-of"
WAVE = "t10.dev/wave"
# What Compose has that needs nothing here, or that a server's compose/server.yml sets.
IGNORED = {"networks", "restart", "depends_on", "container_name", "labels", "logging", "mem_limit", "profiles",
           "stop_grace_period", "init", "pull_policy", "build", "env_file", "hostname"}


def namespace(env):
    cfg = lib.settings(env)
    return cfg.get("KUBE_NAMESPACE") or f"{cfg['PROJECT_NAME']}-{env}"


def compose_config(env):
    """`docker compose config` on the bundle, as JSON. `$` in values stays escaped as `$$`, which
    Kubernetes also reads as `$` in command, args and env."""
    r = subprocess.run([str(lib.GENERATED / env / "compose.sh"), "config", "--format", "json"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"docker compose config: {r.stderr.strip()[-500:]}")
    return json.loads(r.stdout)


def unescape(s):
    return s.replace("$$", "$")


def secret_keys(env, service):
    """The variables a service gets from its secrets, generated/<env>/secrets/<service>.env."""
    return set(lib.read_env(lib.GENERATED / env / "secrets" / f"{service}.env"))


def seconds(duration, default):
    """Compose's 1m30s, 5s or 500ms, in whole seconds, at least 1."""
    if not duration:
        return default
    units = {"h": 3600, "m": 60, "s": 1, "ms": 0.001, "us": 1e-6, "ns": 1e-9}
    total = sum(float(n) * units[u] for n, u in re.findall(r"([\d.]+)(ms|us|ns|h|m|s)", duration))
    return max(1, round(total))


def slug(text, size=40):
    """A name Kubernetes accepts, from any text, short and unique to it."""
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:size].strip("-")
    return f"{base}-{hashlib.sha256(text.encode()).hexdigest()[:6]}"


def waves(services):
    """Each service's wave: 1 if it waits on nothing, else one after the last it waits on."""
    out = {}

    def wave(name, seen=()):
        if name not in out:
            if name in seen:
                sys.exit(f"depends_on loops through {name}")
            deps = [d for d in services[name].get("depends_on", {}) if d in services]
            out[name] = 1 + max((wave(d, (*seen, name)) for d in deps), default=0)
        return out[name]

    for name in services:
        wave(name)
    return out


def probe(healthcheck):
    test = (healthcheck or {}).get("test")
    if not test or healthcheck.get("disable") or test[0] == "NONE":
        return None
    command = [unescape(t) for t in test[1:]] if test[0] == "CMD" else ["/bin/sh", "-c", unescape(test[1])]
    return {"exec": {"command": command}, "periodSeconds": seconds(healthcheck.get("interval"), 30),
            "timeoutSeconds": seconds(healthcheck.get("timeout"), 30), "failureThreshold": healthcheck.get("retries", 3)}


def pod(env, name, s, files, built):
    """A service's pod spec, and the files it mounts: {relative path in the bundle: ConfigMap name}."""
    bundle = f"{lib.GENERATED / env}/"
    secrets = secret_keys(env, name)
    container = {"name": name, "image": s["image"], "imagePullPolicy": "Never" if built else "IfNotPresent"}
    if s.get("entrypoint") is not None:
        container["command"] = s["entrypoint"]
    if s.get("command") is not None:
        container["args"] = s["command"]
    env_vars = [{"name": k, "value": v} for k, v in sorted((s.get("environment") or {}).items()) if v is not None and k not in secrets]
    if env_vars:
        container["env"] = env_vars
    if secrets:
        container["envFrom"] = [{"secretRef": {"name": f"{name}-secrets"}}]
    if s.get("working_dir"):
        container["workingDir"] = s["working_dir"]
    ports = [{"containerPort": int(p["target"]), "protocol": p.get("protocol", "tcp").upper()} for p in s.get("ports", [])]
    if ports:
        container["ports"] = ports
    if probe(s.get("healthcheck")):
        container["readinessProbe"] = probe(s["healthcheck"])
    if s.get("read_only"):
        container["securityContext"] = {"readOnlyRootFilesystem": True}

    volumes, mounts = [], []
    for i, v in enumerate(s.get("volumes", [])):
        vol = f"v{i}"
        if v["type"] == "volume":
            volumes.append({"name": vol, "persistentVolumeClaim": {"claimName": v["source"]}})
            mounts.append({"name": vol, "mountPath": v["target"]})
        elif v["type"] == "tmpfs":
            volumes.append({"name": vol, "emptyDir": {"medium": "Memory"}})
            mounts.append({"name": vol, "mountPath": v["target"]})
        elif v["type"] == "bind":
            if not v["source"].startswith(bundle):
                sys.exit(f"{name} mounts {v['source']}, outside generated/{env}/: the cluster can't see it")
            rel = v["source"][len(bundle):]
            path = lib.GENERATED / env / rel
            if not path.exists():
                # Compose makes an empty folder for it.
                volumes.append({"name": vol, "emptyDir": {}})
                mounts.append({"name": vol, "mountPath": v["target"], "readOnly": True})
                continue
            cm = files.setdefault(rel, slug("files-" + rel))
            if path.is_dir():
                items = [{"key": key(f.relative_to(path)), "path": f.relative_to(path).as_posix(), "mode": mode(f)} for f in sorted(path.rglob("*")) if f.is_file()]
                volumes.append({"name": vol, "configMap": {"name": cm, "items": items}})
                mounts.append({"name": vol, "mountPath": v["target"], "readOnly": True})
            else:
                volumes.append({"name": vol, "configMap": {"name": cm, "items": [{"key": key(path.name), "path": path.name, "mode": mode(path)}]}})
                mounts.append({"name": vol, "mountPath": v["target"], "subPath": path.name, "readOnly": True})
        else:
            sys.exit(f"{name}: a {v['type']} volume has no Kubernetes form here")
    for i, t in enumerate(s.get("tmpfs", [])):
        volumes.append({"name": f"t{i}", "emptyDir": {"medium": "Memory"}})
        mounts.append({"name": f"t{i}", "mountPath": t.split(":")[0]})
    if mounts:
        container["volumeMounts"] = mounts

    spec = {"containers": [container], "enableServiceLinks": False, "automountServiceAccountToken": False}
    if volumes:
        spec["volumes"] = volumes
    user = str(s.get("user") or "")
    if user:
        uid, _, gid = user.partition(":")
        if not uid.isdigit() or (gid and not gid.isdigit()):
            sys.exit(f"{name}: user {user} must be numeric here")
        spec["securityContext"] = {"runAsUser": int(uid), **({"runAsGroup": int(gid)} if gid else {})}
    return spec


def key(rel):
    """A ConfigMap key for a file's path: Kubernetes keys can't hold `/`."""
    return re.sub(r"[^-._a-zA-Z0-9]", "_", pathlib.PurePath(rel).as_posix().replace("/", "__"))


def mode(path):
    return 0o755 if path.stat().st_mode & 0o111 else 0o644


def manifests(env, config=None):
    """{relative path: object list} for k8s/, and the kustomization, from the bundle's config."""
    config = config or compose_config(env)
    services = config["services"]
    project = lib.settings(env)["PROJECT_NAME"]
    once = {d for s in services.values() for d, c in s.get("depends_on", {}).items() if c.get("condition") == DONE and d in services}
    order = waves(services)
    files, out = {}, {}
    for name, s in sorted(services.items()):
        unknown = sorted(k for k in s if k not in IGNORED and k not in {
            "image", "entrypoint", "command", "environment", "working_dir", "ports", "healthcheck", "read_only", "volumes", "tmpfs", "user"})
        if unknown:
            print(f"warn {name}: {', '.join(unknown)} isn't carried to Kubernetes", file=sys.stderr)
        labels = {NAME: name, PART_OF: project}
        meta = {"name": name, "labels": {**labels, WAVE: str(order[name])}}
        template = {"metadata": {"labels": labels}, "spec": pod(env, name, s, files, "build" in s)}
        held = lib.GENERATED / env / "secrets" / f"{name}.env"
        if secret_keys(env, name):
            # A change to its secrets rolls it, as Compose recreates a container whose env_file changed.
            template["metadata"]["annotations"] = {"t10.dev/secrets": hashlib.sha256(held.read_bytes()).hexdigest()[:16]}
        objects = [] if name in once else [{"apiVersion": "v1", "kind": "Service", "metadata": {"name": name, "labels": {**labels, WAVE: "0"}},
                    # Headless and published before it's ready: the name resolves to the pod, any port, as on Compose.
                    "spec": {"clusterIP": "None", "publishNotReadyAddresses": True, "selector": {NAME: name}}}]
        if name in once:
            template["spec"]["restartPolicy"] = "Never"
            objects.append({"apiVersion": "batch/v1", "kind": "Job", "metadata": meta, "spec": {"backoffLimit": 2, "template": template}})
        else:
            objects.append({"apiVersion": "apps/v1", "kind": "Deployment", "metadata": meta, "spec": {
                "replicas": 1, "strategy": {"type": "Recreate"}, "selector": {"matchLabels": {NAME: name}}, "template": template}})
        published = [p for p in s.get("ports", []) if p.get("published")]
        if published:
            objects.append({"apiVersion": "v1", "kind": "Service", "metadata": {"name": f"{name}-public", "labels": {**labels, WAVE: "0"}},
                            "spec": {"type": "LoadBalancer", "selector": {NAME: name}, "ports": [
                                {"name": f"p{p['published']}-{p.get('protocol', 'tcp')}", "port": int(p["published"]), "targetPort": int(p["target"]),
                                 "protocol": p.get("protocol", "tcp").upper()} for p in published]}})
        out[f"k8s/{name}.yaml"] = objects
    volumes = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace(env), "labels": {PART_OF: project, WAVE: "0"}}}]
    volumes += [{"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": v, "labels": {PART_OF: project, WAVE: "0"}},
                 "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "1Gi"}}}}
                for v in sorted(config.get("volumes", {}))]
    out["k8s/volumes.yaml"] = volumes

    generators = []
    for rel, cm in sorted(files.items()):
        path = lib.GENERATED / env / rel
        found = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        names = [key(p.relative_to(path) if path.is_dir() else p.name) for p in found]
        generators.append({"name": cm, "files": [f"{k}={p.relative_to(lib.GENERATED / env).as_posix()}" for k, p in zip(names, found)]})
    components = [f"{part.relative_to(lib.ROOT).as_posix()}/k8s/{layer}" for layer in ["base", *lib.layers(env)] for part in lib.parts()
                  if (part / "k8s" / layer / "kustomization.yaml").exists()]
    kustomization = {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "namespace": namespace(env),
                     "resources": sorted(out), "generatorOptions": {"labels": {PART_OF: project, WAVE: "0"}}, "configMapGenerator": generators}
    if components:
        kustomization["components"] = components
    return out, kustomization


def secrets(env, config):
    """Each service's Secret, from the values Compose gives it: never written to disk."""
    project = lib.settings(env)["PROJECT_NAME"]
    out = []
    for name, s in sorted(config["services"].items()):
        keys = secret_keys(env, name)
        data = {k: unescape(v) for k, v in (s.get("environment") or {}).items() if k in keys and v is not None}
        if data:
            out.append({"apiVersion": "v1", "kind": "Secret", "type": "Opaque", "metadata": {
                "name": f"{name}-secrets", "labels": {NAME: name, PART_OF: project}}, "stringData": data})
    return out


def write(env):
    """Writes the manifests into generated/<env>/; render.py calls it last."""
    objects, kustomization = manifests(env)
    head = f"# Written by scripts/kube.py for ENV={env}, from the Compose bundle. Don't edit.\n"
    files = {rel: (head + "\n---\n".join(wiring.to_yaml(o) for o in objs) + "\n").encode() for rel, objs in objects.items()}
    files["kustomization.yaml"] = (head + wiring.to_yaml(kustomization) + "\n").encode()
    return files


class Kube:
    def __init__(self, env):
        cfg = lib.settings(env)
        self.env, self.ns, self.project = env, namespace(env), cfg["PROJECT_NAME"]
        self.base = ["kubectl", "--context", cfg["KUBE_CONTEXT"], "--namespace", self.ns]

    def run(self, *args, check=True, capture=True, stdin=None):
        r = subprocess.run([*self.base, *args], capture_output=capture, text=True, input=stdin)
        if check and r.returncode != 0:
            sys.exit(f"kubectl {' '.join(args)}: {(r.stderr or '').strip()[-800:]}")
        return r

    def apply(self, stdin=None, selector=None):
        """Server-side apply of the bundle (or stdin), the objects of one wave: their names."""
        source = ["-f", "-"] if stdin else ["-k", str(lib.GENERATED / self.env)]
        r = self.run("apply", "--server-side", "--force-conflicts", "--field-manager=t10", "-o", "name", *source,
                     *(["-l", selector] if selector else []), stdin=stdin)
        return set(r.stdout.split())

    def mine(self, kinds):
        return set(self.run("get", kinds, "-l", f"{PART_OF}={self.project}", "-o", "name", check=False).stdout.split())

    def logs_of(self, name):
        return self.run("logs", "--tail=30", "--all-containers", "-l", f"{NAME}={name}", check=False).stdout.strip()

    def wait(self, name, kind, deadline):
        while time.time() < deadline:
            if kind == "Job":
                status = json.loads(self.run("get", f"job/{name}", "-o", "json").stdout).get("status", {})
                if status.get("succeeded"):
                    return
                if any(c["type"] == "Failed" and c["status"] == "True" for c in status.get("conditions", [])):
                    sys.exit(f"{name} failed:\n{self.logs_of(name)}")
            else:
                left = max(1, int(deadline - time.time()))
                if self.run("rollout", "status", f"deployment/{name}", f"--timeout={left}s", check=False).returncode == 0:
                    return
            time.sleep(2)
        sys.exit(f"{name} isn't ready after the wait timeout:\n{self.logs_of(name)}")

    def up(self, args):
        """Every service, wave by wave; with SERVICE names, only those, as Compose's --no-deps.
        --build rebuilds what's built here first, and --force-recreate replaces the pods."""
        timeout, names, it = 300, [], iter(args)
        for a in it:
            if a == "--wait-timeout":
                timeout = int(next(it))
            elif a.startswith("--wait-timeout="):
                timeout = int(a.split("=", 1)[1])
            elif not a.startswith("-"):
                names.append(a)
        config = compose_config(self.env)
        services = config["services"]
        if set(names) - set(services):
            sys.exit(f"{self.env} has no service {', '.join(sorted(set(names) - set(services)))}")
        chosen = names or sorted(services)
        kinds = {o["metadata"]["name"]: o["kind"] for objs in manifests(self.env, config)[0].values() for o in objs if o["kind"] in ("Job", "Deployment")}
        built = [n for n in chosen if "build" in services[n]]
        if "--build" in args and built:
            subprocess.run([str(lib.GENERATED / self.env / "compose.sh"), "build", *built], check=True)
        if self.run("get", "namespace", self.ns, check=False).returncode != 0:
            print(f"namespace {self.ns}, on context {self.base[2]}")
        # Compose's one-off services run again on every up; a Job can't, so it's made afresh.
        jobs = [f"job/{n}" for n in chosen if kinds[n] == "Job"]
        if jobs:
            self.run("delete", *jobs, "--ignore-not-found", "--wait")
        applied = self.apply(selector=f"{WAVE}=0")
        applied |= self.apply(stdin=json.dumps({"apiVersion": "v1", "kind": "List", "items": secrets(self.env, config)}))
        order = waves(services)
        for n in range(1, max(order.values(), default=0) + 1):
            wave = [s for s in chosen if order[s] == n]
            if not wave:
                continue
            print(f"wave {n}: {', '.join(wave)}", flush=True)
            applied |= self.apply(selector=f"{WAVE}={n}" + (f",{NAME} in ({','.join(wave)})" if names else ""))
            deadline = time.time() + timeout
            for name in wave:
                self.wait(name, kinds[name], deadline)
        # An image built here keeps its tag, so a rebuilt one restarts its pod.
        for name in chosen:
            if kinds[name] != "Deployment":
                continue
            restart = "--force-recreate" in args
            if name in built:
                want = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", services[name]["image"]], capture_output=True, text=True).stdout.strip()
                have = self.run("get", "pods", "-l", f"{NAME}={name}", "-o", "jsonpath={.items[*].status.containerStatuses[*].imageID}", check=False).stdout
                restart = restart or bool(want and want not in have)
            if restart:
                self.run("rollout", "restart", f"deployment/{name}")
                self.wait(name, "Deployment", time.time() + timeout)
        # As --remove-orphans: what this project made that the bundle no longer has. Volumes stay.
        stale = set() if names else self.mine("deployment,job,service,configmap,secret") - applied
        if stale:
            self.run("delete", *sorted(stale), "--ignore-not-found")
        print(f"{self.env}: {', '.join(names) if names else 'up'} in namespace {self.ns}")

    def down(self, args):
        if "-v" in args or "--volumes" in args:
            subprocess.run([*self.base[:3], "delete", "namespace", self.ns, "--ignore-not-found", "--wait"], check=True)
        else:
            stale = self.mine("deployment,job,service,configmap,secret")
            if stale:
                self.run("delete", *sorted(stale), "--ignore-not-found", "--wait", capture=False)

    def target(self, service):
        kind = "deployment" if self.run("get", f"deployment/{service}", check=False).returncode == 0 else "job"
        return f"{kind}/{service}"

    def main(self, command, args):
        if command == "up":
            self.up(args)
        elif command == "down":
            self.down(args)
        elif command == "ps":
            self.run("get", "deployments,jobs,pods,services", "-o", "wide", check=False, capture=False)
        elif command == "logs":
            tail = next((a.split("=", 1)[1] for a in args if a.startswith("--tail=")), "100")
            follow = ["-f"] if "-f" in args or "--follow" in args else []
            names = [a for a in args if not a.startswith("-")]
            where = [self.target(names[0])] if names else ["-l", f"{PART_OF}={self.project}", "--prefix", "--max-log-requests=50"]
            os.execvp("kubectl", [*self.base, "logs", *follow, f"--tail={tail}", "--all-containers", *where])
        elif command == "exec":
            tty = [] if "-T" in args or not sys.stdin.isatty() else ["-t"]
            rest = [a for a in args if a != "-T"]
            os.execvp("kubectl", [*self.base, "exec", "-i", *tty, self.target(rest[0]), "-c", rest[0], "--", *rest[1:]])
        elif command == "run":
            self.one_off(args)
        else:
            sys.exit(f"{command} isn't a command on Kubernetes here: up, down, ps, logs, exec, run, config")

    def one_off(self, args):
        entrypoint, rest = None, []
        it = iter(args)
        for a in it:
            if a == "--entrypoint":
                entrypoint = next(it)
            elif a.startswith("--entrypoint="):
                entrypoint = a.split("=", 1)[1]
            elif not (a.startswith("-") and not rest):
                rest.append(a)
        if not rest:
            sys.exit("run SERVICE [ARGS...]")
        service, command = rest[0], rest[1:]
        r = self.run("get", self.target(service), "-o", "json", check=False)
        if r.returncode != 0:
            sys.exit(f"{service} isn't running in {self.ns}: make up ENV={self.env} first")
        spec = json.loads(r.stdout)["spec"]["template"]["spec"]
        container = spec["containers"][0]
        if entrypoint is not None:
            container["command"] = [entrypoint]
            container.pop("args", None)
        if command:
            container["args"] = command
        spec["restartPolicy"] = "Never"
        name = f"{service}-run-{int(time.time())}"
        os.execvp("kubectl", [*self.base, "run", name, "--rm", "-i", "--quiet", "--restart=Never", f"--image={container['image']}",
                              f"--overrides={json.dumps({'apiVersion': 'v1', 'spec': spec})}"])


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    env, command, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
    if command == "config":
        os.execv(str(lib.GENERATED / env / "compose.sh"), [str(lib.GENERATED / env / "compose.sh"), "config", *rest])
    Kube(env).main(command, rest)

#!/usr/bin/env python3
"""Pin images to what a tag points to now, as sha-<commit>@<digest>.

    scripts/resolve-tags.py --env=prod          # show what `latest` points to, change nothing
    scripts/resolve-tags.py --env=prod --write  # rewrite each pin in the versions.env that wins for it
    scripts/resolve-tags.py --env=prod --write T10_AUTH_SERVER T10_WORKBENCH   # only these

Each image is pinned in the last versions.env that names it for the environment (lib.versions_files):
for a server, foundation/config/server/versions.env in the template, or site/'s where a project
overrides one. A line that follows `latest`, as local's do, is shown but never rewritten. Only
public ghcr.io images: it asks for an anonymous token, so a private module image is skipped and
pinned by hand.
"""
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib  # noqa: E402

ACCEPT = ",".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])
LINE = re.compile(r"^(T10_[A-Z_]+)=ghcr\.io/([^:@]+)[:@]")


def request(url, token, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"Authorization": "Bearer " + token, "Accept": ACCEPT})
    return urllib.request.urlopen(req)


def resolve(repo, tag="latest"):
    token = json.load(urllib.request.urlopen(f"https://ghcr.io/token?scope=repository:{repo}:pull"))["token"]
    digest = lambda t: request(f"https://ghcr.io/v2/{repo}/manifests/{t}", token, "HEAD").headers["Docker-Content-Digest"]
    want = digest(tag)
    tags = json.load(request(f"https://ghcr.io/v2/{repo}/tags/list?n=1000", token)).get("tags") or []
    for t in tags:
        if t.startswith("sha-") and digest(t) == want:
            return f"ghcr.io/{repo}:{t}@{want}"
    raise SystemExit(f"{repo}: no sha- tag has the digest of {tag}")


def main(argv):
    write = "--write" in argv
    env = next((a.split("=", 1)[1] for a in argv if a.startswith("--env=")), "local")
    only = {a for a in argv if not a.startswith("--")}
    files = lib.versions_files(env)
    winner = {name: f for f in files for name in lib.read_env(f)}
    for f in files:
        lines = f.read_text().splitlines(keepends=True)
        for i, line in enumerate(lines):
            m = LINE.match(line)
            if not m or winner[m.group(1)] != f or (only and m.group(1) not in only):
                continue
            try:
                pinned = resolve(m.group(2))
            except urllib.error.HTTPError as e:
                print(f"{m.group(1)}: skipped, {e.code} from ghcr.io (private?)", file=sys.stderr)
                continue
            if line.rstrip().endswith(":latest"):
                print(f"{m.group(1)}: follows latest, now {pinned}  ({f.relative_to(lib.ROOT)}, not rewritten)")
                continue
            print(f"{m.group(1)}={pinned}  ({f.relative_to(lib.ROOT)})")
            lines[i] = f"{m.group(1)}={pinned}\n"
        if write:
            f.write_text("".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])

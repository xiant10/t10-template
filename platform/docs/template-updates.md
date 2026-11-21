# A project and its template

How a project keeps its own changes and still takes every update from `t10-template`, and how the template releases those updates. Who owns which path is in [`guide.md`](guide.md#who-owns-what); this is the practice built on it.

## The model

A project is a git clone of the template with two remotes:

| Remote | Is | You |
| --- | --- | --- |
| `origin` | The project's own repo | Push all your work here |
| `template` | `t10-template` | Only ever merge from it, with `make template-update` |

The two never step on each other because each owns its own paths (`lib.OWNED` in `platform/scripts/lib.py`):

| The project's: template updates never touch them | The template's: a project never edits them |
| --- | --- |
| `README.md` | `platform/`: the foundation, scripts, kit, docs, tests and `CHANGELOG.md` |
| `modules/<id>/`: each module's deployment, and its code in `src/` | `Makefile`, `LICENSE`, `.gitignore` |
| `site/`: name, components, ports, addresses, secrets, overrides | `.github/workflows/t10-template.yml`: the checks |
| `.github/workflows/ci.yml`: the project's CI, which calls the template's checks | Everything else at the root |

A project's own ignore rules go in `site/.gitignore` or `modules/<id>/.gitignore`, which git reads as it does the root's, so the root `.gitignore` stays the template's.

Updates arrive as a git merge, so the project keeps the shared history. Never fork the template on GitHub or copy its files without git: either loses the history the merges rely on.

## Starting a project

```sh
git clone -o template https://github.com/xiant10/t10-template.git myproject
cd myproject
git remote add origin <your project's repo>
git push -u origin main
```

`-o template` names the template's remote `template` instead of `origin`. A project cloned from a local copy of the template (`git clone -o template ~/projects/t10-template myproject`) works the same; `git remote set-url template <url>` points it at GitHub later. The rest of setting up a project is [`new-project.md`](new-project.md).

## Changing things in a project

Change only the project's paths, and commit and push to `origin` as usual. When the project needs a value the template sets differently, override it from `site/` or the module's folder; never edit the template's file:

| To change | Put it in |
| --- | --- |
| A foundation service's setting | `site/config/<service>.env`, or `site/config/<env>/<service>.env` for one environment |
| Ports, public addresses, project name, which components run | `site/config/settings.env`, or `site/config/<env>/settings.env` |
| An image the template pins | `site/config/server/versions.env` for servers, `site/config/local/versions.env` for this machine, as a deliberate exception |
| How a module plugs in | `modules/<id>/compose/<name>.yml`, which overrides its generated wiring |
| A secret the project adds | `site/secrets.json`, and its value in `site/secrets/<env>.env` |
| An OAuth client, catalog, agent route or workbench entry of its own, or a change to the foundation's | `site/clients.json` (`"_merge": true` to change one), `site/permissions/`, `site/agent-routes.json`, `site/part.env` ([`guide.md`](guide.md#what-a-part-adds)) |
| A step before or after a command | `site/hooks/<event>.sh` or `.py` ([`guide.md`](guide.md#hooks)) |
| A command of its own | `site/project.mk`, or a module's `modules/<id>/module.mk` |

`make config-show SVC=<service>` shows which file each value came from. `make check` warns about every template file the project has edited, since that's where an update can conflict.

## Taking an update

```sh
make template-update      # merges the template's latest release
make verify               # everything from empty volumes
git push                  # to origin
```

`make template-update` needs a clean working tree. It:

1. fetches the template, keeping its tags apart from the project's (under `refs/remotes/template/tags/`);
2. merges the newest release tag, `v<x.y.z>`; `REF=main make template-update` takes the template's unreleased work instead, and `REF=v0.1.0` a given release;
3. puts back `README.md`, `modules/`, `site/` and `.github/workflows/ci.yml` exactly as the project had them;
4. commits the merge, and prints what [`CHANGELOG.md`](../CHANGELOG.md) added. With `NO_COMMIT=1` it stops before committing, the merge staged, so its **In a project** work can go in the same commit; `git commit` finishes it and `git merge --abort` drops it.

Read that output: each release's **In a project** notes say what a project must do, such as slimming a module's folder after the template takes over part of it. Do them, then `make verify`, and commit.

Take each release in turn when they ask for work; several releases at once is fine when they don't.

### When it conflicts

A conflict happens only on a template file the project edited. The merge stops without committing and names the files. For each:

- **A setting, or something only this project needs:** take the template's version of the file (`git checkout --theirs <file>`), move the change into `site/` or the module's folder, then `git add` and `git commit`.
- **Something every project needs:** take the template's version here, and make the change in the template instead (below), so it comes back with the next release.

To give up on the merge: `git merge --abort`.

## Releasing an update from the template

A project's `make template-update` sees only tagged, pushed releases. In `t10-template`:

1. Make the change, with `make test-template`, `make lint` and `make verify` passing (CI runs them on every push and pull request).
2. Add an entry at the top of `CHANGELOG.md`: what changed, and under **In a project** anything a project must do, with how to check it worked.
3. Pick the version: the last number for a change that needs nothing from a project, the middle one for a change that asks a project to do something.
4. Commit, tag and push:

   ```sh
   git tag -a v0.1.1 -m "v0.1.1: <what it's for>"
   git push origin main v0.1.1
   ```

5. Each project runs `make template-update` when it's ready.

A change found while working in a project goes the same way: make it in the template, release it, and take it into the project with `make template-update`. Never leave it as an edit to a template file in the project. When the project can't wait, or someone else maintains the template, write it down as a finding instead ([below](#reporting-what-a-project-finds)).

## Reporting what a project finds

Building a real module is how the template's gaps show up: a bug in the kit, a route Workbench expects that nobody documented, a step every module repeats by hand. A project writes each one down in `site/docs/template-findings.md`, which every project starts with, so the template's maintainers can take it back. It's the project's file, so `make template-update` never touches it.

**When to write one.** Whenever working on the project shows something about the template rather than about the project: a bug in `platform/`, a gap in the module contract or the kit, a doc that's wrong or silent, something the project had to work around or repeat that every project will, or a check that would have caught a problem sooner. Write it when you find it, not at the end. Something only this project needs isn't a finding; it goes in `site/` or the module's folder, as above. Something wrong in a foundation service (auth-server, Workbench, …) is still written here: the template's maintainers turn it into an upstream item ([`upstream.md`](upstream.md)).

**What each says.** A row in the file's table, then a section with the same number:

| Part | Says |
| --- | --- |
| Title | The finding in one sentence, as the problem, not the fix: "The kit's web sign-in goes to the wrong address" |
| Kind | `Bug`, `Contract gap` (the template doesn't say or do something a module has to), `Gap` (missing help, such as a kit helper), `Documentation`, `Test gap` or `Suggestion` |
| What happened | What you saw, with the exact error, address or log line, and the template version (`platform/CHANGELOG.md`'s top entry) |
| Cause | Where in the template, or the foundation, it comes from: file and function, `path/to/file.go`, `name` |
| Here | What this project did about it: nothing yet, a workaround in its own code, or a local patch to a template file |
| Suggestion | What the template could do, so the next project gets it for free. Several options are fine; say which you'd pick |
| Status | `open`; `taken in v<x.y.z>` once a release has it; `declined` with the reason |

**A local patch to a template file** is the last resort, for a bug that blocks the project: keep it to the smallest change, put `template-finding <n>` in a comment beside it so `grep -rn "template-finding"` finds it, and mark it in the table's **Local patch** column. `make check` lists every edited template file too. The patch may conflict at the next `make template-update`; when that release has the fix, take the template's file (`git checkout --theirs <file>`), and otherwise keep yours and say so in the finding.

**After an update,** read the release's notes against the open findings: mark each one the release takes as `taken in v<x.y.z>`, remove its workaround or patch, and check with `make verify`.

**For the template's maintainers:** read a project's `site/docs/template-findings.md` before planning a release. Each finding a release takes gets a line in `CHANGELOG.md` naming it (such as "from kuaidan-sales's findings, 1"), so the project can match them up. A finding about a foundation service becomes an item in `upstream.md`.

## Foundation images

Local follows each foundation image's `latest`, so it meets foundation changes first. A server's pins, in `foundation/config/server/versions.env`, belong to the template, because they're the set it was tested with, and a project takes new ones through a template release. If a project's servers must run a different image before then, it pins it by digest in `site/config/server/versions.env` (or `site/config/<env>/versions.env`) and says why there; `make pin ENV=prod` shows what's newer.

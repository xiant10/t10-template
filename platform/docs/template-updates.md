# A project and its template

How a project keeps its own changes and still takes every update from `t10-template`, and how the template releases those updates. Who owns which path is in [`guide.md`](guide.md#who-owns-what); this is the practice built on it.

## The model

A project is a git clone of the template with two remotes:

| Remote | Is | You |
| --- | --- | --- |
| `origin` | The project's own repo | Push all your work here |
| `template` | `t10-template` | Only ever merge from it, with `make template-update` |

The two never step on each other because each owns its own paths (`lib.OWNED` in `scripts/lib.py`):

| The project's: template updates never touch them | The template's: a project never edits them |
| --- | --- |
| `README.md` | `foundation/`, `scripts/`, `kit/`, `docs/` |
| `modules/<id>/`: each module's deployment | `Makefile`, `CHANGELOG.md`, `LICENSE`, `tests/`, `.github/` |
| `src/<id>/`: each module's code | Everything else at the root |
| `site/`: name, components, ports, addresses, secrets, overrides | |

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
| An image the template pins | `site/versions.env`, as a deliberate exception |
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
3. puts back `README.md`, `modules/`, `site/` and `src/` exactly as the project had them;
4. commits the merge, and prints what [`CHANGELOG.md`](../CHANGELOG.md) added.

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

A change found while working in a project goes the same way: make it in the template, release it, and take it into the project with `make template-update`. Never leave it as an edit to a template file in the project.

## Foundation images

The foundation's pins in `foundation/versions.env` belong to the template, because they're the set it was tested with. A project takes new foundation images through a template release. If a project must run a different image before then, it pins it in `site/versions.env` and says why there; `make pin` shows what's newer.

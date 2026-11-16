#!/bin/sh
# Merges the template's latest into this project: everything the template owns comes from it,
# and what the project owns (README.md, modules/, site/) stays the project's, so those never
# conflict. The template is the git remote `template`, as `git clone -o template` names it.
#
#   scripts/template-update.sh            # merges template/main, or REF=<branch or tag>
#
# Stops without committing if a template file conflicts, which happens only where the project
# edited one: `make check` warns about those. Resolve, then `git commit`.
set -eu
cd "$(dirname "$0")/.."
ref=template/${REF:-main}
git remote get-url template >/dev/null 2>&1 || { echo "no git remote named template: git remote add template <template repo>" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "commit or stash your changes first" >&2; exit 1; }

git fetch -q template
if git merge-base --is-ancestor "$ref" HEAD; then
	echo "already up to date with $ref"
	exit 0
fi
before=$(git rev-parse HEAD)
git merge -q --no-ff --no-commit "$ref" >/dev/null 2>&1 || true

# What the project owns stays as it was. A file the template adds there is kept, as a starting point.
for path in README.md modules site; do
	if git cat-file -e "$before:$path" 2>/dev/null; then
		git checkout "$before" -- "$path"
	fi
done

if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
	echo "these template files conflict, because this project edited them; resolve, then git commit:" >&2
	git diff --name-only --diff-filter=U >&2
	exit 1
fi
git commit -q -m "Merge $ref (make template-update)"
echo "merged $ref: $(git rev-parse --short "$ref")"
git diff --stat "$before" HEAD | tail -1

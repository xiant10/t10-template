#!/bin/sh
# Merges the template's latest into this project: everything the template owns comes from it,
# and what the project owns (lib.OWNED: README.md, modules/, site/, src/) stays the project's, so
# those never conflict. The template is the git remote `template`, as `git clone -o template` names it.
#
#   scripts/template-update.sh            # merges the template's latest release, v<x.y.z>
#   REF=main scripts/template-update.sh   # or a branch or tag: its unreleased work, or an older release
#
# Stops without committing if a template file conflicts, which happens only where the project
# edited one: `make check` warns about those. Resolve, then `git commit`. After merging, prints
# what CHANGELOG.md added, which says what a project must do for each release.
set -eu
cd "$(dirname "$0")/.."
git remote get-url template >/dev/null 2>&1 || { echo "no git remote named template: git remote add template <template repo>" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "commit or stash your changes first" >&2; exit 1; }

# The template's tags go under refs/remotes/template/tags/, so they never mix with the project's.
git fetch -q template '+refs/heads/*:refs/remotes/template/*' '+refs/tags/*:refs/remotes/template/tags/*'
if [ -n "${REF:-}" ]; then
	ref=template/tags/$REF
	git rev-parse -q --verify "$ref^{commit}" >/dev/null || ref=template/$REF
else
	latest=$(git for-each-ref --sort=-v:refname --count=1 --format='%(refname:lstrip=4)' 'refs/remotes/template/tags/v*')
	if [ -n "$latest" ]; then ref=template/tags/$latest; else ref=template/main; fi
fi
git rev-parse -q --verify "$ref^{commit}" >/dev/null || { echo "the template has no $ref" >&2; exit 1; }
if git merge-base --is-ancestor "$ref" HEAD; then
	echo "already up to date with $ref"
	exit 0
fi
before=$(git rev-parse HEAD)
owned=$(python3 -I -B scripts/lib.py owned)
git merge -q --no-ff --no-commit "$ref" >/dev/null 2>&1 || true

# What the project owns stays as it was. A file the template adds there is kept, as a starting point.
for path in $owned; do
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
notes=$(git diff "$before" HEAD -- CHANGELOG.md | sed -n 's/^+\([^+]\)/\1/p; s/^+$//p')
[ -z "$notes" ] || printf '\nWhat changed, from CHANGELOG.md; do what it says for each release:\n%s\n' "$notes"

#!/usr/bin/env bash
# scripts/release.sh X.Y.Z [--dry-run]: cut a release by hand.
#
#   1. checks: X.Y.Z is newer than VERSION, the tag vX.Y.Z does not exist, the
#      working tree is clean, a repo-local git identity is set, and
#      CHANGELOG.md has at least one entry under [Unreleased];
#   2. writes X.Y.Z to VERSION and moves the [Unreleased] entries to
#      "## [X.Y.Z] - YYYY-MM-DD" (UTC), leaving an empty [Unreleased] above it
#      (compare links at the bottom of CHANGELOG.md are updated when present);
#   3. commits "chore(release): vX.Y.Z" and tags vX.Y.Z (annotated), both with
#      TZ=UTC dates;
#   4. writes that section to a notes file and prints the push and
#      `gh release create` commands. It pushes nothing.
#
# --dry-run prints the new VERSION, the CHANGELOG diff and the notes, and
# changes nothing.
set -euo pipefail

ROOT=$(CDPATH='' cd -P -- "$(dirname -- "$0")/.." && pwd -P)
cd "$ROOT"
export LC_ALL=C TZ=UTC

die() {
  printf 'release: %s\n' "$*" >&2
  exit 1
}
usage() {
  echo "usage: scripts/release.sh X.Y.Z [--dry-run]" >&2
  exit 2
}

new='' dry=''
for a in "$@"; do
  case $a in
    --dry-run) dry=1 ;;
    -h | --help)
      sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*) usage ;;
    *)
      [ -z "$new" ] || usage
      new=$a
      ;;
  esac
done
[ -n "$new" ] || usage
case $new in v[0-9]*) new=${new#v} ;; esac
printf '%s\n' "$new" | grep -Eq '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' ||
  die "'$new' is not X.Y.Z"
tag=v$new

[ -f VERSION ] || die "VERSION is missing"
[ -f CHANGELOG.md ] || die "CHANGELOG.md is missing"
old=$(sed -n 1p VERSION | tr -d '[:space:]')

# 0 when $1 > $2 (numeric X.Y.Z).
newer() {
  awk -v a="$1" -v b="$2" 'BEGIN {
    split(a, x, "."); split(b, y, ".")
    for (i = 1; i <= 3; i++) {
      if (x[i] + 0 > y[i] + 0) exit 0
      if (x[i] + 0 < y[i] + 0) exit 1
    }
    exit 1
  }'
}
newer "$new" "$old" || die "$new is not newer than VERSION ($old)"

grep -q '^## \[Unreleased\]' CHANGELOG.md || die "CHANGELOG.md has no '## [Unreleased]' heading"
grep -q "^## \[$new\]" CHANGELOG.md && die "CHANGELOG.md already has a [$new] section"

# The entries under [Unreleased], up to the next "## " heading or the link
# references at the bottom.
unreleased=$(awk '
  /^## \[Unreleased\]/ { on = 1; next }
  on && (/^## / || /^\[[^]]*\]: /) { exit }
  on { print }
' CHANGELOG.md)
printf '%s\n' "$unreleased" | grep -q '[^[:space:]]' || die "nothing under [Unreleased] in CHANGELOG.md"

if [ -z "$dry" ]; then
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not a git checkout"
  [ -z "$(git status --porcelain)" ] || die "the working tree has changes; commit or stash them first"
  if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then die "tag $tag already exists"; fi
  git config --local user.name >/dev/null && git config --local user.email >/dev/null ||
    die "no repo-local git identity: set user.name and user.email with git config --local"
fi

date=$(date -u +%Y-%m-%d)
work=$(mktemp -d "${TMPDIR:-/tmp}/bellhop-release.XXXXXX")
trap 'rm -rf "$work"' EXIT

# New CHANGELOG: an empty [Unreleased], then the moved entries under
# [X.Y.Z] - date. Compare links: [Unreleased] now starts at vX.Y.Z, and
# [X.Y.Z] compares the previous tag with vX.Y.Z (only when the file has them).
awk -v new="$new" -v date="$date" '
  /^## \[Unreleased\]/ && !done {
    print; print ""; print "## [" new "] - " date; print ""
    done = 1; skip = 1; next
  }
  skip && /^[[:space:]]*$/ { next }
  { skip = 0 }
  /^\[Unreleased\]: / && match($0, /compare\/v[0-9]+\.[0-9]+\.[0-9]+\.\.\.HEAD/) {
    prev = substr($0, RSTART + 9, RLENGTH - 16)   # between "compare/v" and "...HEAD"
    base = substr($0, 1, RSTART - 1)
    sub(/^\[Unreleased\]: /, "", base)
    print "[Unreleased]: " base "compare/v" new "...HEAD"
    print "[" new "]: " base "compare/v" prev "...v" new
    next
  }
  { print }
' CHANGELOG.md >"$work/CHANGELOG.md"

notes=${TMPDIR:-/tmp}/bellhop-release-$tag.md
awk -v h="## [$new]" '
  index($0, h) == 1 { on = 1; next }
  on && (/^## / || /^\[[^]]*\]: /) { exit }
  on { print }
' "$work/CHANGELOG.md" | awk 'NF { seen = 1 } seen' >"$work/notes.md"

if [ -n "$dry" ]; then
  echo "VERSION: $old -> $new"
  echo
  diff -u CHANGELOG.md "$work/CHANGELOG.md" | sed '1,2d' || true
  echo
  echo "release notes for $tag:"
  sed 's/^/  /' "$work/notes.md"
  echo
  echo "(dry run: nothing changed)"
  exit 0
fi

printf '%s\n' "$new" >"$work/VERSION"
cp "$work/VERSION" VERSION
cp "$work/CHANGELOG.md" CHANGELOG.md
cp "$work/notes.md" "$notes"

stamp=$(date -u +%Y-%m-%dT%H:%M:%S+0000)
export GIT_AUTHOR_DATE=$stamp GIT_COMMITTER_DATE=$stamp
git add VERSION CHANGELOG.md
git commit -q -m "chore(release): $tag"
git tag -a "$tag" -m "$tag"

echo "Released $tag locally: VERSION and CHANGELOG.md committed, tag $tag created."
echo "Release notes: $notes"
echo
echo "Next:"
echo "  git push origin HEAD $tag"
echo "  gh release create $tag --title $tag --notes-file $notes"

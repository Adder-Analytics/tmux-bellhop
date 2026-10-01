#!/usr/bin/env bash
# scripts/scrub-check.sh [--public | --all] [--tree]: nothing personal ships.
#
#   --public   the public rules below (the default; CI runs this)
#   --all      also a private denylist: one extended regex per line in the file
#              named by $SCRUB_DENYLIST_FILE (# comments and blank lines skipped).
#              It is never committed and never printed.
#   --tree     scan every file in the working tree, not only tracked files
#              (the default when git lists no tracked files)
#
# Scans text files (tapes included) and, for images, only the text exiftool
# reads from their metadata: PNG tEXt/iTXt/zTXt chunks, GIF comment and
# application extensions, EXIF, XMP. Never the pixel data: compressed bytes
# can spell anything, so `strings` over a whole image only finds noise. The
# metadata must hold no EXIF, XMP, GIF comment or PNG text chunk other than a
# Software chunk naming vhs; without exiftool images are not checked (a
# warning says so). A hit prints only
# "path:line: public rule #N" or "path:line: private denylist entry #N" (N is the
# line of the denylist file), never the pattern or the matched text. Exit 1 on
# any hit, 2 on a usage error. Matching ignores case.
#
# Public rules (the bracketed letters keep this file from matching itself):
#   1 /User[s]/<name>
#   2 /home/<name>, except the CI runner's in .github/ and linuxbrew's in compat.sh
#   3 the build workflow's scratch paths
#   4 email addresses, except GitHub noreply addresses and example.com
#   5 claude.ai artifact links    6 <host>.loca[l]    7 Mac[B]ook    8 user@ma[c]
#   9 /opt/home[b]rew outside compat.sh
#  10 menu-bar and keyboard tools of a personal setup
#  11 aero[s]pace outside contrib/focus/ and docs/configuration.md
#  12 ghost[t]y outside docs/configuration.md, the aero[s]pace adapter and CHANGELOG.md
#  13 flee[t]-   14 ~/wor[k]   15 ~/k[b]   16 ~/bi[n]/   17 dotfile[s]
#  18 a UUID other than 00000000-0000-4000-8000-0000000000NN
set -uo pipefail

ROOT=$(CDPATH='' cd -P -- "$(dirname -- "$0")/.." && pwd -P)
cd "$ROOT" || exit 2
export LC_ALL=C

mode=public tree=
for a in "$@"; do
  case $a in
    --public) mode=public ;;
    --all) mode=all ;;
    --tree) tree=1 ;;
    -h | --help)
      sed -n '2,/^set -uo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "usage: scripts/scrub-check.sh [--public | --all] [--tree]" >&2
      exit 2
      ;;
  esac
done
if [ "$mode" = all ]; then
  if [ -z "${SCRUB_DENYLIST_FILE:-}" ] || [ ! -r "$SCRUB_DENYLIST_FILE" ]; then
    echo "scrub-check: --all needs SCRUB_DENYLIST_FILE (a readable file, one regex per line)" >&2
    exit 2
  fi
fi

# ── the files ────────────────────────────────────────────────────────────────
LIST=$(mktemp "${TMPDIR:-/tmp}/bellhop-scrub.XXXXXX") || exit 2
HITS=$(mktemp "${TMPDIR:-/tmp}/bellhop-scrub.XXXXXX") || exit 2
META=$(mktemp -d "${TMPDIR:-/tmp}/bellhop-scrub.XXXXXX") || exit 2
trap 'rm -f "$LIST" "$HITS"; rm -rf "$META"' EXIT
if [ -z "$tree" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git ls-files >"$LIST" 2>/dev/null || : >"$LIST"
  if [ ! -s "$LIST" ]; then
    echo "scrub-check: git lists no tracked files; scanning the working tree" >&2
    tree=1
  fi
else
  tree=1
fi
if [ -n "$tree" ]; then
  find . -type f \
    ! -path './.git/*' ! -path './tests/.artifacts/*' ! -path './demo/out/*' \
    ! -path '*/__pycache__/*' ! -name .DS_Store | sed 's|^\./||' | LC_ALL=C sort >"$LIST"
fi

texts=() images=()
while IFS= read -r f; do
  [ -f "$f" ] || continue
  case $f in
    *.png | *.PNG | *.gif | *.GIF | *.jpg | *.jpeg | *.JPG | *.webp | *.ico) images+=("$f") ;;
    *) texts+=("$f") ;;
  esac
done <"$LIST"

hit() { echo "$1" >>"$HITS"; }

# The text in each image's metadata, one tag per line, in $META/<n> for
# images[n]: what exiftool decodes (PNG text chunks, GIF comment and
# application extensions, EXIF, XMP), less its System, ExifTool and Composite
# groups, which describe the file on this disk or are computed, not stored.
# (The File group stays: exiftool files a GIF or JPEG comment there.) Raw
# pixel bytes are never scanned.
have_exif=
command -v exiftool >/dev/null 2>&1 && have_exif=1
i=0
for f in ${images[@]+"${images[@]}"}; do
  : >"$META/$i"
  if [ -n "$have_exif" ]; then
    exiftool -a -G1 -s -- "$f" 2>/dev/null | grep -v -E '^\[(System|ExifTool|Composite)\]' >"$META/$i" || true
  fi
  i=$((i + 1))
done

# grep_rule N ERE [-o]: every match of one public rule in the text files, as
# path:line:text (or path:line:match with -o); exceptions are applied by the caller.
grep_rule() {
  [ ${#texts[@]} -gt 0 ] || return 0
  grep -a -H -n -i -E ${3:+-o} -e "$2" -- "${texts[@]}" 2>/dev/null || true
}

# public N ERE [EXCEPTION-PATTERN...]: hits outside the files matching the case patterns.
public() {
  local n=$1 re=$2 f l rest p skip
  shift 2
  while IFS=: read -r f l rest; do
    skip=
    for p in "$@"; do
      # shellcheck disable=SC2254 # the exception is a case pattern on purpose
      case $f in $p) skip=1 ;; esac
    done
    [ -n "$skip" ] || hit "$f:$l: public rule #$n"
  done < <(grep_rule "$n" "$re")
}

public 1 '/User[s]/[A-Za-z]'
while IFS=: read -r f l m; do
  case $f:$m in
    .github/*:/hom[e]/runner* | lib/bellhop/compat.sh:/hom[e]/linuxbrew*) ;;
    *) hit "$f:$l: public rule #2" ;;
  esac
done < <(grep_rule 2 '/home/[a-z][a-z0-9._-]*' -o)
public 3 '/(private/)?tmp/claude[-]'
while IFS=: read -r f l m; do
  case $(printf '%s' "$m" | LC_ALL=C tr 'A-Z' 'a-z') in
    *@users.noreply.github.com | *@example.com | *.example.com) ;;
    *) hit "$f:$l: public rule #4" ;;
  esac
done < <(grep_rule 4 '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' -o)
public 5 'claude\.ai/artifac[t]'
public 6 '[A-Za-z0-9-]\.loca[l]([^/A-Za-z]|$)'
public 7 'mac[b]ook'
public 8 '[a-z]+@(ma[c]|macboo[k])([^a-z]|$)'
public 9 '/opt/home[b]rew' lib/bellhop/compat.sh
public 10 'swift[b]ar|hammer[s]poon|janky[b]orders|kara[b]iner|nu[p]hy|hyper[ -]?ke[y]'
public 11 'aero[s]pace' 'contrib/focus/*' docs/configuration.md
public 12 'ghost[t]y' docs/configuration.md 'contrib/focus/aero[s]pace' CHANGELOG.md
public 13 '(^|[^_[:alnum:]])flee[t]-'
public 14 '[~]/wor[k]'
public 15 '[~]/k[b]'
public 16 '[~]/bi[n]/'
public 17 'dotfile[s]'
while IFS=: read -r f l m; do
  case $(printf '%s' "$m" | LC_ALL=C tr 'A-F' 'a-f') in
    00000000-0000-4000-8000-0000000000[0-9a-f][0-9a-f]) ;;
    *) hit "$f:$l: public rule #18" ;;
  esac
done < <(grep_rule 18 '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' -o)

# ── the private denylist: patterns go to grep through a file descriptor ──────
if [ "$mode" = all ]; then
  exec 3<"$SCRUB_DENYLIST_FILE"
  n=0
  while IFS= read -r re <&3 || [ -n "$re" ]; do
    n=$((n + 1))
    case $re in '' | \#*) continue ;; esac
    [ ${#texts[@]} -gt 0 ] || break
    while IFS=: read -r f l _; do
      hit "$f:$l: private denylist entry #$n"
    done < <(grep -a -H -n -i -E -f <(printf '%s\n' "$re") -- "${texts[@]}" 2>/dev/null || true)
    i=0
    for f in ${images[@]+"${images[@]}"}; do
      while IFS=: read -r l _; do
        hit "$f (metadata):$l: private denylist entry #$n"
      done < <(grep -a -n -i -E -f <(printf '%s\n' "$re") -- "$META/$i" 2>/dev/null || true)
      i=$((i + 1))
    done
  done
  exec 3<&-
fi

# ── images: the public rules over their metadata text, and no metadata ───────
PUBLIC_IMAGE_RE='/User[s]/[A-Za-z]|/hom[e]/[a-z]|/tmp/claude[-]|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|mac[b]ook|/opt/home[b]rew|swift[b]ar|hammer[s]poon|aero[s]pace|ghost[t]y|flee[t]-|[~]/wor[k]|dotfile[s]'
i=-1
for f in ${images[@]+"${images[@]}"}; do
  i=$((i + 1))
  [ -n "$have_exif" ] || continue
  while IFS=: read -r l _; do
    hit "$f (metadata):$l: public image rule"
  done < <(grep -a -n -i -E -e "$PUBLIC_IMAGE_RE" -- "$META/$i" 2>/dev/null || true)
  # EXIF, XMP, IPTC and comments are never wanted (exiftool puts a GIF or JPEG
  # comment in its File group).
  if exiftool -a -G0 -s "$f" 2>/dev/null | grep -q -E '^\[(EXIF|XMP|IPTC|Photoshop|MakerNotes)\]|^\[(File|GIF)\] +Comment '; then
    hit "$f: metadata: EXIF, XMP, IPTC or a GIF comment (run exiftool -all= on it)"
  fi
  # PNG text chunks: only a Software chunk that names vhs is allowed.
  if exiftool -v "$f" 2>/dev/null | awk '
      /^PNG (tEXt|zTXt|iTXt|eXIf)/ { t = 1; next }
      t { t = 0; k = $1; v = tolower($0); if (!(k == "Software" && v ~ /vhs/)) bad = 1 }
      END { exit bad ? 0 : 1 }'; then
    hit "$f: metadata: a PNG text chunk other than Software=vhs (run exiftool -all= on it)"
  fi
done
if [ ${#images[@]} -gt 0 ] && [ -z "$have_exif" ]; then
  echo "scrub-check: exiftool not installed; image metadata not checked" >&2
fi

if [ -s "$HITS" ]; then
  LC_ALL=C sort -u "$HITS"
  echo "scrub-check ($mode): $(LC_ALL=C sort -u "$HITS" | wc -l | tr -d ' ') hit(s)" >&2
  exit 1
fi
echo "scrub-check ($mode): clean (${#texts[@]} text files, ${#images[@]} images)"

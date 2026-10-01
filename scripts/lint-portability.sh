#!/usr/bin/env bash
# scripts/lint-portability.sh [FILE...]: fail on constructs that break on one of
# macOS (bash 3.2, BSD tools) and Linux (GNU tools, mawk). Operating-system
# differences belong in lib/bellhop/compat.sh, which is the one file not checked.
#
# Skipped: comment lines (first non-blank character #), any line carrying
# "# portable-ok: <reason>", and in libexec/bellhop-doctor the quoted text of
# say/die/warn/printf messages (it prints "lock backend: flock").
# Words match on word boundaries, so bh_realpath is not realpath.
set -uo pipefail

ROOT=$(CDPATH='' cd -P -- "$(dirname -- "$0")/.." && pwd -P)
cd "$ROOT" || exit 2
export LC_ALL=C

if [ $# -gt 0 ]; then
  files=("$@")
else
  shopt -s nullglob
  files=()
  for f in bellhop.tmux bin/* lib/bellhop/*.sh libexec/* contrib/focus/* demo/*.sh demo/bin/* scripts/*.sh \
    tests/run.sh; do
    [ -f "$f" ] || continue
    case $f in lib/bellhop/compat.sh | scripts/lint-portability.sh) continue ;; esac
    files+=("$f")
  done
fi

B='(^|[^_[:alnum:]])' # a word starts here
E='([^_[:alnum:]]|$)' # and ends here
MB=$(printf '[\200-\377]')

# label <TAB> extended regex
RULES="mapfile	${B}mapfile${E}
readarray	${B}readarray${E}
declare -A	${B}declare +-[a-zA-Z]*A
local -n	${B}local +-[a-zA-Z]*n( |$)
\${x,,} / \${x^^}	\\\$\\{[#!]?[A-Za-z_][A-Za-z0-9_]*(\\[[^]]*\\])?(,|\\^)
[[ -v	\\[\\[ +-v
printf '%(…)T'	${B}printf .*%\\([^)]*\\)T
date -r / -d	${B}date( +-[a-zA-Z]+)* +(-[a-zA-Z]*[rd]|--date)
stat -f / -c	${B}stat( +-[a-zA-Z]+)* +-[a-zA-Z]*[fc]
lockf	${B}lockf${E}
flock	${B}flock${E}
readlink -f	${B}readlink( +-[a-zA-Z]+)* +-[a-zA-Z]*f
realpath	${B}realpath${E}
sed -i / -E / -r	${B}sed( +-[a-zA-Z]+)* +-[a-zA-Z]*[iEr]
\\x1b in a sed script	${B}sed .*\\\\x1[bB]
grep -P	${B}grep( +-[a-zA-Z]+)* +-[a-zA-Z]*P
echo -e	${B}echo +-[a-zA-Z]*e
mktemp -t	${B}mktemp( +-[a-zA-Z]+)* +-[a-zA-Z]*t
a Homebrew prefix	/opt/home[b]rew
/usr/local/bin	/usr/local/bin
open -g	${B}open +-g
osascript	${B}osascript${E}
pbcopy	${B}pbcopy${E}
timeout	${B}timeout +[^[:space:]=:]
gensub	${B}gensub${E}
asort	${B}asorti?${E}
multibyte in an awk bracket	/[^/]*\\[[^]/]*${MB}[^]/]*\\][^/]*/"

# Only in the hook: tmux must be "$TMUX_BIN", never a bare command.
HOOK_RULE="bare tmux (use \"\$TMUX_BIN\")	(^|[;&|({[:space:]]|\\\$\\()tmux( |$)"

tmp=$(mktemp "${TMPDIR:-/tmp}/bellhop-lint.XXXXXX") || exit 2
trap 'rm -f "$tmp"' EXIT

problems=0
for f in "${files[@]}"; do
  [ -f "$f" ] || { echo "$f: no such file" >&2; problems=$((problems + 1)); continue; }
  # The lines to check, line numbers kept (skipped lines become empty).
  doctor=0
  case $f in libexec/bellhop-doctor) doctor=1 ;; esac
  awk -v doctor="$doctor" '
    /^[ \t]*#/ || /# portable-ok:/ { print ""; next }
    doctor && /(^|[^_[:alnum:]])(say|die|warn|printf)[ \t]/ {
      s = $0; gsub(/"([^"\\]|\\.)*"/, "\"\"", s); gsub(/\047[^\047]*\047/, "\047\047", s); print s; next
    }
    { print }' "$f" >"$tmp"
  rules=$RULES
  case $f in bin/bellhop-hook) rules=$rules$'\n'$HOOK_RULE ;; esac
  while IFS=$'\t' read -r label re; do
    [ -n "$re" ] || continue
    while IFS=: read -r n _; do
      echo "$f:$n: $label"
      problems=$((problems + 1))
    done < <(grep -nE -- "$re" "$tmp" || true)
  done <<<"$rules"
done

if [ "$problems" -gt 0 ]; then
  echo "lint-portability: $problems problem(s); move OS differences into lib/bellhop/compat.sh," \
    "or mark a deliberate line with '# portable-ok: <reason>'" >&2
  exit 1
fi
echo "lint-portability: ok (${#files[@]} files)"

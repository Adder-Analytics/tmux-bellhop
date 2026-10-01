#!/usr/bin/env bash
# demo/teardown.sh: stops the demo server (tmux -L bellhop-demo) and removes
# its temporary HOME. Works from a fresh shell (`make try-clean`): the demo
# root comes from the server's environment, else from the env file setup.sh
# wrote. It deletes only a folder named bellhop-demo.* that is a direct child of
# the temp folder and is owned by this user, and reads the env file only when
# this user owns it (on Linux, /tmp is shared with other users).
#
# No save may outlive the server: closing the demo's tabs fires bellhop's save
# hooks, and a save that starts after the server is gone can't read
# @bellhop-autosave, so it would recreate home/.local/state/bellhop after the
# folder was removed. So the hooks go first, autosave goes off for any save
# already started, and the folder is removed only once no save of this
# checkout is still running.
set -uo pipefail
SOCK=bellhop-demo
ENVF=${TMPDIR:-/tmp}/bellhop-demo.env
REPO=$(CDPATH='' cd -P -- "$(dirname -- "$0")/.." && pwd -P)
T() { env -u TMUX tmux -L "$SOCK" "$@"; }

root=$(T show-environment -g DEMO_ROOT 2>/dev/null || true)
root=${root#DEMO_ROOT=}
case $root in -* | '') root='' ;; esac
if [ -z "$root" ] && [ -f "$ENVF" ] && [ ! -L "$ENVF" ] && [ -O "$ENVF" ]; then
  root=$(LC_ALL=C sed -n 's/^declare -x DEMO_ROOT="\(.*\)"$/\1/p; s/^export DEMO_ROOT="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$ENVF" | head -n 1)
fi

if T has-session 2>/dev/null; then
  for h in after-new-window window-unlinked session-closed; do
    T set-hook -gu "${h}[77]" 2>/dev/null || true
  done
  T set-option -g @bellhop-autosave off 2>/dev/null || true
fi
T kill-server 2>/dev/null || true

# saves_running: true while a `save` of this checkout (a hook's run-shell, the
# dispatcher or libexec/bellhop-layout) is still alive.
saves_running() {
  ps -ww -eo args= 2>/dev/null | LC_ALL=C awk -v r="$REPO/" '
    index($0, r) && / save( |$)/ { found = 1 }
    END { exit !found }'
}
n=0
while [ "$n" -lt 50 ] && saves_running; do # up to 5 s
  sleep 0.1
  n=$((n + 1))
done

# safe_root: true when $root is ours to delete: no . or .. part, a direct
# child of the (physical) temp folder, named bellhop-demo.*, a real folder
# (not a link) owned by this user.
safe_root() {
  local tmpd
  case $root/ in /*) ;; *) return 1 ;; esac
  case $root/ in */../* | */./* | *//*) return 1 ;; esac
  tmpd=$(CDPATH='' cd -P -- "${TMPDIR:-/tmp}" 2>/dev/null && pwd -P) || return 1
  [ "${root%/*}" = "$tmpd" ] || return 1
  [ -d "$root" ] && [ ! -L "$root" ] && [ -O "$root" ]
}
case $root in
  */bellhop-demo.*)
    if safe_root; then
      rm -rf -- "$root"
      # A save that slipped past the wait (it was between ps and rm): once more.
      sleep 0.3
      [ ! -d "$root" ] || rm -rf -- "$root"
    fi
    ;;
esac
if [ -O "$ENVF" ] || [ -L "$ENVF" ]; then rm -f -- "$ENVF"; fi
exit 0

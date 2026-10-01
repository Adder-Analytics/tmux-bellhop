#!/usr/bin/env bash
# demo/setup.sh: builds the fictional demo server `tmux -L bellhop-demo` from
# demo/world.tsv, under a temporary HOME. It never touches the caller's HOME,
# tmux.conf or default tmux server. Silent unless --attach.
#
#   demo/setup.sh                   build it (a tape attaches itself)
#   demo/setup.sh --attach          build it and attach (`make try`); inside
#                                   tmux it opens in a popup, never nested
#   demo/setup.sh --restore-scene   build it, save its layout, stop the server
#                                   (the restore tape brings it back)
#
# DEMO_RING_NOW=1 rings the "rang" tabs at once instead of waiting for a client.
# The env a shell needs to use the demo (HOME, PATH, BELLHOP_NOW ...) is written
# to ${TMPDIR:-/tmp}/bellhop-demo.env; source that, never this script.
set -euo pipefail
REPO=$(CDPATH='' cd -P -- "$(dirname -- "$0")/.." && pwd -P)
SOCK=bellhop-demo
MODE=${1:-}
case $MODE in
  '' | --attach | --restore-scene) ;;
  *)
    echo "usage: demo/setup.sh [--attach | --restore-scene]" >&2
    exit 2
    ;;
esac
OUTER_TMUX=${TMUX:-} # the caller's tmux, for --attach's popup
"$REPO/demo/teardown.sh" >/dev/null 2>&1 || true

DEMO_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/bellhop-demo.XXXXXX")
# The physical path (macOS's $TMPDIR is behind a symlink), so the folders tmux
# reports for panes start with $HOME and print as ~/...
DEMO_ROOT=$(CDPATH='' cd -P -- "$DEMO_ROOT" && pwd -P)
# The system bash (bash 3.2 on macOS) runs the demo, so no frame shows a
# package manager's path; a link to it goes first on PATH for `env bash`.
BASH_BIN=/bin/bash
[ -x "$BASH_BIN" ] || BASH_BIN=$(command -v bash)
mkdir -p "$DEMO_ROOT/bin"
ln -s "$BASH_BIN" "$DEMO_ROOT/bin/bash"

export REPO BELLHOP_ROOT="$REPO" SHELL="$BASH_BIN" DEMO_ROOT \
  HOME="$DEMO_ROOT/home" USER=demo LOGNAME=demo TZ=UTC LANG=C.UTF-8 \
  XDG_CONFIG_HOME="$DEMO_ROOT/home/.config" XDG_STATE_HOME="$DEMO_ROOT/home/.local/state" \
  BELLHOP_NOW=1767225600 BELLHOP_FOCUS_CMD='' \
  PATH="$REPO/demo/bin:$REPO/bin:$DEMO_ROOT/bin:$PATH" \
  PS1='\W \$ ' HISTFILE=/dev/null BASH_SILENCE_DEPRECATION_WARNING=1
unset TMUX TMUX_PANE CLAUDE_CONFIG_DIR BELLHOP_MAP BELLHOP_STATE_DIR BELLHOP_LAYOUT \
  BELLHOP_CLAUDE_SETTINGS FZF_DEFAULT_OPTS FZF_DEFAULT_OPTS_FILE PROMPT_COMMAND
case $HOME in
  "$DEMO_ROOT"/*) ;;
  *)
    echo "refusing: HOME not under demo root" >&2
    exit 1
    ;;
esac

# Every server started under this HOME (including the one `bellhop restore`
# starts) gets the demo look.
mkdir -p "$HOME" "$XDG_CONFIG_HOME/bellhop" "$XDG_CONFIG_HOME/tmux"
printf 'source-file "%s/demo/tmux.conf"\n' "$REPO" | tee "$HOME/.tmux.conf" >"$XDG_CONFIG_HOME/tmux/tmux.conf"
# REPO and DEMO_ROOT are exported before the first T: tmux.conf's $REPO
# expands, and the server's global environment holds DEMO_ROOT for teardown.
T() { tmux -L "$SOCK" "$@"; }

WORLD=$REPO/demo/world.tsv
# The map from world.tsv; mobile's folder is never created.
LC_ALL=C awk -F '\t' '$1 == "map" { print $2 "  " $3 "  " $4 }' "$WORLD" >"$XDG_CONFIG_HOME/bellhop/map"
for d in api web docs infra; do mkdir -p "$HOME/src/$d"; done

# Sessions and tabs in world order: Claude panes run fake-claude, shells bash.
while IFS=$'\t' read -r kind sess idx name title state _age screen _sfx; do
  [ "$kind" = tab ] || continue
  dir=$HOME/src/$sess
  [ -d "$dir" ] || dir=$HOME
  # PS1 on the command line: the non-interactive `bash -c` tmux runs it through drops it.
  cmd="env PS1='\\W \\\$ ' bash --norc --noprofile"
  if [ "$screen" != - ]; then cmd="fake-claude $screen"; fi
  if ! T has-session -t "=$sess" 2>/dev/null; then
    T new-session -d -s "$sess" -n "$name" -c "$dir" -x 160 -y 44 "$cmd"
  else
    T new-window -d -t "=$sess:" -n "$name" -c "$dir" "$cmd"
  fi
  # A pane's title defaults to the host name; shells get their tab's name.
  if [ "$title" = - ]; then title=$name; fi
  T select-pane -t "=$sess:$idx" -T "$title"
done <"$WORLD"
T set -g automatic-rename off # names stay as world.tsv says

sock=$(T display-message -p '#{socket_path}')
pid=$(T display-message -p '#{pid}')
# State through the real hook, fed fake JSON, exactly as the tests do.
feed() { # pane event session-id [message]
  printf '{"hook_event_name":"%s","session_id":"%s","message":"%s"}' "$2" "$3" "${4:-}" |
    TMUX="$sock,$pid,0" TMUX_PANE="$1" "$REPO/bin/bellhop-hook"
}
while IFS=$'\t' read -r kind sess idx _name _title state age _screen sfx; do
  [ "$kind" = tab ] && [ "$sfx" != - ] || continue
  p=$(T display-message -p -t "=$sess:$idx" '#{pane_id}')
  id=00000000-0000-4000-8000-0000000000$sfx
  feed "$p" SessionStart "$id"
  case $state in working | needs-you | finished) feed "$p" UserPromptSubmit "$id" ;; esac
  case $state in
    needs-you)
      note=$(LC_ALL=C awk -F '\t' -v s="$sess" -v i="$idx" '$1 == "note" && $2 == s && $3 == i { print $4 }' "$WORLD")
      feed "$p" Notification "$id" "$note"
      ;;
    finished) feed "$p" Stop "$id" ;;
  esac
  T set-option -p -t "$p" @bellhop_since $((BELLHOP_NOW - age))
  case $state in needs-you | finished) T set-option -p -t "$p" @bellhop_rang $((BELLHOP_NOW - age)) ;; esac
done <"$WORLD"

# Rings api:1 infra:2 web:1 docs:1 once a client attaches, and re-pins @bellhop_rang.
if [ "$MODE" != --restore-scene ]; then
  ("$REPO/demo/ring.sh" </dev/null >/dev/null 2>&1 &)
fi

# The env a tape's shell (or `make try`) needs, at a fixed path. Never source
# setup.sh itself: its set -e would end the shell on the first error.
export -p | grep -E ' (REPO|DEMO_ROOT|HOME|USER|LOGNAME|SHELL|TZ|LANG|XDG_[A-Z_]+|BELLHOP_[A-Z_]+|PATH|PS1|HISTFILE|BASH_SILENCE_DEPRECATION_WARNING)=' \
  >"${TMPDIR:-/tmp}/bellhop-demo.env"

case $MODE in
  --restore-scene)
    # A plain save waits for the hook's background saves to let go of the
    # lock (-L: never the caller's default server).
    bellhop save -L "$SOCK"
    T set -g @bellhop-autosave off # the closing hooks must not overwrite the snapshot
    T kill-server
    ;;
  --attach)
    if [ -n "${OUTER_TMUX:-}" ]; then
      # Inside the caller's tmux: a popup of it, never a nested attach. The
      # popup runs with the caller's server env, so it names the socket itself.
      echo "demo keys: C-b i · C-b / · C-b m · C-b d leaves"
      exec env TMUX="$OUTER_TMUX" tmux display-popup -E -w 95% -h 95% \
        "env -u TMUX $(printf %q "$(command -v tmux)") -L $SOCK attach -t =api:3"
    fi
    echo "demo keys: C-b i · C-b / · C-b m · C-b d leaves"
    sleep 1
    exec env -u TMUX tmux -L "$SOCK" attach -t "=api:3"
    ;;
esac

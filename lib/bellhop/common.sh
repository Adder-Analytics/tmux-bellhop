# shellcheck shell=bash
# lib/bellhop/common.sh: what the bellhop commands share. Sourced, never run.
#
#   options    bh_opt NAME [DEFAULT] · bh_opt_set NAME
#   messages   say MSG · warn MSG · die MSG [CODE]
#   the map    bh_map_path · bh_map_rows [--warn] · bh_slot_of_session NAME
#              bh_slot_dir DIGIT · bh_slot_session DIGIT
#   panes      bh_panes [--autorename]  (the 16 columns every tool reads)
#   jump       bh_jump WINDOW [PANE] [CLIENT]  (with the focus-adapter seam)
#   fzf        bh_fzf ARGS... · bh_fzf_version · bh_fzf_check [CLIENT] · bh_version_ge A B
#   preview    bh_sanitize (filter) · bh_preview PANE
#   state      bh_badge STATE · $BH_AWK_BADGE
#   state dir  bh_socket_name [SOCKET] · bh_state_dir [SOCKET]
#   text       plural N WORD [SUFFIX] · tildify PATH · session_name DIR
#
# Sets BH_ROOT (the plugin folder) and BH_LIB. bash 3.2 compatible and safe
# under set -euo pipefail. Every awk here runs under LC_ALL=C.

[ -z "${_BH_COMMON_LOADED:-}" ] || return 0
_BH_COMMON_LOADED=1

BH_LIB=$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC2034 # used by the scripts that source this file
BH_ROOT=$(CDPATH='' cd -P -- "$BH_LIB/../.." && pwd -P)
# shellcheck source=compat.sh
. "$BH_LIB/compat.sh"
# shellcheck source=width.awk.sh
. "$BH_LIB/width.awk.sh"

BH_FZF_MIN=0.42
# shellcheck disable=SC2034 # used by bellhop.tmux and doctor
BH_TMUX_MIN=3.3

# ── options ──────────────────────────────────────────────────────────────────
# bh_opt NAME [DEFAULT]: the global tmux option @bellhop-NAME (or NAME when it
# starts with @), else DEFAULT when it is unset or empty.
bh_opt() {
  local name=$1 v
  case $name in @*) ;; *) name=@bellhop-$name ;; esac
  v=$(tmux show-options -gqv "$name" 2>/dev/null || true)
  printf '%s\n' "${v:-${2:-}}"
}

# bh_opt_set NAME: true when the option is set, even to ''.
bh_opt_set() {
  local name=$1
  case $name in @*) ;; *) name=@bellhop-$name ;; esac
  [ -n "$(tmux show-options -gq "$name" 2>/dev/null || true)" ]
}

# ── messages ─────────────────────────────────────────────────────────────────
# say: to the popup's client when BH_CLIENT is set (display-message reads
# formats, so # is doubled), else to stdout. warn and die: stderr, prefixed
# "bellhop <cmd>:" from BH_CMD.
say() {
  if [ -n "${BH_CLIENT:-}" ]; then
    local m=$1
    tmux display-message -c "$BH_CLIENT" -d 2500 "${m//#/##}" 2>/dev/null || printf '%s\n' "$1" >&2
  else
    printf '%s\n' "$1"
  fi
}

warn() { printf 'bellhop%s: %s\n' "${BH_CMD:+ $BH_CMD}" "$*" >&2; }

die() {
  warn "$1"
  exit "${2:-1}"
}

# ── text ─────────────────────────────────────────────────────────────────────
plural() {
  if [ "$1" -eq 1 ]; then echo "$1 $2"; else echo "$1 $2${3:-s}"; fi
}

# For display only. Where /tmp is a link to /private/tmp (macOS), a resolved
# /private/tmp/… path is shown as the /tmp/… the user typed.
tildify() {
  case $1 in
    "$HOME") printf '~' ;;
    "$HOME"/*) printf '~%s' "${1#"$HOME"}" ;;
    /private/tmp | /private/tmp/*)
      if [ /tmp -ef /private/tmp ]; then tildify "${1#/private}"; else printf '%s' "$1"; fi
      ;;
    *) printf '%s' "$1" ;;
  esac
}

# A session name for a folder: its basename, with . : and whitespace as _.
session_name() { basename -- "$1" | tr '.: \t' '____'; }

# ── the session map ──────────────────────────────────────────────────────────
bh_map_path() {
  printf '%s\n' "${BELLHOP_MAP:-${XDG_CONFIG_HOME:-$HOME/.config}/bellhop/map}"
}

# bh_map_rows [--warn]: slot TAB session TAB dir TAB pinned, one per slot.
# With a map file: its valid lines in digit order, pinned=1 (a bad line is
# skipped; --warn says why on stderr). Without one: the running sessions in
# list-sessions order numbered 1-9 then 0, pinned=0.
# (--warn is passed from libexec/bellhop-map and bellhop-doctor, which an
# older shellcheck checking this file alone cannot see.)
# shellcheck disable=SC2120
bh_map_rows() {
  local warn='' f
  [ "${1:-}" != --warn ] || warn=1
  f=$(bh_map_path)
  if [ -f "$f" ]; then
    LC_ALL=C awk -v OFS='\t' -v warn="$warn" -v file="$(tildify "$f")" '
      function bad(m) { if (warn) printf "%s:%d: %s; line skipped\n", file, FNR, m > "/dev/stderr" }
      BEGIN { home = ENVIRON["HOME"] }
      { sub(/\r$/, "") }
      /^[ \t]*#/ || /^[ \t]*$/ { next }
      {
        d = $1; s = $2; rest = $0
        sub(/^[ \t]*[^ \t]+[ \t]*/, "", rest)
        sub(/^[^ \t]+[ \t]*/, "", rest)
        sub(/[ \t]+$/, "", rest)
        if (d !~ /^[0-9]$/) { bad("bad digit \"" d "\""); next }
        if (s == "" || s ~ /[.:]/) { bad("bad session name \"" s "\" (no . : or spaces)"); next }
        if (d in seen) { bad("duplicate digit " d " (line " seen[d] " wins)"); next }
        seen[d] = FNR
        if (rest == "" || rest == "~") rest = home
        else if (substr(rest, 1, 2) == "~/") rest = home substr(rest, 2)
        print d, s, rest, 1
      }' "$f" | LC_ALL=C sort -t "$(printf '\t')" -k1,1n
  else
    tmux list-sessions -F $'#{s/\t/ /:session_name}\t#{s/\t/ /:session_path}' 2>/dev/null |
      LC_ALL=C awk -F '\t' -v OFS='\t' 'NR <= 10 { print (NR == 10 ? 0 : NR), $1, $2, 0 }'
  fi
  return 0
}

bh_slot_of_session() {
  bh_map_rows | LC_ALL=C awk -F '\t' -v s="$1" '$2 == s { print $1; exit }'
}

bh_slot_dir() {
  bh_map_rows | LC_ALL=C awk -F '\t' -v d="$1" '$1 == d { print $3; exit }'
}

bh_slot_session() {
  bh_map_rows | LC_ALL=C awk -F '\t' -v d="$1" '$1 == d { print $2; exit }'
}

# ── panes ────────────────────────────────────────────────────────────────────
# bh_panes: one tab-separated line per pane on the server, the one reading of
# what is where that inbox, find and save share:
#   slot session session_id window_id window_index window_name bell pane_id
#   active command path title state since claude_session note
# state is what the pane's Claude is doing, from its title and the pane options
# bin/bellhop-hook keeps: working (a spinner in the title), needs-you (a
# permission prompt), finished (✳ and the window rang), idle (✳ or a known
# session), else none. The slot is empty for a session off the map.
# --autorename (internal, for save) adds a 17th column: the window's
# automatic-rename as 1 or 0.
bh_panes() {
  local fmt ar=''
  [ "${1:-}" != --autorename ] || ar=1
  # Fields come from tmux tab-separated, and tmux itself turns a tab inside a
  # title, note, name or path into a space (the s/ modifier) before printing,
  # so the columns can't shift. Tab is the one separator every tmux passes
  # through: from 3.4 the client spells any other control byte in command
  # output out as \ooo.
  fmt=$'#{s/\t/ /:session_name}\t#{session_id}\t#{window_id}\t#{window_index}\t#{s/\t/ /:window_name}\t#{window_bell_flag}\t#{pane_id}\t#{pane_active}\t#{s/\t/ /:pane_current_command}\t#{s/\t/ /:pane_current_path}\t#{s/\t/ /:pane_title}\t#{@bellhop_state}\t#{@bellhop_since}\t#{@bellhop_session}\t#{s/\t/ /:@bellhop_note}'
  [ -z "$ar" ] || fmt=$fmt$'\t#{automatic-rename}'
  # Spinners are an alternation, never a bracket: in byte mode a bracket of
  # multibyte characters is a set of bytes that holds 0xE2, the lead byte of ✳.
  tmux list-panes -a -F "$fmt" 2>/dev/null |
    LC_ALL=C awk -F '\t' -v OFS='\t' -v ar="$ar" '
      FILENAME == ARGV[1] { if (split($0, s, "\t") >= 2) slot[s[2]] = s[1]; next }
      {
        c = "none"
        if ($11 ~ /◐|◓|◑|◒/) c = "working"
        else if ($12 == "needs-you") c = "needs-you"
        else if ($11 ~ /✳/ && $6 == 1) c = "finished"
        else if ($11 ~ /✳/ || $14 != "") c = "idle"
        # A braille spinner (U+2800-28FF, bytes E2 A0-A3 ..) is working too.
        if (c == "idle" && $11 ~ /^\342[\240-\243]/) c = "working"
        line = ($1 in slot ? slot[$1] : "") OFS $1 OFS $2 OFS $3 OFS $4 OFS $5 OFS $6 OFS $7 OFS $8 OFS $9 OFS $10 OFS $11 OFS c OFS $13 OFS $14 OFS $15
        if (ar != "") { a = $16; if (a == "on") a = 1; else if (a == "off") a = 0; line = line OFS a }
        print line
      }' <(bh_map_rows) -
}

# ── jump ─────────────────────────────────────────────────────────────────────
# bh_jump WINDOW [PANE] [CLIENT]: go to a tab wherever it is.
#  1. select the window (and pane) in its session;
#  2. with a focus adapter ($BELLHOP_FOCUS_CMD, else @bellhop-focus-cmd), when
#     another client shows that session and the caller is not on it: run
#     `<cmd> <slot-or-empty> <session> <window-id>` for at most 2 s; exit 0
#     means a terminal showing that session is now focused, and we stop;
#  3. else switch CLIENT (or, inside tmux, the current client) to the window;
#  4. else, outside tmux with no client: a hint on stderr, return 2.
bh_jump() {
  local win=${1:-} pane=${2:-} client=${3:-} info sid sess focus caller others slot
  [ -n "$win" ] || { warn "jump: which window?"; return 2; }
  info=$(tmux display-message -p -t "$win" $'#{session_id}\t#{s/\t/ /:session_name}') || return 1
  sid=${info%%$'\t'*} sess=${info#*$'\t'}
  tmux select-window -t "$win"
  [ -z "$pane" ] || tmux select-pane -t "$pane"
  if [ -n "${BELLHOP_FOCUS_CMD+set}" ]; then
    focus=$BELLHOP_FOCUS_CMD
  else
    focus=$(tmux show-options -gqv @bellhop-focus-cmd 2>/dev/null || true)
  fi
  case $focus in \~/*) focus=$HOME/${focus#\~/} ;; esac
  if [ -n "$focus" ]; then
    caller=
    [ -z "$client" ] || caller=$(tmux display-message -p -c "$client" '#{session_id}' 2>/dev/null || true)
    others=$(tmux list-clients -t "$sid" -F '#{client_name}' 2>/dev/null | LC_ALL=C awk -v c="$client" '$0 != c' || true)
    if [ -n "$others" ] && [ "$caller" != "$sid" ]; then
      slot=$(bh_slot_of_session "$sess")
      if (
        export BELLHOP_TMUX="$TMUX_BIN"
        bh_watchdog 2 "$focus" "$slot" "$sess" "$win"
      ) </dev/null >/dev/null 2>&1; then
        return 0
      fi
    fi
  fi
  if [ -n "$client" ]; then
    tmux switch-client -c "$client" -t "$win"
  elif [ -n "${TMUX:-}" ]; then
    tmux switch-client -t "$win"
  else
    printf "bellhop: no client to switch; run: tmux attach -t '=%s'\n" "$sess" >&2
    return 2
  fi
}

# ── fzf ──────────────────────────────────────────────────────────────────────
# bh_fzf ARGS...: fzf without the user's FZF_DEFAULT_OPTS (a --bind or --exact
# there could eat ctrl-g or the digits), full height, then @bellhop-fzf-opts
# (word-split on purpose; no quoting inside).
bh_fzf() {
  local extra
  extra=$(tmux show-options -gqv @bellhop-fzf-opts 2>/dev/null || true)
  (
    set -f
    # shellcheck disable=SC2086 # @bellhop-fzf-opts is split into words on purpose
    exec env -u FZF_DEFAULT_OPTS -u FZF_DEFAULT_OPTS_FILE "${BELLHOP_FZF:-fzf}" --height=100% "$@" $extra
  )
}

bh_fzf_version() {
  "${BELLHOP_FZF:-fzf}" --version 2>/dev/null | LC_ALL=C awk 'NR == 1 { print $1 }'
}

# bh_version_ge A B: true when dotted version A >= B ("3.3a" reads as 3.3).
bh_version_ge() {
  LC_ALL=C awk -v a="$1" -v b="$2" 'BEGIN {
    split(a, x, "."); split(b, y, ".")
    for (i = 1; i <= 3; i++) { p = x[i] + 0; q = y[i] + 0; if (p > q) exit 0; if (p < q) exit 1 }
    exit 0 }'
}

# bh_fzf_check [CLIENT]: true when fzf >= 0.42; otherwise says so (on CLIENT's
# status line when given, else stderr) and returns 1.
bh_fzf_check() {
  local v msg
  v=$(bh_fzf_version || true)
  if [ -n "$v" ] && bh_version_ge "$v" "$BH_FZF_MIN"; then return 0; fi
  msg="bellhop: needs fzf ≥ $BH_FZF_MIN (found ${v:-none}) · bellhop doctor"
  if [ -n "${1:-}" ]; then
    tmux display-message -c "$1" -d 5000 "$msg" 2>/dev/null || printf '%s\n' "$msg" >&2
  else
    printf '%s\n' "$msg" >&2
  fi
  return 1
}

# ── preview ──────────────────────────────────────────────────────────────────
# bh_sanitize: a pane capture made safe to draw. Keeps SGR colour sequences and
# tabs; deletes OSC strings (titles, clipboard writes), every other CSI
# sequence, other escape sequences and C0 controls; drops the blank lines under
# the prompt; keeps the last ${FZF_PREVIEW_LINES:-40} lines.
bh_sanitize() {
  LC_ALL=C awk '
    {
      s = $0
      gsub(/\033\][^\007\033]*(\007|\033\\)/, "", s)
      gsub(/\033\][^\007\033]*$/, "", s)
      gsub(/\033\[[0-9;:?<>=]*[ -\/]*[@-ln-~]/, "", s)
      gsub(/\033\[[0-9;:?<>=]*[ -\/]*$/, "", s)
      gsub(/\033[()*+#%-.\/][^\033]/, "", s)
      gsub(/\033[^[]/, "", s)
      gsub(/\033$/, "", s)
      gsub(/[\001-\010\013-\032\034-\037\177]/, "", s)
      line[NR] = s
      t = s
      gsub(/\033\[[0-9;:]*m/, "", t)
      if (t ~ /[^ \t]/) last = NR
    }
    END { for (i = 1; i <= last; i++) print line[i] }' | tail -n "${FZF_PREVIEW_LINES:-40}"
}

bh_preview() {
  tmux capture-pane -p -e -t "$1" 2>/dev/null | bh_sanitize
}

# ── state badges ─────────────────────────────────────────────────────────────
# One palette for inbox and find (docs/how-it-works.md states it).
BH_BADGE_NEEDS_YOU='1;31'
BH_BADGE_FINISHED='38;5;214'
BH_BADGE_WORKING='34'
BH_BADGE_IDLE='2'

bh_badge() {
  case ${1:-} in
    needs-you) echo "$BH_BADGE_NEEDS_YOU" ;;
    finished) echo "$BH_BADGE_FINISHED" ;;
    working) echo "$BH_BADGE_WORKING" ;;
    idle) echo "$BH_BADGE_IDLE" ;;
    *) echo 0 ;;
  esac
}

# awk: badge(state) is the SGR parameter string, badge_label(state) the word.
# shellcheck disable=SC2034 # used by the scripts that source this file
BH_AWK_BADGE='
function badge(s) {
  if (s == "needs-you") return "'"$BH_BADGE_NEEDS_YOU"'"
  if (s == "finished") return "'"$BH_BADGE_FINISHED"'"
  if (s == "working") return "'"$BH_BADGE_WORKING"'"
  if (s == "idle") return "'"$BH_BADGE_IDLE"'"
  return "0"
}
function badge_label(s) { return s == "needs-you" ? "needs you" : s }
'

# ── state directory ──────────────────────────────────────────────────────────
# The socket's basename: from the argument (-L NAME or a socket path), else
# $TMUX, else "default".
bh_socket_name() {
  local s=${1:-}
  if [ -z "$s" ] && [ -n "${TMUX:-}" ]; then s=${TMUX%%,*}; fi
  [ -n "$s" ] || s=default
  basename -- "$s"
}

bh_state_dir() {
  printf '%s/%s\n' "$(bh_state_root)" "$(bh_socket_name "${1:-}")"
}

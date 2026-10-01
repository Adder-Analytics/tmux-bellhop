#!/usr/bin/env bash
# bellhop.tmux: the plugin entry point. TPM runs it; without TPM, add
#   run-shell /path/to/tmux-bellhop/bellhop.tmux
# at the end of tmux.conf. It changes only the running server, never tmux.conf:
#   - up to three prefix keys (inbox, find, move), never over a key you bound
#     yourself (see "never-clobber" below), each with a note for `prefix ?`;
#   - three save hooks at index [77] (after-new-window, window-unlinked,
#     session-closed), off with @bellhop-autosave off;
#   - the server options @bellhop-root and, when keys were skipped,
#     @bellhop-skipped; @bellhop-prev-<key> records what a key did before
#     (@bellhop-prevnote-<key> its prefix ? note);
#   - automatic-rename-format, only with @bellhop-tab-titles on.
#
#   bellhop.tmux          load (idempotent: re-sourcing replaces, never stacks)
#   bellhop.tmux unload   take our keys and hooks back off the running server
#
# Never-clobber: a key set through @bellhop-<tool>-key is always bound ('' =
# none). A default key is bound only when it is unbound, still does what stock
# tmux does, or is already ours.
#
# Silent on purpose: run-shell shows a script's output in the pane.
exec >/dev/null 2>&1

_self=${BASH_SOURCE[0]}
_n=0
while [ -L "$_self" ] && [ "$_n" -lt 40 ]; do
  _l=$(readlink "$_self")
  case $_l in
    /*) _self=$_l ;;
    *) _self=$(dirname "$_self")/$_l ;;
  esac
  _n=$((_n + 1))
done
ROOT=$(CDPATH='' cd -P -- "$(dirname -- "$_self")" && pwd -P) || exit 0
# shellcheck source=lib/bellhop/common.sh
. "$ROOT/lib/bellhop/common.sh" || exit 0
[ -n "${TMUX_BIN:-}" ] || exit 0

BIN=$ROOT/bin/bellhop
# run-shell expands formats in its command: a '#' in the path is written '##'.
BINF=${BIN//\#/##}
MINE="'$BINF' "
HOOKS="after-new-window window-unlinked session-closed"
HOOK_CMD="run-shell -b \"[ -x '$BINF' ] && '$BINF' save --from-hook || true\""
# Tabs with a Claude title (✳, a spinner or braille, then a space) are named
# after it, glyph stripped; every other tab keeps tmux's default name.
TITLE_FMT='#{?#{m/r:^(✳|◐|◓|◑|◒|[⠀-⣿]) ,#{pane_title}},#{s/^[^ ]+ //:pane_title},#{?pane_in_mode,[tmux],#{pane_current_command}}#{?pane_dead,[dead],}}' # portable-ok: a tmux regex, not awk

opt() { tmux show-options -gqv "$1" 2>/dev/null || true; }
opt_set() { [ -n "$(tmux show-options -gq "$1" 2>/dev/null || true)" ]; }

KEYS=
read_keys() { KEYS=$(tmux list-keys -T prefix 2>/dev/null || true); }

# A key as list-keys prints it (\# or '"') back to what bind-key takes.
unquote_key() {
  local k=$1
  case $k in
    \\?*) k=${k#\\} ;;
    \'*\') k=${k#\'} k=${k%\'} ;;
    \"*\") k=${k#\"} k=${k%\"} ;;
  esac
  printf '%s' "$k"
}

# The prefix-table line for a key, from one list-keys call.
key_line() {
  local want=$1 line k
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    k=$(printf '%s\n' "$line" | LC_ALL=C awk '{ i = ($2 == "-r") ? 5 : 4; print $i }')
    if [ "$(unquote_key "$k")" = "$want" ]; then
      printf '%s\n' "$line"
      return 0
    fi
  done <<<"$KEYS"
  return 0
}

# The prefix ? note of a key ('' when it has none). list-keys -N -P '' prints
# " KEY<spaces>NOTE", the key unquoted.
key_note() {
  tmux list-keys -N -P '' -T prefix 2>/dev/null |
    LC_ALL=C awk -v k="$1" '$1 == k { sub(/^ *[^ ]+ +/, ""); print; exit }'
}

# The command part of a list-keys line.
cmd_of() {
  printf '%s\n' "$1" | LC_ALL=C awk '{ sub(/^bind-key +(-r +)?-T +[^ ]+ +[^ ]+ +/, ""); print }'
}

key_of() {
  unquote_key "$(printf '%s\n' "$1" | LC_ALL=C awk '{ i = ($2 == "-r") ? 5 : 4; print $i }')"
}

# Give a key back what it did before we bound it (or unbind it when it was
# unbound, or when nothing was recorded), and forget the record.
give_back() {
  local key=$1 prev tmp pnote
  if opt_set "@bellhop-prev-$key"; then
    prev=$(opt "@bellhop-prev-$key")
    pnote=$(opt "@bellhop-prevnote-$key")
    # The note (prefix ?) goes back too: list-keys lines don't carry it.
    if [ -n "$pnote" ] && [ -n "$prev" ]; then
      pnote=$(printf '%s\n' "$pnote" | LC_ALL=C sed 's/[\\"$]/\\&/g')
      prev="bind-key -N \"$pnote\" ${prev#bind-key}"
    fi
    if [ -n "$prev" ] && tmp=$(mktemp "${TMPDIR:-/tmp}/bellhop-prev.XXXXXX"); then
      printf '%s\n' "$prev" >"$tmp"
      tmux source-file "$tmp" || tmux unbind-key -T prefix "$key"
      rm -f "$tmp"
    else
      tmux unbind-key -T prefix "$key"
    fi
    tmux set-option -gu "@bellhop-prev-$key"
    tmux set-option -gu "@bellhop-prevnote-$key"
  else
    tmux unbind-key -T prefix "$key"
  fi
}

# Every key this root has bound (for one tool, when given), one per line.
our_keys() {
  local line
  while IFS= read -r line; do
    case $line in
      *"$MINE${1:-}"*) key_of "$line" && echo ;;
    esac
  done <<<"$KEYS"
}

SKIPPED=
SKIP_MSG=

# bind_tool TOOL DEFAULT-KEY STOCK-REGEX NOTE ARGS
bind_tool() {
  local tool=$1 def=$2 stock=$3 note=$4 args=$5 o key explicit='' line cmd k run
  o=@bellhop-$tool-key
  if opt_set "$o"; then
    key=$(opt "$o")
    explicit=1
  else
    key=$def
  fi
  # The option moved this tool to another key since the last load: hand the
  # old one back first.
  while IFS= read -r k; do
    [ -n "$k" ] && [ "$k" != "$key" ] || continue
    give_back "$k"
    read_keys
  done < <(our_keys "$tool ")
  [ -n "$key" ] || return 0

  line=$(key_line "$key")
  cmd=$(cmd_of "$line")
  if [ -z "$explicit" ] && [ -n "$line" ]; then
    case $cmd in
      *bellhop*) ;;
      *)
        if ! [[ $cmd =~ $stock ]]; then
          SKIPPED="$SKIPPED${SKIPPED:+ }$key"
          SKIP_MSG="$SKIP_MSG${SKIP_MSG:+ · }prefix $key is bound to something else; set $o to pick a key"
          return 0
        fi
        ;;
    esac
  fi
  # Remember what the key did, once: a re-source never overwrites the record.
  case $cmd in
    *bellhop*) ;;
    *)
      if ! opt_set "@bellhop-prev-$key"; then
        tmux set-option -g "@bellhop-prev-$key" "$line"
        k=$(key_note "$key")
        [ -z "$k" ] || tmux set-option -g "@bellhop-prevnote-$key" "$k"
      fi
      ;;
  esac

  run="'$BINF' $tool $args"
  if [ "$(opt @bellhop-demo-caption)" = on ]; then
    tmux bind-key -N "$note" -T prefix "$key" display-message -d 900 " ⌨ prefix $key " '\;' run-shell -b "$run"
  else
    tmux bind-key -N "$note" -T prefix "$key" run-shell -b "$run"
  fi
  read_keys
}

load() {
  local v num h
  v=$(tmux -V 2>/dev/null || true)
  num=$(printf '%s\n' "$v" | LC_ALL=C awk '{ if (match($0, /[0-9]+\.[0-9]+/)) print substr($0, RSTART, RLENGTH) }')
  if [ -n "$num" ] && ! bh_version_ge "$num" "$BH_TMUX_MIN"; then
    tmux display-message "bellhop needs tmux ≥ $BH_TMUX_MIN (you have ${v#tmux }); keys not bound"
    return 0
  fi

  tmux set-option -g @bellhop-root "$ROOT"
  read_keys
  bind_tool inbox i '^display-message$' 'bellhop: Claude inbox' \
    "'#{client_name}' '#{session_id}' '#{window_id}' '#{pane_id}'"
  bind_tool find / '^command-prompt -k -p key' 'bellhop: find a tab' \
    "'#{client_name}' '#{session_id}' '#{window_id}'"
  bind_tool move m '^select-pane -m$' 'bellhop: move tabs' \
    "'#{client_name}' '#{session_id}' '#{window_id}'"
  if [ -n "$SKIPPED" ]; then
    tmux set-option -g @bellhop-skipped "$SKIPPED"
    tmux display-message -d 5000 "bellhop: $SKIP_MSG"
  else
    tmux set-option -gu @bellhop-skipped
  fi

  for h in $HOOKS; do
    if [ "$(opt @bellhop-autosave)" = off ]; then
      unhook "$h"
    else
      tmux set-hook -g "${h}[77]" "$HOOK_CMD"
    fi
  done

  if [ "$(opt @bellhop-tab-titles)" = on ]; then
    tmux set-option -gw automatic-rename-format "$TITLE_FMT"
  else
    untitle
  fi
}

# Only a [77] hook that is ours; a user's own hook at 77 is left alone.
unhook() {
  case $(tmux show-hooks -g "${1}[77]" 2>/dev/null || true) in
    *bellhop*) tmux set-hook -gu "${1}[77]" ;;
  esac
}

untitle() {
  [ "$(tmux show-options -gwv automatic-rename-format 2>/dev/null || true)" != "$TITLE_FMT" ] ||
    tmux set-option -gwu automatic-rename-format
}

unload() {
  local k h
  read_keys
  while IFS= read -r k; do
    [ -n "$k" ] || continue
    give_back "$k"
  done < <(our_keys)
  for h in $HOOKS; do unhook "$h"; done
  untitle
  tmux set-option -gu @bellhop-skipped
  tmux set-option -gu @bellhop-root
}

case ${1:-} in
  unload) unload ;;
  *) load ;;
esac
exit 0

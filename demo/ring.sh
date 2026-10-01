#!/usr/bin/env bash
# demo/ring.sh: run by demo/setup.sh in the background. It waits up to 10 s
# for a client to attach to the demo server (not at all with DEMO_RING_NOW=1),
# then rings the bell in every needs-you and finished tab of demo/world.tsv
# (api:1 infra:2 web:1 docs:1), so tmux flags them, and pins @bellhop_rang
# back to the world's ages. It rings after the wait even with no client.
set -uo pipefail
REPO=${REPO:-$(CDPATH='' cd -P -- "$(dirname -- "$0")/.." && pwd -P)}
: "${BELLHOP_NOW:?run by demo/setup.sh}"
T() { env -u TMUX tmux -L bellhop-demo "$@"; }
if [ "${DEMO_RING_NOW:-}" != 1 ]; then
  n=0
  while [ "$n" -lt 50 ] && [ -z "$(T list-clients -F '#{client_name}' 2>/dev/null)" ]; do
    sleep 0.2
    n=$((n + 1))
  done
  sleep 0.5 # let the attach draw first
fi
while IFS=$'\t' read -r kind sess idx _name _title state age _rest; do
  [ "$kind" = tab ] || continue
  case $state in needs-you | finished) ;; *) continue ;; esac
  info=$(T display-message -p -t "=$sess:$idx" '#{pane_id} #{pane_tty}' 2>/dev/null) || continue
  pane=${info%% *} tty=${info#* }
  [ -n "$tty" ] && printf '\a' >"$tty" 2>/dev/null
  T set-option -p -t "$pane" @bellhop_rang $((BELLHOP_NOW - age))
done <"$REPO/demo/world.tsv"
exit 0

# shellcheck shell=bash
# lib/bellhop/compat.sh: every difference between operating systems lives here,
# and only here (scripts/lint-portability.sh enforces it). Sourced by every
# bellhop script, including bin/bellhop-hook, so it stays small, prints nothing
# and has no side effects beyond resolving the tmux binary.
#
#   bh_tmux                  resolve tmux into $TMUX_BIN; tmux() calls it
#   bh_state_root            the state root (per-socket dirs live below it)
#   bh_lock_backend          flock, lockf or mkdir: probed once per state root
#   bh_lock_open FD FILE     open FILE on FD for locking (records FILE for mkdir)
#   bh_lock FD SECS [FILE]   blocking lock, gives up after SECS
#   bh_lock_nb FD [FILE]     one try, no wait
#   bh_unlock FD [FILE]      release and close FD
#   bh_date EPOCH FMT        format an epoch (GNU or BSD date)
#   bh_locale                make LC_CTYPE a UTF-8 locale this system has
#   bh_realpath PATH         resolve symlinks, no readlink -f / realpath
#   bh_now                   $BELLHOP_NOW or the current epoch
#   bh_watchdog SECS CMD...  run CMD, kill it after SECS (no coreutils timeout)
#   bh_server_id             "<pid>.<start_time>" of the tmux server
#
# bash 3.2 compatible. Safe under set -euo pipefail.

[ -z "${_BH_COMPAT_LOADED:-}" ] || return 0
_BH_COMPAT_LOADED=1

# ── tmux ─────────────────────────────────────────────────────────────────────
# $BELLHOP_TMUX, else tmux on PATH, else the usual install places (a hook's or
# run-shell's PATH can be thin). Returns 1 when none resolves; TMUX_BIN is then
# empty and tmux() fails.
bh_tmux() {
  local c
  TMUX_BIN=
  if [ -n "${BELLHOP_TMUX:-}" ]; then
    case $BELLHOP_TMUX in
      */*) TMUX_BIN=$BELLHOP_TMUX ;;
      *) TMUX_BIN=$(type -P "$BELLHOP_TMUX" 2>/dev/null || true) ;;
    esac
  fi
  [ -n "$TMUX_BIN" ] || TMUX_BIN=$(type -P tmux 2>/dev/null || true)
  if [ -z "$TMUX_BIN" ]; then
    for c in /opt/homebrew/bin/tmux /usr/local/bin/tmux \
      /home/linuxbrew/.linuxbrew/bin/tmux /usr/bin/tmux; do
      if [ -x "$c" ]; then TMUX_BIN=$c; break; fi
    done
  fi
  [ -n "$TMUX_BIN" ]
}

tmux() { command "${TMUX_BIN:-tmux}" "$@"; }

bh_tmux || true

bh_server_id() { tmux display-message -p '#{pid}.#{start_time}' 2>/dev/null; }

# ── time ─────────────────────────────────────────────────────────────────────
bh_now() { printf '%s\n' "${BELLHOP_NOW:-$(date +%s)}"; }

# bh_date EPOCH FMT: FMT with or without the leading '+'. '%a %-d %b %H:%M'
# works on both GNU and BSD date.
bh_date() {
  local e=${1:-0} f=${2:-%c}
  case $f in +*) ;; *) f=+$f ;; esac
  if [ -z "${_BH_DATE_GNU:-}" ]; then
    if date --version >/dev/null 2>&1; then _BH_DATE_GNU=1; else _BH_DATE_GNU=0; fi
  fi
  if [ "$_BH_DATE_GNU" = 1 ]; then
    date -d "@$e" "$f"
  else
    date -r "$e" "$f"
  fi
}

# ── locale ───────────────────────────────────────────────────────────────────
_bh_is_utf8() {
  case ${1:-} in *[Uu][Tt][Ff]-8* | *[Uu][Tt][Ff]8*) return 0 ;; esac
  return 1
}

# When the effective LC_CTYPE is not UTF-8, export the first of C.UTF-8 and
# en_US.UTF-8 that `locale -a` lists, spelled exactly as it prints it (glibc
# says C.utf8, macOS C.UTF-8), and drop a non-UTF-8 LC_ALL that would override
# it. Returns 1 when no UTF-8 locale was found (nothing changed).
bh_locale() {
  local cur=${LC_ALL:-${LC_CTYPE:-${LANG:-}}} pick
  _bh_is_utf8 "$cur" && return 0
  pick=$(locale -a 2>/dev/null | LC_ALL=C awk '
    { n = tolower($0); gsub(/-/, "", n)
      if (n == "c.utf8" && c == "") c = $0
      if (n == "en_us.utf8" && e == "") e = $0 }
    END { print (c != "" ? c : e) }')
  [ -n "$pick" ] || return 1
  export LC_CTYPE="$pick"
  if [ -n "${LC_ALL:-}" ]; then unset LC_ALL; fi
  return 0
}

# ── paths ────────────────────────────────────────────────────────────────────
# bh_realpath PATH: the physical path, following every symlink (a loop of
# readlink and cd -P). The last component need not exist.
bh_realpath() {
  local p=$1 l d b n=0
  while [ -L "$p" ] && [ "$n" -lt 40 ]; do
    l=$(readlink "$p") || break
    case $l in
      /*) p=$l ;;
      *)
        d=$(dirname "$p")
        if [ "$d" = / ]; then p=/$l; else p=$d/$l; fi
        ;;
    esac
    n=$((n + 1))
  done
  if [ -d "$p" ]; then
    (CDPATH='' cd -P -- "$p" 2>/dev/null && pwd -P)
    return
  fi
  d=$(dirname "$p") b=$(basename "$p")
  d=$(CDPATH='' cd -P -- "$d" 2>/dev/null && pwd -P) || return 1
  if [ "$d" = / ]; then printf '/%s\n' "$b"; else printf '%s/%s\n' "$d" "$b"; fi
}

bh_state_root() {
  printf '%s\n' "${BELLHOP_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/bellhop}"
}

# ── watchdog ─────────────────────────────────────────────────────────────────
# bh_watchdog SECS CMD...: CMD's exit status, or 124 when it had to be killed.
bh_watchdog() {
  local secs=$1 pid wd rc
  shift
  "$@" &
  pid=$!
  (
    set +e
    trap 'kill "$sp" 2>/dev/null; exit 0' TERM
    sleep "$secs" &
    sp=$!
    wait "$sp"
    if command -v pkill >/dev/null 2>&1; then pkill -TERM -P "$pid" 2>/dev/null; fi
    kill -TERM "$pid" 2>/dev/null || exit 0
    sleep 1
    kill -KILL "$pid" 2>/dev/null
    exit 0
  ) >/dev/null 2>&1 &
  wd=$!
  rc=0
  wait "$pid" || rc=$?
  kill -TERM "$wd" 2>/dev/null || true
  wait "$wd" 2>/dev/null || true
  case $rc in 137 | 143) rc=124 ;; esac
  return "$rc"
}

# ── locks ────────────────────────────────────────────────────────────────────
# One backend per state root, cached in <root>/lock-backend, so every process
# on that root uses the same one: flock, lockf and mkdir locks do not see each
# other. $BELLHOP_LOCK forces one (tests only).
_bh_lock_usable() {
  case ${1:-} in
    flock) type -P flock >/dev/null 2>&1 ;;
    lockf) [ -x /usr/bin/lockf ] ;;
    mkdir) return 0 ;;
    *) return 1 ;;
  esac
}

_bh_lock_probe() {
  local root=$1 probe
  if type -P flock >/dev/null 2>&1; then
    echo flock
    return 0
  fi
  if [ -x /usr/bin/lockf ]; then
    # fd mode: exit 0 = supported; 64 (usage: no fd mode) or anything else =
    # not. A private scratch file, so contention on a real lock can't fail it.
    probe=$root/.lockprobe.$$
    if (exec 7>>"$probe" && /usr/bin/lockf -t 0 7) >/dev/null 2>&1; then
      rm -f "$probe"
      echo lockf
      return 0
    fi
    rm -f "$probe"
  fi
  echo mkdir
}

_bh_lock_pick() {
  local root cache b tmp c
  [ -z "${BH_LOCK_BACKEND:-}" ] || return 0
  case ${BELLHOP_LOCK:-} in
    flock | lockf | mkdir)
      BH_LOCK_BACKEND=$BELLHOP_LOCK
      return 0
      ;;
  esac
  root=$(bh_state_root)
  cache=$root/lock-backend
  b=
  if [ -r "$cache" ]; then IFS= read -r b <"$cache" 2>/dev/null || true; fi
  if _bh_lock_usable "$b"; then
    BH_LOCK_BACKEND=$b
    return 0
  fi
  (umask 077 && mkdir -p "$root") 2>/dev/null || true
  b=$(_bh_lock_probe "$root")
  # First writer wins: ln never replaces an existing file. A cache that is
  # present but unusable (say, copied from another machine) is replaced.
  if [ -d "$root" ] && tmp=$(mktemp "$root/lock-backend.XXXXXX" 2>/dev/null); then
    printf '%s\n' "$b" >"$tmp"
    if ! ln "$tmp" "$cache" 2>/dev/null; then
      c=
      IFS= read -r c <"$cache" 2>/dev/null || true
      _bh_lock_usable "$c" || mv -f "$tmp" "$cache" 2>/dev/null || true
    fi
    rm -f "$tmp"
    c=
    IFS= read -r c <"$cache" 2>/dev/null || true
    if _bh_lock_usable "$c"; then b=$c; fi
  fi
  BH_LOCK_BACKEND=$b
}

bh_lock_backend() {
  _bh_lock_pick
  printf '%s\n' "$BH_LOCK_BACKEND"
}

_bh_fd_ok() { case ${1:-} in '' | *[!0-9]*) return 1 ;; esac; }

# bh_lock_open FD FILE: open FILE for append on FD and remember FILE, so the
# mkdir backend knows which lock FD stands for.
bh_lock_open() {
  _bh_fd_ok "$1" || return 2
  eval "exec $1>>\"\$2\"" || return 1
  eval "_BH_LOCKFILE_$1=\$2"
}

# The file behind FD: given, recorded by bh_lock_open, else asked of the OS.
_bh_lock_file() {
  local fd=$1 f=${2:-} v
  if [ -n "$f" ]; then printf '%s\n' "$f"; return 0; fi
  eval "v=\${_BH_LOCKFILE_$fd:-}"
  if [ -n "$v" ]; then printf '%s\n' "$v"; return 0; fi
  if [ -e "/proc/self/fd/$fd" ]; then
    readlink "/proc/self/fd/$fd" && return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    # (No pipeline here: lsof must be a child of a shell that holds the fd.)
    local pid=${BASHPID:-$$} line
    v=$(lsof -a -p "$pid" -d "$fd" -Fn 2>/dev/null) || true
    while IFS= read -r line; do
      case $line in n?*)
        printf '%s\n' "${line#n}"
        return 0
        ;;
      esac
    done <<<"$v"
  fi
  return 1
}

# Held mkdir locks, one "<dir>|<pid>" per line.
_BH_MKDIR_HELD=
_bh_lock_cleanup() {
  local e d p cur
  while IFS= read -r e; do
    [ -n "$e" ] || continue
    d=${e%|*} p=${e##*|}
    cur=
    IFS= read -r cur <"$d/pid" 2>/dev/null || true
    if [ "$cur" = "$p" ]; then rm -rf "$d"; fi
  done <<<"$_BH_MKDIR_HELD"
  _BH_MKDIR_HELD=
}

# The EXIT trap is set only when none is set, so a caller's trap is never
# replaced. Without it, a holder that exits leaves a dead pid behind and the
# next locker takes the lock over.
_bh_lock_trap() {
  [ -z "$(trap -p EXIT)" ] || return 0
  trap _bh_lock_cleanup EXIT
}

# _bh_mkdir_lock FILE TRIES: mkdir FILE.d, 0.1 s between tries.
_bh_mkdir_lock() {
  local d=$1.d tries=$2 n=0 me=${BASHPID:-$$} pid again
  while :; do
    if mkdir "$d" 2>/dev/null; then
      printf '%s\n' "$me" >"$d/pid"
      _BH_MKDIR_HELD="$_BH_MKDIR_HELD$d|$me"$'\n'
      _bh_lock_trap
      return 0
    fi
    pid=
    IFS= read -r pid <"$d/pid" 2>/dev/null || true
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      # Stale: its holder is gone. Move it aside only if it is still that one.
      again=
      IFS= read -r again <"$d/pid" 2>/dev/null || true
      if [ "$again" = "$pid" ] && mv "$d" "$d.stale.$me" 2>/dev/null; then
        rm -rf "$d.stale.$me"
        continue
      fi
    fi
    [ "$n" -lt "$tries" ] || return 1
    n=$((n + 1))
    sleep 0.1
  done
}

bh_lock() {
  local fd=$1 secs=${2:-10} file
  _bh_fd_ok "$fd" || return 2
  _bh_lock_pick
  case $BH_LOCK_BACKEND in
    flock) flock -w "$secs" "$fd" ;;
    lockf) /usr/bin/lockf -t "$secs" "$fd" ;;
    *)
      file=$(_bh_lock_file "$fd" "${3:-}") || return 2
      _bh_mkdir_lock "$file" $((secs * 10))
      ;;
  esac
}

bh_lock_nb() {
  local fd=$1 file
  _bh_fd_ok "$fd" || return 2
  _bh_lock_pick
  case $BH_LOCK_BACKEND in
    # A lost try is not an error: no "already locked" on stderr.
    flock) flock -n "$fd" 2>/dev/null ;;
    lockf) /usr/bin/lockf -t 0 "$fd" 2>/dev/null ;;
    *)
      file=$(_bh_lock_file "$fd" "${2:-}") || return 2
      _bh_mkdir_lock "$file" 0
      ;;
  esac
}

bh_unlock() {
  local fd=$1 file d e keep=
  _bh_fd_ok "$fd" || return 2
  _bh_lock_pick
  if [ "$BH_LOCK_BACKEND" = mkdir ] && file=$(_bh_lock_file "$fd" "${2:-}"); then
    d=$file.d
    while IFS= read -r e; do
      [ -n "$e" ] || continue
      if [ "${e%|*}" = "$d" ]; then
        [ "$(cat "$d/pid" 2>/dev/null)" != "${e##*|}" ] || rm -rf "$d"
      else
        keep="$keep$e"$'\n'
      fi
    done <<<"$_BH_MKDIR_HELD"
    _BH_MKDIR_HELD=$keep
  fi
  eval "exec $fd>&-"
  eval "_BH_LOCKFILE_$fd="
}

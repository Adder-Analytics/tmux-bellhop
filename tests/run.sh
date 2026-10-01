#!/usr/bin/env bash
# tests/run.sh [test_x.py ...]: run every tests/test_*.py (or the ones named),
# one at a time, each under a 300 s watchdog. Each harness's output goes to the
# terminal and to tests/.artifacts/<name>.log. Prints a summary; the exit status
# is the number of files that failed (a file that times out counts as failed).
set -uo pipefail

HERE=$(CDPATH='' cd -P -- "$(dirname -- "$0")" && pwd -P)
ART=$HERE/.artifacts
PY=${PYTHON:-python3}
export PYTHONDONTWRITEBYTECODE=1
LIMIT=${BELLHOP_TEST_FILE_TIMEOUT:-300}
mkdir -p "$ART"

if [ $# -gt 0 ]; then
  files=("$@")
else
  files=()
  for f in "$HERE"/test_*.py; do [ -e "$f" ] && files+=("$f"); done
fi
[ ${#files[@]} -gt 0 ] || { echo "run.sh: no test files" >&2; exit 1; }

failed=0
summary=
for f in "${files[@]}"; do
  case $f in /*) ;; *) [ -e "$f" ] || f=$HERE/$f ;; esac
  name=$(basename "$f" .py)
  log=$ART/$name.log
  echo "── $name"
  start=$(date +%s)
  # No coreutils timeout on stock macOS: a background watchdog instead.
  (
    "$PY" -u "$f" 2>&1 | tee "$log"
    exit "${PIPESTATUS[0]}"
  ) &
  pid=$!
  (
    sleep "$LIMIT" &
    s=$!
    trap 'kill "$s" 2>/dev/null; exit 0' TERM
    wait "$s"
    echo "run.sh: $name still running after ${LIMIT}s; killed" >>"$log"
    pkill -TERM -P "$pid" 2>/dev/null
    kill -TERM "$pid" 2>/dev/null
    sleep 2
    kill -KILL "$pid" 2>/dev/null
  ) >/dev/null 2>&1 &
  dog=$!
  rc=0
  wait "$pid" || rc=$?
  kill -TERM "$dog" 2>/dev/null
  wait "$dog" 2>/dev/null
  took=$(($(date +%s) - start))
  passes=$(grep -c '^PASS' "$log" 2>/dev/null || true)
  fails=$(grep -c '^FAIL' "$log" 2>/dev/null || true)
  if [ "$rc" -eq 0 ]; then
    line=$(printf 'ok    %-22s %3s passed  %4ss' "$name" "$passes" "$took")
  else
    failed=$((failed + 1))
    line=$(printf 'FAIL  %-22s %3s passed, %s failed, exit %s  %4ss' "$name" "$passes" "$fails" "$rc" "$took")
  fi
  summary=$summary$line$'\n'
done

echo
echo "── summary"
printf '%s' "$summary"
echo "$failed of ${#files[@]} files failed (logs: tests/.artifacts/)"
exit "$failed"

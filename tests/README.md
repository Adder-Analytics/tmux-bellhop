# Tests

The tests are end-to-end: each `test_*.py` starts real tmux servers, attaches real
tmux clients on pseudo-terminals, presses keys, and reads back what tmux did.
They need tmux, fzf, jq, bash and Python 3.9 or later.

```sh
tests/run.sh                        # every test file, one at a time
tests/run.sh test_plugin_load.py    # one file
python3 -u tests/test_compat.py     # one file, without the runner
make lint test                      # what CI runs, minus the privacy job
```

`run.sh` runs the files serially, stops any file after 300 seconds, prints a
summary and exits with the number of files that failed. Each file's output is
also saved in `tests/.artifacts/<name>.log` (CI uploads that folder when a job
fails). A file prints one `PASS` or `FAIL` line per check and a `SKIP` line when
a check can't run on the host (for example the awk dialect comparison with
only one awk installed), then `failures: N`.

## It can't touch your tmux or your HOME

- Every server has its own socket name, `bellhop-test-<name>-<pid>`, in its own
  `TMUX_TMPDIR` (a new short folder under `/tmp`). No test uses the default
  socket of your `TMUX_TMPDIR`.
- Every process a test starts (the server, clients, `bellhop`, the hook) gets a
  temporary `HOME`, `XDG_CONFIG_HOME` and `XDG_STATE_HOME`, and none of your
  `TMUX`, `TMUX_PANE`, `FZF_DEFAULT_OPTS` or `BELLHOP_*` variables.
- Servers load `tests/fixtures/tmux.conf` (tmux defaults, `base-index 1`, and the
  plugin through `run-shell`) or `/dev/null`, never your `~/.tmux.conf`.
- When a test ends, pass or fail (or `run.sh` kills it), every server it started
  is killed and every temporary folder removed.

## How the harness works (`harness.py`)

| name | what it is |
|---|---|
| `Server(name, conf=FIXTURE)` | a throwaway server. `.start(*new_session_args)`, `.t(*tmux_args)`, `.bellhop(*args)`, `.hook(pane, event, **json)`, `.tmux_env()`, `.pane(target)`, `.window(target)`, `.fmt(target, format)`, `.windows()`, `.dump(label)`, `.kill()` |
| `Client(server, session, cols, rows)` | a tmux client on a pty made with `os.openpty()`. `.keys(*keys)`, `.where()`, `.session()`, `.text(since)`, `.wait_prompt(since)`, `.close()` |
| `check(name, got, want)` | one `PASS`/`FAIL` line; `done()` prints the count and exits |
| `wait_for(pred, what, timeout)` | polls every 0.1 s until `pred()` is truthy |
| `procs()` | every process as `{pid: (ppid, args)}` (`ps -ww -eo pid=,ppid=,args=`) |
| `fzf_of(tty, tool)` / `popup_open(tty, tool)` | the fzf a popup on that client is showing: its parent is `libexec/bellhop-<tool> --pick <tty> …` |
| `uuid("a1")` | the only session ids tests use, `00000000-0000-4000-8000-0000000000a1` |

The tests wait on things, never on fixed sleeps: on the popup's fzf process to
appear, on fzf's prompt being drawn before any key is sent (`.wait_prompt`
defaults to `›`; pass the tool's own prompt, such as `find a tab ›`, when two
popups could be on screen; drawn lines are compared with their trailing spaces
stripped), on the popup
process to go away, on a window's bell flag. Scripts that call a bare `tmux` reach
the test server through `TMUX=<socket>,<server pid>,0`, which `Server.tmux_env()`
builds from the real `#{socket_path}` and `#{pid}`.

## Environment

| variable | meaning |
|---|---|
| `BELLHOP_TEST_TIMEOUT_SCALE` | multiplies every timeout (CI uses 2 on macOS) |
| `BELLHOP_TEST_FILE_TIMEOUT` | `run.sh`'s limit per file, in seconds (default 300) |
| `BELLHOP_TMUX`, `BELLHOP_FZF` | the tmux and fzf binaries under test (default: from PATH) |
| `PYTHON` | the Python `run.sh` uses (default `python3`) |

Inside a test, each server's environment also sets `BELLHOP_TMUX`,
`BELLHOP_ROOT` and `BELLHOP_FOCUS_CMD=''` (jump always falls back to
`switch-client`), and tests set `BELLHOP_MAP`, `BELLHOP_STATE_DIR`, `BELLHOP_LOCK`,
`BELLHOP_JQ` or `BELLHOP_NOW` where a case needs them. See
[docs/configuration.md](../docs/configuration.md) → "For scripts and tests".

## Test data

Every session name, tab title and conversation title in these files is
fictional and neutral (`a`, `b`, `c`, `zz`, `scratch-x`, `search-bug`,
`release-notes`, `lobby`, `alpha`, `beta`, `gamma`, …). Keep it that way:
`scripts/scrub-check.sh` runs over this folder too.

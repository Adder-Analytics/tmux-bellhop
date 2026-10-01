# Contributing

Thanks for helping. tmux-bellhop is built and maintained by Adder Analytics; issues and pull requests are welcome. For a bug, please include the output of `bellhop doctor`.

## The dev loop

```
make lint test
```

You need tmux ≥ 3.3, fzf ≥ 0.42, jq, bash, Python ≥ 3.9 and shellcheck.
- `make lint`: shellcheck, `bash -n`, `scripts/lint-portability.sh` and a Python syntax check. `make lint BASH_N=/bin/bash` checks the bash 3.2 floor on macOS.
- `make test`: `tests/run.sh`, every `tests/test_*.py` in turn.
- `make docs-check`: `scripts/check-docs.sh`.
- `make scrub`: `scripts/scrub-check.sh`.

One test file: `tests/run.sh test_find.py`, or `python3 -u tests/test_find.py`.

## The tests can't touch your tmux or your HOME

Every test starts its own tmux servers on unique sockets in a temporary `TMUX_TMPDIR`, gives every process a temporary `HOME` and XDG folders, loads `tests/fixtures/tmux.conf` instead of yours, and kills everything it started when it ends, pass or fail. The tests wait on processes and on drawn text, never on fixed sleeps. [tests/README.md](tests/README.md) explains the harness.

## Rules for the code

- **bash 3.2.** Every script starts with `#!/usr/bin/env bash` and runs on stock macOS `/bin/bash`: no `mapfile`/`readarray`, `declare -A`, `${x,,}`, `local -n`, `[[ -v`, `printf '%(…)T'` or `wait -n`, and guard empty arrays under `set -u` (`${a[@]+"${a[@]}"}`).
- **OS branches only in `lib/bellhop/compat.sh`.** Everywhere else, `scripts/lint-portability.sh` fails on non-portable constructs: `date -r`, `stat -f`, `readlink -f`, `sed -i`, `sed -E`, `grep -P`, `echo -e`, `mktemp -t`, hard-coded install paths and the like. Add a `# portable-ok: <reason>` comment only when there is a real reason.
- **awk:** run every awk under `LC_ALL=C`, never put a multibyte character inside `[...]` (use alternation), use POSIX functions only, and pad non-ASCII text with `pad()` from `lib/bellhop/width.awk.sh`. It has to work on BSD awk, mawk and gawk.
- **sed and sort:** no `\x` escapes in sed (use `$(printf '\033')`), and `sort` under `LC_ALL=C`.
- **shellcheck clean** at `--severity=warning`.
- **No new runtime dependencies** beyond bash, tmux, fzf, awk and jq (jq only for `bellhop hook install` and `uninstall`).
- **The hook stays small.** `bin/bellhop-hook` runs on every prompt: it sources only `compat.sh`, never prints and always exits 0.
- **fzf headers are documented.** Every `--header` in `libexec/bellhop-{inbox,find,move}` must appear word for word in the "Keys" section of its manual page (`docs/<tool>.md`), and each ` · ` part of it (`enter go there`) must be one row of the keys table there, key cell plus header cell (`` | `enter` | go there | ``). Change the header and the manual in the same pull request.

## Checking the docs

`make docs-check` runs `scripts/check-docs.sh`, which CI runs too. It fails, with a list, when:
- an fzf header in the code is missing from its manual's keys table (above);
- an image in `README.md` or `docs/*.md` is not a file in `docs/img`, or has no alt text;
- a relative link or `#anchor` in the docs doesn't resolve;
- a session name or tab or conversation title quoted in the docs (popup rows, the restore plan, status messages such as `Moved <label> → <session>`) is not from `demo/world.tsv` or a placeholder such as `<session>`;
- a tool page loses the shared order: title, one sentence, still, Open it, Keys, What you see, Rules, Without the Claude hook, For scripts, Watch it, See also.

`CHECK_DOCS_VERBOSE=1 make docs-check` lists every quoted name it checked.

## Fictional data only

Every session name, tab title, conversation title, folder and session id in the tests, the demo and the docs is made up: the demo world in `demo/world.tsv` (api, web, docs, infra, mobile, scratch) or the neutral test names (a, b, c, zz, lobby, search-bug, release-notes, alpha, beta…). Session ids are `00000000-0000-4000-8000-0000000000NN`. No real paths, hostnames, user names or email addresses; `scripts/scrub-check.sh` fails on them.

## Demos

Every image in `docs/img` is rendered by [vhs](https://github.com/charmbracelet/vhs) from `demo/tapes/*.tape` against a throwaway demo server (`tmux -L bellhop-demo`, a temporary HOME, `demo/world.tsv`), never captured from a real screen.
- `make demos` renders them locally. Frames show the plugin path, so it renders from `/tmp/tmux-bellhop` (copying the checkout there first) and copies `docs/img` back.
- The images that get committed come from the `demos` workflow (run by hand), downloaded as an artifact.
- Look at every still, and at every GIF frame (`gifsicle --explode`), before committing: no title bar, hostname, user name, clock or real path.
- `make try` starts the same demo server for you to play with; `make try-clean` removes it.

The demo's `demo/tmux.conf` sets `@bellhop-demo-caption on`, which makes each key first flash ` ⌨ prefix <key> ` for 0.9 s, so a recording shows which key was pressed. It exists for the demos only and is not documented anywhere else.

**Run `make scrub` before any pull request that touches `docs/img`**: it checks the images' text and metadata as well as every file.

## Pull requests

- Add a line under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md).
- Use [Conventional Commits](https://www.conventionalcommits.org/): `fix(inbox): …`, `feat(move): …`, `docs: …`, `test: …`.
- The pull request template repeats the checklist: tests, shellcheck, bash 3.2, lint-portability, CHANGELOG, fictional data, `make scrub` if `docs/img` changed.

The public interface (subcommands and flags, option names, the map format, the `panes` and `--rows` columns, the `@bellhop_*` pane options, the layout file format and the `bellhop-hook` marker in settings.json) changes only with a minor version while bellhop is 0.x.

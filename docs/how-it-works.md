# How it works

bellhop keeps no daemon and no database: Claude state lives in tmux pane options, one reader turns a single `list-panes` call into rows, and the popups are fzf inside `display-popup`.

## The picture

```
Claude Code ── hook event (JSON on stdin) ──▶ bin/bellhop-hook
                                                │
                     set-option -p @bellhop_*   │   printf '\a' > the pane's tty
                                                ▼
                          tmux pane options ◀──┴──▶ window_bell_flag (monitor-bell)
                                   │                       │
                                   └──────────┬────────────┘
                                              ▼
                              bellhop panes (one list-panes -a call)
                                              │
                        ┌─────────────────────┼─────────────────────┐
                        ▼                     ▼                     ▼
                   inbox popup           find popup           save → layout
```

Move reads only the session map and tmux's lists of sessions and tabs; restore reads the layout file.

## Pane options

The hook writes these per-pane options (underscores: bellhop writes them; dashes, as in `@bellhop-preview`, are yours to set):

| option | value | written on |
|---|---|---|
| `@bellhop_state` | `idle`, `working`, `finished` or `needs-you` | `SessionStart`, `UserPromptSubmit`, `Stop`, a permission `Notification`; cleared on `SessionEnd` |
| `@bellhop_since` | epoch of the last state change | `SessionStart`, `UserPromptSubmit`, `Stop`, a permission `Notification` |
| `@bellhop_session` | the Claude Code session id | every event that carries one; cleared on `SessionEnd` |
| `@bellhop_note` | the last notification's text, up to 200 characters, on one line | `Notification`; cleared on `SessionStart`, `UserPromptSubmit` and `SessionEnd` |
| `@bellhop_rang` | epoch of the last ring | `Stop`, `Notification` |

They live in the tmux server's memory only.

## How a pane is classified

`bellhop panes` decides each pane's state from three things: the pane's title, which Claude Code sets (`✳` when idle, a spinner while working), the hook's `@bellhop_state`, and the tab's bell flag. The first matching row wins:

| title | `@bellhop_state` | bell flag | state |
|---|---|---|---|
| contains `◐`, `◓`, `◑` or `◒` | anything | anything | working |
| anything else | `needs-you` | anything | needs-you |
| contains `✳` | anything else | set | finished |
| contains `✳` | anything else | not set | idle |
| starts with a braille character (U+2800–28FF) | not needs-you, and the hook knows the session | anything | working |
| anything else | not needs-you, and the hook knows the session | anything | idle |
| anything else | no session known | anything | none (not a Claude; not listed) |

Only needs-you comes from the hook's state alone. The hook's session id only says a pane is a Claude, which reads idle when its title shows neither glyph. Working, finished and idle come from the title and the bell, so a missed hook event can't leave a pane stuck. The Esc case shows why: when you interrupt Claude, no hook event fires and `@bellhop_state` still says `working`, but the title goes back to `✳`, so the pane reads idle, or finished once Claude rings for your input.

Finished means "rang and you haven't looked": tmux sets a tab's bell flag when a pane in it rings, `monitor-bell` is on and the tab is not the one on screen, and clears it when you select the tab. The bell flag belongs to the tab, so when a tab holds two Claudes the inbox counts only the one with the newest `@bellhop_rang` as finished.

The inbox and find draw the states from one palette (`bh_badge` in `lib/bellhop/common.sh`), as SGR colours:

| state | badge | SGR |
|---|---|---|
| needs-you | bold red | `1;31` |
| finished | amber | `38;5;214` |
| working | blue | `34` |
| idle | dim | `2` |

## Why the popups re-run themselves

A key binding runs `run-shell` inside the tmux server, which can't tell which terminal pressed the key and has no terminal for fzf to draw on. So the binding passes the client, session, tab and pane as arguments (`'#{client_name}' '#{session_id}' …`). The script checks fzf, then runs `display-popup -c <client> -E '<itself> --pick <client> <session> <window> [pane]'`. The second run has a terminal, draws fzf and acts on the choice.

The popup runs with the tmux server's environment, not your shell's. So each script finds its own folder from its own path, through any symlink, and never trusts `BELLHOP_ROOT`, which is only a hint.

## `bellhop panes`: 16 columns

`bellhop panes` prints one tab-separated line per pane on the server; the inbox, find and save all read it:

| # | column | from |
|---|---|---|
| 1 | slot | the session's digit on the map, empty off the map |
| 2 | session | `#{session_name}` |
| 3 | session_id | `#{session_id}` |
| 4 | window_id | `#{window_id}` |
| 5 | window_index | `#{window_index}` |
| 6 | window_name | `#{window_name}` |
| 7 | bell | `#{window_bell_flag}` |
| 8 | pane_id | `#{pane_id}` |
| 9 | active | `#{pane_active}` |
| 10 | command | `#{pane_current_command}` |
| 11 | path | `#{pane_current_path}` |
| 12 | title | `#{pane_title}` |
| 13 | state | `needs-you`, `finished`, `working`, `idle` or `none` (the table above) |
| 14 | since | `@bellhop_since` |
| 15 | claude_session | `@bellhop_session` |
| 16 | note | `@bellhop_note` |

tmux prints the fields tab-separated, and turns a tab inside a title, note, name or path into a space itself (the `s/` format modifier) before printing, so the columns can't shift. Tab is the one separator every tmux passes through: from 3.4 the client spells any other control byte in command output out as `\ooo`. `bellhop jump <window-id> [pane-id] [client]` is the other piece of plumbing: it selects the tab and pane, then runs the [focus adapter](configuration.md#focus-adapters) or switches the client. Both are stable within a minor version.

## The layout file (v1)

```
# bellhop layout 1 <epoch> <server-id>
slot  session  index  name  path  claude_session  state  window_id  ended  autorename
```

One tab-separated line per tab after the header. Its fields are explained in [restore](restore.md#the-layout-file-format-v1).

## Saves

- **When:** three tmux hooks at index 77, `after-new-window`, `window-unlinked` and `session-closed`, each running `bellhop save --from-hook`, plus the Claude Code hook on `SessionStart` and `SessionEnd`. The fixed index means reloading the plugin replaces the hooks instead of stacking them.
- **Coalescing:** tabs often open in bursts, and every one fires a save. A hook save marks `layout.pending`, then tries the lock `layout.lock` once. If another save holds the lock, it exits at once, and the holder sees the mark and snapshots again. The holder loops until no mark is left, releases the lock, and looks once more for a mark made in between. The last change of a burst is therefore always saved, with far fewer snapshots than hook calls. A plain `bellhop save` waits up to 10 seconds for the lock.
- **Server id:** each layout's header holds the tmux server's `#{pid}.#{start_time}`, which changes every time a server starts.
- **The `.prev` hand-off:** after a reboot, the first save of the new server finds a layout from another server id. Before writing its own, it moves the old one to `layout.prev`, so opening a tab before `bellhop restore` can't bury the pre-reboot layout.
- **Read once:** restore reads the layout (or `layout.prev`) once at the start, because every tab it opens fires the save hooks, which rewrite the file. After restoring, it saves and retires `layout.prev` to `layout.restored` under the same lock, so a second restore can't reopen what you closed since.
- **Name thaw:** restore gives each tab its old name with `new-window -n`, which turns tmux's automatic-rename off for it. For tabs tmux had named (`autorename` 1), a one-shot `pane-title-changed` hook turns automatic-rename back on the first time a Claude title (`✳` or a spinner) appears, then removes itself. A tab you named by hand keeps its name.
- **Atomic writes:** each snapshot is written to a temporary file beside the layout and renamed over it. A save with no tabs (the last session closing) keeps the previous snapshot.

## Things bellhop never hooks

`window-renamed`, `pane-title-changed` (apart from restore's one-shot thaw), `session-window-changed` and `pane-focus-in`/`pane-focus-out` fire constantly: on every rename, every title update of a working Claude, every tab switch. Hooking them would run a process many times a second for nothing. bellhop reads the state when you open a popup instead, with one `list-panes` call, and saves only when the set of tabs changes.

## Portability

Every difference between macOS and Linux lives in `lib/bellhop/compat.sh`, and CI fails if any other file uses a non-portable construct (`scripts/lint-portability.sh`):
- **tmux:** `BELLHOP_TMUX`, else `tmux` on PATH, else the usual install places, because a hook's or `run-shell`'s PATH can be thin.
- **Locks:** `flock` where it exists, else `lockf` when a probe shows it supports file descriptors, else `mkdir` with a pid file and stale-lock takeover. The pick is cached per state root, because the three kinds of lock don't see each other.
- **Dates:** GNU `date -d @N` or BSD `date -r N`, detected once.
- **Locale:** when the locale isn't UTF-8, the first of `C.UTF-8` and `en_US.UTF-8` that `locale -a` lists, spelled as it prints it.
- **Paths and timeouts:** a `cd -P` and `readlink` loop instead of `realpath`, and a small watchdog instead of coreutils `timeout`, which stock macOS lacks.
- **awk:** every awk runs under `LC_ALL=C` and counts UTF-8 characters by hand, so BSD awk, mawk and gawk draw the same columns.
- **bash:** the scripts run on bash 3.2, the stock macOS `/bin/bash`.

## See also

- [The Claude Code hook](claude-code-hook.md) · [Restore](restore.md) · [Configuration](configuration.md)

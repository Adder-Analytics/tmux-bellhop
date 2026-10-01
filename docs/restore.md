# Restore · bellhop restore

After a reboot, `bellhop restore` brings back every saved session that isn't running, with its tabs in order on their folders, and types `claude --resume <id>` in each tab that had a Claude, without pressing Enter.

![bellhop restore --dry-run on a fictional layout: five sessions with their folders, twelve tabs, and claude --resume markers on the eight Claude Code tabs](img/restore.png)

The same plan as text (`bellhop restore --dry-run`):

```
Layout saved Thu 1 Jan 00:00 (dry run: nothing changes)
  api (slot 1)  ~/src/api
    Fix flaky checkout test         ~/src/api  · claude --resume 00000000-0000-4000-8000-000000000001
    Add rate limiting to /login     ~/src/api  · claude --resume 00000000-0000-4000-8000-000000000002
    server                          ~/src/api
  web (slot 2)  ~/src/web
    Dark mode for the settings page ~/src/web  · claude --resume 00000000-0000-4000-8000-000000000003
    Upgrade to React 19             ~/src/web  · claude --resume 00000000-0000-4000-8000-000000000004
    storybook                       ~/src/web
  docs (slot 3)  ~/src/docs
    Write the v2 migration guide    ~/src/docs  · claude --resume 00000000-0000-4000-8000-000000000005
    preview                         ~/src/docs
  infra (slot 4)  ~/src/infra
    Terraform plan for staging      ~/src/infra  · claude --resume 00000000-0000-4000-8000-000000000006
    Rotate staging TLS certificates ~/src/infra  · claude --resume 00000000-0000-4000-8000-000000000007
    logs                            ~/src/infra
  scratch  ~
    Explain this regex              ~  · claude --resume 00000000-0000-4000-8000-000000000008
Would start 5 sessions, 12 tabs; 8 Claudes to resume.
```

## Run it

- **Typed:** `bellhop restore` in a shell, inside tmux or not. It has no key: you need it once per reboot.
- **Try first:** `bellhop restore --dry-run` prints the plan and changes nothing.
- **Another server:** `bellhop restore -L work` for a server you start with `tmux -L work`.

## Flags

| flag | what it does |
|---|---|
| `--dry-run` | prints the plan and stops: `Would start N sessions, M tabs; K Claudes to resume.` |
| `--yes` | starts without asking; needed when there is no terminal to ask on |
| `-L NAME`, `--socket NAME` | which server's layout to read, and which server to start into (default: the server of `$TMUX`, else the default server); a value with a `/` is a socket path |
| `-h`, `--help` | the flags and exit codes |

## What you see

First the plan, as above: when the layout was saved, then each session to start with its slot and folder (numbered sessions in slot order, then the others by name, as the popups list them), and each tab with its folder and ` · claude --resume <id>` where one will be typed, or ` · Claude without a session id: nothing typed` for a Claude bellhop knows only by its title. Then, on a terminal, the question `Start 5 sessions, 12 tabs? [y/N]`. Anything but `y` or `yes` prints `Nothing started.` and exits 1. With `y`, the sessions start in the background and the last line says what was done:

```
Started 5 sessions, 12 tabs. 8 tabs with claude --resume typed: press Enter to resume.
```

When nothing was typed, the line stops after the tabs: `Started 5 sessions, 12 tabs.`

Other lines you may see:
- `  already running, left alone: web`: those sessions are running, so they are not in the plan.
- `  started meanwhile, left alone: web`: the session appeared between the plan and the start.
- `  no prompt within 3 s, nothing typed in: api:Fix flaky checkout test`: that tab's shell drew nothing in time.
- `claude not found on PATH: nothing typed`: the tabs come back, but no resume line is typed.
- `Nothing to restore.`: every saved session is already running.

Then attach as usual (`tmux attach`), go to a tab and press Enter to resume its Claude.

## What's saved and when

bellhop saves the layout of the whole server (every session, every tab's name and folder, and the Claude Code session id of each tab's Claude) whenever it changes shape:
- tmux's `after-new-window`, `window-unlinked` and `session-closed` hooks, which the plugin sets at index 77;
- the Claude Code hook, when a Claude starts (`SessionStart`) and when it ends (`SessionEnd`).

It never saves on tab switches, renames or title changes: those happen all the time, and restore doesn't need them to the second. A renamed tab is saved with the next save. `bellhop save` saves by hand. When the server has no tabs left (the last session closing, a shutdown), the last good layout is kept rather than an empty one. `set -g @bellhop-autosave off` turns the automatic saves off.

## Plan, confirm, --yes, -L

Restore always prints the plan before it does anything. On a terminal it asks; without a terminal (a script, a launch agent) it exits 2 and starts nothing unless you pass `--yes`. `-L NAME` restores the server you start with `tmux -L NAME`; when that server isn't running, restore starts it.

## Why typed, not run

Which conversations come back is your call: some of them are done, and a dozen Claudes starting at once all compete for the machine while you only look at one. So restore types the command and stops: you press Enter in the tabs you want back, when you get to them. A tab whose line you don't want is just a shell with some text at the prompt; `ctrl-u` clears it.

## Which Claudes are resumed

`claude --resume <id>` is typed only when all of these hold:
- the saved id is a Claude Code session id: 8-4-4-4-12 hexadecimal digits, such as `00000000-0000-4000-8000-000000000001`;
- `claude` is on your PATH (otherwise restore says `claude not found on PATH: nothing typed` once);
- the Claude was still running at the last save, or ended no more than 120 seconds before it (at a shutdown, Claudes often end a moment before tmux does);
- the new tab's shell has drawn its prompt, within 3 seconds.

A Claude that bellhop knows only by its title (no hook, so no id) gets nothing typed; the plan marks its tab ` · Claude without a session id: nothing typed`.

## Rules

What happens when…
- **a saved session is already running:** it is never merged into; it is reported as `already running, left alone`.
- **a tab's folder is gone** (a deleted worktree): the tab opens in its session's folder instead: the slot's folder on today's map, else the first tab's folder, else your home folder.
- **you closed a session on purpose after restoring:** it stays closed. Once a layout has been restored, it is retired, so a second restore can't bring back what you closed since.
- **you open tabs before restoring:** fine. The first save of the new server moves the pre-reboot layout aside to `layout.prev` instead of overwriting it, and restore reads that one. After restoring, it is renamed `layout.restored`.
- **you run restore twice at once:** the second waits (`waiting for another bellhop restore to finish...`) for up to 60 seconds, then gives up with exit 1.
- **a tab was named by tmux:** it comes back with its old name, and naming is handed back to tmux as soon as its Claude sets a title. A tab you named by hand keeps its name for good.
- **a tab name holds `#`:** it comes back as written, never expanded as a tmux format.

## Per-socket files

Each tmux server keeps its own layout, named after its socket: `~/.local/state/bellhop/default/layout` for the default server, `~/.local/state/bellhop/work/layout` for `tmux -L work`. A test or demo server can never overwrite your default server's layout. The folder moves with `XDG_STATE_HOME` or `BELLHOP_STATE_DIR`; see [state paths](configuration.md#state-paths).

## Using tmux-resurrect or tmux-continuum too

Those plugins restore sessions on their own. bellhop never merges into a running session, so a session the other plugin restored first is left alone, and no `claude --resume` line is typed in it. Pick one restorer per server: run `bellhop restore` first, before continuum's automatic restore, or `set -g @bellhop-autosave off` and let the other plugin restore while you keep bellhop's popups.

## The layout file (format v1)

Mode 600, in a folder of mode 700. The first line is a header:

```
# bellhop layout 1 <epoch> <server-id>
```

`<epoch>` is when it was saved and `<server-id>` is the tmux server's `#{pid}.#{start_time}`, which changes on every server start. Then one tab-separated line per tab:

```
slot  session  index  name  path  claude_session  state  window_id  ended  autorename
```

`claude_session` is the tab's Claude Code session id (empty when none), `ended` is when that Claude ended (empty while it runs), and `autorename` is 1 when tmux named the tab and 0 when someone named it by hand. The format is a public interface; restore always reads version 1.

## Safety

- Only an id that passes the check above is ever typed, so a changed or hostile layout file can't put other text on your prompt.
- Text goes in with `tmux send-keys -l`, which types it literally: no tmux key names are interpreted.
- Restore never presses Enter.
- Nothing is sent anywhere: the layout stays on your machine.

## Without the Claude hook

Restore brings back every session and tab on its folder, but types nothing: without the hook it has no session ids.

## For scripts

Exit status: 0 when done or when there is nothing to restore; 1 when nothing is saved, the answer was not yes, or another restore held the lock for 60 seconds; 2 for bad usage, or no terminal and no `--yes`. `bellhop save [--from-hook] [-L NAME]` writes the layout by hand and always exits 0.

## Watch it

![bellhop restore: the plan, the y/N question, the summary line, then the api session attached with claude --resume typed and waiting for Enter](img/restore.gif)

## See also

- [The Claude Code hook](claude-code-hook.md): where the session ids come from
- [How it works](how-it-works.md#saves): locking, the server id, the `.prev` hand-off
- [Configuration](configuration.md): `@bellhop-autosave`, `@bellhop-save-ignore`, state paths

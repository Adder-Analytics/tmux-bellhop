# Configuration

Everything bellhop reads: the session map, the tmux options, environment variables for scripts and tests, where state lives, focus adapters, and terminal shortcuts for the three keys.

## The session map

The map gives sessions the digits that [move](move.md) uses and that the [inbox](inbox.md) and [find](find.md) show in their slot column. It is optional, and nothing creates it at install.

**Where:** `$BELLHOP_MAP`, else `${XDG_CONFIG_HOME:-~/.config}/bellhop/map`. `bellhop map path` prints it.

**Format:** one line per slot, `<digit> <session> [folder]`.

```
# digit  session  folder
1  api    ~/src/api
2  web    ~/src/web
3  docs   ~/src/docs
4  infra  ~/src/infra
```

- The folder is the rest of the line, so folders with spaces work. `~` is your home folder, and the folder defaults to `~`.
- `#` starts a comment line; blank lines are ignored.
- A folder may not exist yet. Move then starts that slot's session in `~` and says `(started in ~)`.

**Validation:** the digit is 0–9, and the first line wins for a digit given twice. A session name is not empty and has no spaces, `.` or `:` (tmux would change them). A bad line is skipped: `bellhop map list`, `bellhop map edit` and `bellhop doctor` say which line and why; the popups skip it silently and never fail over it.

**Commands:**

| command | what it does |
|---|---|
| `bellhop map` or `bellhop map list` | each slot: digit, session, folder, and `running, N tabs` or `not started` |
| `bellhop map init [--force]` | writes a map numbering the running sessions 1–9, then 0; refuses to replace a map without `--force` |
| `bellhop map set <digit> [dir] [session]` | puts a folder on a slot; the folder defaults to the current one, the session to the folder's name with `.`, `:` and spaces as `_` |
| `bellhop map unset <digit>` | takes a slot off the map |
| `bellhop map edit` | opens the map in `$VISUAL`, else `$EDITOR`, else `vi`, starting from a commented template, and reports bad lines when you close it |
| `bellhop map path` | prints the map file's path |

`set` and `unset` keep your comment lines, sort the slot lines by digit, and replace the file in one step.

The map is one file for every tmux server. `list` and `init` read the running sessions of the server you are in, else the default one, and say which; `bellhop map -L work init` reads the server you start with `tmux -L work`.

## Numbering without a map

With no map file, the running sessions are numbered 1–9, then 0, in the order `prefix s` lists them (by name). The numbers shift as sessions start and end, move's header says `bellhop map init to pin these`, and there are no `not started` rows. `bellhop map init` writes today's numbering down.

## tmux options

Set these in tmux.conf before the `@plugin` or `run-shell` line. Tools read them each time they run, with one `show -gqv` each; only the key options and `@bellhop-autosave` / `@bellhop-tab-titles` need a reload (`tmux source-file ~/.tmux.conf`).

| option | default | example | meaning | takes effect |
|---|---|---|---|---|
| `@bellhop-inbox-key` | `i` | `set -g @bellhop-inbox-key I` | the inbox's prefix key; `''` = no binding | on reload |
| `@bellhop-find-key` | `/` | `set -g @bellhop-find-key f` | find's prefix key; `''` = no binding | on reload |
| `@bellhop-move-key` | `m` | `set -g @bellhop-move-key M` | move's prefix key; `''` = no binding | on reload |
| `@bellhop-move-stay-key` | `ctrl-s` | `set -g @bellhop-move-stay-key ctrl-t` | fzf key name for "move and stay behind" | next popup |
| `@bellhop-preview` | `on` | `set -g @bellhop-preview off` | `off` starts every preview hidden (screen-sharing); `ctrl-p` still shows it | next popup |
| `@bellhop-fzf-opts` | `''` | `set -g @bellhop-fzf-opts '--color=dark --no-scrollbar'` | appended to every fzf call (word-split; no quoting inside) | next popup |
| `@bellhop-autosave` | `on` | `set -g @bellhop-autosave off` | the three tmux save hooks and the Claude Code hook's saves | at once (the tmux hooks come off on reload) |
| `@bellhop-save-ignore` | `''` | `set -g @bellhop-save-ignore 'scratch-*'` | tmux glob of session names save skips | next save |
| `@bellhop-focus-cmd` | `''` | `set -g @bellhop-focus-cmd '~/.config/bellhop/focus'` | focus adapter for jump (below) | next jump |
| `@bellhop-tab-titles` | `off` | `set -g @bellhop-tab-titles on` | `on` sets `automatic-rename-format` so a tab with a Claude title is named after it (glyph stripped); other tabs use tmux's default format | on reload |

About the keys:
- An option you set is always bound, even over a binding of your own. A default key is bound only when it is unbound, still runs what stock tmux runs there, or is already bellhop's; otherwise bellhop shows `bellhop: prefix m is bound to something else; set @bellhop-move-key to pick a key` and leaves it alone.
- What a key did before bellhop took it is kept, and `bellhop uninstall` gives it back.
- A plugin folder whose path contains a `'` is not supported.

Options with dashes (`@bellhop-*`) are yours to set. Options with underscores (`@bellhop_state`, `@bellhop_since`, `@bellhop_session`, `@bellhop_note`, `@bellhop_rang`) are pane options that bellhop writes; see [how it works](how-it-works.md#pane-options).

## For scripts and tests

Environment variables, for tests, demos and anyone scripting bellhop:

| env | meaning |
|---|---|
| `BELLHOP_TMUX` | the tmux binary (default: `tmux` on PATH, else the usual install places) |
| `BELLHOP_FZF` | the fzf binary |
| `BELLHOP_MAP` | the map file |
| `BELLHOP_STATE_DIR` | the state root; per-socket folders live below it |
| `BELLHOP_LAYOUT` | the exact layout file, bypassing per-socket naming |
| `BELLHOP_FOCUS_CMD` | overrides `@bellhop-focus-cmd`; `''` forces switch-client |
| `BELLHOP_CLAUDE_SETTINGS` | the settings.json path (else `$CLAUDE_CONFIG_DIR/settings.json`, else `~/.claude/settings.json`) |
| `BELLHOP_NOW` | a pinned epoch for ages ("rang 4m ago") |
| `BELLHOP_LOCK` | `flock`, `lockf` or `mkdir`: forces the lock backend (tests only; every process on one state folder must use the same value) |
| `BELLHOP_JQ` | the jq binary; `/nonexistent` forces the hook's jq-less parser and hookctl's "jq missing" path (tests) |
| `BELLHOP_TEST_TIMEOUT_SCALE` | multiplies every test timeout (harness only) |

`CLAUDE_CONFIG_DIR`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `TMUX`, `TMUX_PANE` and `FZF_PREVIEW_LINES` are honoured too.

The popups run inside the tmux server, so they see the **server's** environment, not your shell's: a `BELLHOP_MAP` exported only in your shell does not reach `prefix m`. Put such variables in the server's environment (`tmux set-environment -g BELLHOP_MAP ~/maps/work`) or export them before the server starts. The command-line tools (`bellhop restore`, `bellhop map`, `bellhop doctor`) read your shell's environment as usual.

## State paths

```
${BELLHOP_STATE_DIR:-${XDG_STATE_HOME:-~/.local/state}/bellhop}/<socket>/layout
```

`<socket>` is the tmux socket's name: `default` for the default server, `work` for `tmux -L work`. Beside the layout, in the same folder:

| file | what it is |
|---|---|
| `layout` | the current layout ([format](restore.md#the-layout-file-format-v1)) |
| `layout.prev` | the previous server's layout, moved aside by the first save of a new server |
| `layout.restored` | a layout that has been restored |
| `layout.lock`, `layout.pending` | the save lock, and the mark a save leaves for the save holding the lock |
| `restore.lock` | one restore at a time |

The lock backend that works on this system (`flock`, `lockf` or `mkdir`) is probed once and cached in `lock-backend` at the state root. Files are mode 600 and folders 700. Before the first save, the only file written is that `lock-backend` cache (`bellhop doctor` writes it too); the `<socket>` folder and the layout come with the first save.

## Focus adapters

By default, going to a tab (Enter in the inbox or find) switches your terminal's tmux client to that session. If you keep one terminal window per session, you may rather have the window that already shows that session come to the front. A focus adapter does that. It is any executable, set with `@bellhop-focus-cmd` (a leading `~/` is expanded).

**The contract:**
- bellhop runs it as `<cmd> <slot-or-empty> <session_name> <window_id>`, only when another terminal is attached to that session and yours isn't on it;
- exit 0 means "a terminal showing that session is now focused", and bellhop stops there;
- any other exit, or taking longer than 2 seconds (it is then killed), and bellhop switches your client as usual;
- its stdout and stderr are discarded; `BELLHOP_TMUX` names the tmux binary.

bellhop has already selected the tab and pane, so the adapter only has to raise the right window.

**`contrib/focus/aerospace`** is an example for the AeroSpace window manager on macOS. It is **unsupported**: not tested in CI, and it may break when AeroSpace changes. It assumes one AeroSpace workspace per map slot, named by the digit, with the terminal window for that slot's session on it; it switches to the workspace and focuses the terminal window there. `BELLHOP_TERMINAL_APP` sets the terminal's bundle id (default `com.mitchellh.ghostty`) and `BELLHOP_AEROSPACE` the aerospace binary. Copy it and adapt it rather than pointing at it in place.

**sway, i3 or Hyprland:** a few lines of shell do the same.
Keep one workspace per slot, numbered by the digit, with that session's terminal on it.
The adapter exits 1 when its first argument (the slot) is empty, so off-map sessions just switch.
On sway, `swaymsg workspace number "$1"` shows the workspace; on i3, `i3-msg` takes the same command.
On Hyprland, `hyprctl dispatch workspace "$1"` does it.
Exit 0 only when that command succeeded, so bellhop falls back to switching your client otherwise.

## Terminal shortcuts

The keys are tmux prefix keys, so any terminal can send them from a single shortcut: the prefix byte, then the key. These give ⌘⇧I, ⌘⇧F and ⌘⇧M for the inbox, find and move with the default prefix `C-b` (`\x02`); on Linux, use a free modifier such as ctrl+shift.

**Ghostty** (`~/.config/ghostty/config`):

```
keybind = super+shift+i=text:\x02i
keybind = super+shift+f=text:\x02/
keybind = super+shift+m=text:\x02m
```

**kitty** (`kitty.conf`):

```
map cmd+shift+i send_text all \x02i
map cmd+shift+f send_text all \x02/
map cmd+shift+m send_text all \x02m
```

**WezTerm** (`wezterm.lua`):

```lua
config.keys = {
  { key = 'i', mods = 'CMD|SHIFT', action = wezterm.action.SendString '\x02i' },
  { key = 'f', mods = 'CMD|SHIFT', action = wezterm.action.SendString '\x02/' },
  { key = 'm', mods = 'CMD|SHIFT', action = wezterm.action.SendString '\x02m' },
}
```

**iTerm2:** Settings → Profiles → Keys → Key Mappings → `+`, record ⌘⇧I, choose "Send Hex Code" and enter `0x02 0x69`. Likewise ⌘⇧F with `0x02 0x2f` and ⌘⇧M with `0x02 0x6d`.

With another prefix, change the first byte:

| prefix | byte | hex |
|---|---|---|
| `C-b` (tmux's default) | `\x02` | `0x02` |
| `C-a` | `\x01` | `0x01` |
| `C-<letter>` | the letter's place in the alphabet | `C-s` is `0x13`, `C-z` is `0x1a` |

If you changed a key with `@bellhop-*-key`, send that key instead of `i`, `/` or `m`.

## See also

- [Inbox](inbox.md) · [Find a tab](find.md) · [Move tabs](move.md) · [Restore](restore.md)
- [The Claude Code hook](claude-code-hook.md) · [Troubleshooting](troubleshooting.md)

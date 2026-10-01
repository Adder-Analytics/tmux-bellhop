# Inbox · prefix i

The inbox lists every Claude Code pane on the tmux server, the one waiting on you first, and Enter takes you to it.

![The inbox popup: eight Claude Code tabs across five sessions, the two asking for permission on top, and a live preview of the first one's permission prompt](img/inbox.png)

`prefix` is tmux's prefix key, `C-b` unless you changed it.

## Open it

- **Key:** `prefix i`.
- **Typed:** `bellhop inbox` in any tmux pane. The popup opens on the terminal attached to that pane's session; with no terminal attached there, it says `bellhop inbox: no client is attached to this session` and exits 1.
- **Another key:** `set -g @bellhop-inbox-key I` before the plugin line, then reload tmux.conf. `set -g @bellhop-inbox-key ''` binds no key.

## Keys

The popup's header reads `enter go there · ctrl-p preview · esc close · prefix L to come back`.

| key | header | what it does |
|---|---|---|
| `enter` | go there | goes to the pane under the cursor, in whatever session it is |
| `ctrl-p` | preview | hides the preview, or shows it again |
| `esc` | close | closes the popup and goes nowhere |
| `prefix L` | to come back | after a jump, back to the session you were in; the header shows this only while `prefix L` still runs tmux's stock `switch-client -l` |
| typing | – | filters the rows (fzf's fuzzy match on the row text) |

## What you see

A popup titled ` Claudes `, 90% of the terminal wide and 70% high, with the prompt `claude › `. One row per Claude Code pane, here as a 120-column popup draws them (the preview then sits under the list):

```
needs you  1  api      Fix flaky checkout test          permission to use Bash
needs you  4  infra    Rotate staging TLS certificates  permission to use Edit
finished   2  web      Dark mode for the settings page  rang 4m ago
finished   3  docs     Write the v2 migration guide     rang 12m ago
working    1  api      Add rate limiting to /login      3m
working    4  infra    Terraform plan for staging       40s
idle       2  web      Upgrade to React 19              1h
idle          scratch  Explain this regex               3h
```

Each row is: the state badge · the session's slot digit (blank for a session off the [map](configuration.md#the-session-map)) · the session · the conversation title without its leading glyph · the detail · `· here` on the pane you opened it from (that row is dimmed).

### The four states

| state | badge | what sets it | what clears it | sorts |
|---|---|---|---|---|
| needs you | bold red | the hook: a `Notification` that is a permission prompt | the next hook event (a prompt, a stop, a new session), or a spinner in the title once Claude carries on | first |
| finished | amber | the title shows `✳` and the tab's bell flag is set (the hook rings on `Stop` and `Notification`) | going to that tab: tmux clears its bell flag | second |
| working | blue | the title shows a spinner (`◐ ◓ ◑ ◒`, or a braille character when the hook knows the session) | the title going back to `✳` | third |
| idle | dim | the title shows `✳` with no bell, or the hook knows the session | a spinner, a bell or a permission prompt | last |

The badge colours are one palette shared with [find](find.md): red `1;31`, amber `38;5;214`, blue `34`, dim `2`. The rules behind the states are in [how it works](how-it-works.md#how-a-pane-is-classified).

### Order of rows

Needs you, then finished, then working, then idle. Needs-you and finished rows are newest first: the Claude that rang last is the one you were just told about. After that, rows go by slot (sessions off the map last), then session, tab and pane.

### The detail column

| state | detail |
|---|---|
| needs you | what it asks, from the hook's notification without the words "Claude needs your": `permission to use Bash` |
| finished | when it rang: `rang 4m ago` |
| working, idle | how long it has been in that state: `40s`, `3m`, `1h`, `2d` |

The detail keeps up to 24 columns; when the popup is narrow the title gives way first, then the session name.

### Preview

The preview shows the pane's screen down to its last non-blank line (usually the pane's own prompt), as many lines as the preview is tall (fzf's `FZF_PREVIEW_LINES`, else 40), with colours but without anything else the pane printed: no title changes, clipboard writes or cursor moves reach your terminal. It sits beside the list when the popup is at least 140 columns wide and under it otherwise. `ctrl-p` hides it; `set -g @bellhop-preview off` starts it hidden.

### Two Claudes in one tab

Each pane is its own row. tmux keeps one bell flag per tab, so when a tab with two Claudes rang, only the one that rang last shows as finished; the other shows as idle.

### The Esc edge case

When you press Esc to interrupt Claude, Claude Code sends no hook event, so the hook's state still says working. The title decides instead: it goes back to `✳`, so the row shows idle, or finished when Claude then rang for input.

## Rules

What happens when…
- **you press Enter:** bellhop selects the tab and the pane, then switches your terminal to that session. With a [focus adapter](configuration.md#focus-adapters), a terminal that already shows that session is raised instead.
- **the tab is in a session off the map:** it is listed with a blank slot, and Enter still switches your terminal there.
- **you press Esc:** nothing moves.
- **there are no Claude Code panes:** no popup opens; the status line says `No Claude Code panes on this server`, followed by ` · hook not installed: bellhop hook install` when the hook is not installed.
- **fzf is missing or older than 0.42:** no popup opens; the status line says, for example, `bellhop: needs fzf ≥ 0.42 (found 0.29) · bellhop doctor`.
- **your `FZF_DEFAULT_OPTS` binds Enter or sets `--exact`:** it is ignored. Every popup runs fzf without it; use `@bellhop-fzf-opts` for fzf options of your own.
- **you type `bellhop inbox` outside tmux:** `bellhop inbox: only works inside tmux`, exit 1.

## Without the Claude hook

The inbox still lists every pane whose title carries a Claude Code glyph: `✳` is idle, a spinner is working, and `✳` with the tab's bell flag is finished. It never shows "needs you", and the detail column stays empty, because both come from the hook. The empty message tells you how to install it. See [the Claude Code hook](claude-code-hook.md).

## For scripts

`bellhop inbox --rows [pane-id]` prints the sorted rows without fzf, one line per pane, 9 tab-separated columns:

```
window_id  pane_id  state  slot  session  window_index  title  detail  here
```

`state` is `needs-you`, `finished`, `working` or `idle`; `here` is 1 for the pane given (default: the calling pane). `bellhop inbox --rows --shown [--cols N] [pane-id]` prints only the text fzf matches, uncoloured, as a popup N columns wide draws it (default 142). Both need `$TMUX` to name the server. The columns are a public interface: they change only with a minor version while bellhop is 0.x.

## Watch it

![The inbox: moving down the list switches the preview to the next permission prompt, ctrl-p hides and shows the preview, typing terraform leaves one row, and Enter goes to that tab](img/inbox.gif)

## See also

- [Find a tab](find.md) · [Move tabs](move.md) · [Restore](restore.md)
- [The Claude Code hook](claude-code-hook.md)
- [How it works](how-it-works.md) · [Troubleshooting](troubleshooting.md)

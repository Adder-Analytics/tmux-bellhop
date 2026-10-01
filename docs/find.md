# Find a tab · prefix /

Find lists every tab in every session, and typing part of a tab name or a Claude Code conversation title takes you there.

![The Find a tab popup narrowed to one row, 1 api Add rate limiting to /login, with that tab's screen, a Claude Code session (mock), in the preview](img/find.png)

`prefix` is tmux's prefix key, `C-b` unless you changed it.

## Open it

- **Key:** `prefix /`.
- **Typed:** `bellhop find` in any tmux pane. The popup opens on the terminal attached to that pane's session; with no terminal attached there, it says `bellhop find: no client is attached to this session` and exits 1.
- **Another key:** `set -g @bellhop-find-key f` before the plugin line, then reload tmux.conf. `set -g @bellhop-find-key ''` binds no key.

## Keys

The popup's header reads `enter go there · ctrl-g grab it into this session · ctrl-p preview`.

| key | header | what it does |
|---|---|---|
| `enter` | go there | goes to the tab under the cursor, in whatever session it is |
| `ctrl-g` | grab it into this session | moves that tab to the end of your session's tab bar and selects it |
| `ctrl-p` | preview | hides the preview, or shows it again |
| `esc` | – | closes the popup and goes nowhere |
| typing | – | filters the rows; fzf's search syntax works |

## What you see

A popup titled ` Find a tab `, 85% of the terminal wide and 75% high, with the prompt `find a tab › ` and a match counter such as `1/12`. One row per tab, its active pane standing for it:

```
 1  api                Fix flaky checkout test  ✳ needs-you
 1  api                Add rate limiting to /login  ✳ working
 1  api                server
 2  web                Dark mode for the settings page  ✳ finished
 2  web                Upgrade to React 19  ✳ idle
 2  web                storybook
 3  docs               Write the v2 migration guide  ✳ finished
 3  docs               preview  · here
 4  infra              Terraform plan for staging  ✳ working
 4  infra              Rotate staging TLS certificates  ✳ needs-you
 4  infra              logs
    scratch            Explain this regex  ✳ idle
```

Each row is: the session's slot digit (blank off the [map](configuration.md#the-session-map)) · the session, cut to 18 columns with `…` when longer · the tab name · ` · <conversation title>` when the tab's Claude has a title that differs from the tab name · the Claude state in the [inbox's colours](inbox.md#the-four-states) · `· here` on your own tab, dimmed. Before you type, numbered sessions come first in slot order, then the others by name, and tabs keep their tab-bar order; once you type, fzf puts the best matches first. The preview shows the tab's screen with colours only, like the inbox's. As in the inbox, it sits beside the list when the popup is at least 140 columns wide and under it otherwise.

### What you can type

Typing matches all of the row text: the slot digit, the session, the tab name, the conversation title and the state word. fzf's search syntax works:

| you type | matches (in the twelve rows above) |
|---|---|
| `migration` | the letters in that order, with anything between (fuzzy): 1 row |
| `'staging` | exactly `staging`: 2 rows |
| `!infra` | rows without `infra`: 9 rows |
| `logs$` | rows that end with `logs`: 1 row |
| `web idle` | rows matching both words: 1 row |

`^` anchors to the start of the row. fzf skips the row's leading space, so `^2` matches the rows of slot 2. Longer words narrow faster: `limiting` leaves one row, while `rate` still matches six.

### Grab vs go

| | Enter (go there) | ctrl-g (grab it into this session) |
|---|---|---|
| the tab | stays in its session | moves to the end of your session |
| you | go to it | stay in your session, on the grabbed tab |

### Grab rules

- The tab is appended after your last tab, never into a gap in the numbering, and selected. The status line says `Grabbed <tab> from <session>`.
- A tab that is already in your session, or linked into it as well, is not moved; it is selected, and the status line says `<tab> is already here`.
- Grabbing the last tab of a session ends that session, so anyone attached to it is first switched to your session; no terminal is detached.

### Tabs named after conversations

tmux names a tab after the command running in it, so Claude Code tabs often read `claude`, `node` or `sh`. Find shows the conversation title after such a name (`claude · Upgrade to React 19`), and typing matches it. With `set -g @bellhop-tab-titles on`, tmux names the tab itself after the conversation (glyph stripped), and find no longer repeats it. tmux renames a tab when its pane next draws, which a running Claude does all the time.

## Rules

What happens when…
- **you press Enter:** bellhop selects the tab, then switches your terminal to its session. With a [focus adapter](configuration.md#focus-adapters), a terminal that already shows that session is raised instead.
- **you press Esc:** nothing moves.
- **the terminal closes, or the connection drops, while the popup is open:** nothing moves, and no error is left in the pane.
- **the tab name holds `#{…}`:** it is shown and moved as written, never expanded.
- **fzf is missing or older than 0.42:** no popup opens; the status line says which fzf bellhop needs.
- **your `FZF_DEFAULT_OPTS` binds `ctrl-g` or sets `--exact`:** it is ignored. Every popup runs fzf without it; use `@bellhop-fzf-opts` for fzf options of your own.
- **you type `bellhop find` outside tmux:** `bellhop find: only works inside tmux`, exit 1.

## Without the Claude hook

Find works fully. Claude titles still show and match, and the state word comes from the title glyph and the tab's bell (working, idle, finished), never `needs-you`.

## For scripts

`bellhop find --rows [session_id window_id]` prints the rows without fzf, uncoloured, one line per tab, 6 tab-separated columns:

```
window_id  pane_id  session_id  session  name  text
```

`text` is the row as shown; `· here` marks the tab given (default: the calling pane's). `bellhop find --rows --shown […]` prints only the `text` column, which is what fzf matches. Both need `$TMUX` to name the server.

## Watch it

![Find: typing limiting narrows twelve tabs to one and Enter goes there; then ctrl-g grabs the Explain this regex tab from the scratch session into api](img/find.gif)

## See also

- [Inbox](inbox.md) · [Move tabs](move.md) · [Restore](restore.md)
- [Configuration](configuration.md): `@bellhop-tab-titles`, `@bellhop-preview`, `@bellhop-fzf-opts`
- [Troubleshooting](troubleshooting.md)

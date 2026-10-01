# Move tabs · prefix m

Move carries the tabs you mark to another session when you press that session's number, and takes you with them.

![The Move tabs popup at step 2 with two tabs marked: the numbered sessions api (here), web, docs, infra and mobile (not started), then scratch under a rule](img/move.png)

`prefix` is tmux's prefix key, `C-b` unless you changed it.

## Open it

- **Key:** `prefix m`. This replaces tmux's `select-pane -m` (mark pane) only when you haven't bound `prefix m` yourself.
- **Typed:** `bellhop move` in any tmux pane; the tabs, session and terminal are that pane's. With no terminal attached to the session, it says `bellhop move: no client is attached to this session` and exits 1.
- **Another key:** `set -g @bellhop-move-key M` before the plugin line, then reload tmux.conf. `set -g @bellhop-move-key ''` binds no key.

## Keys

The popup has two steps, each with its own header.

### Step 1 · which tabs

Skipped when the session has only one tab. The header reads `enter this tab · tab mark several · ctrl-a all`.

| key | header | what it does |
|---|---|---|
| `enter` | this tab | takes the tab under the cursor (it starts on yours), or every marked tab |
| `tab` | mark several | marks the tab under the cursor and moves down |
| `ctrl-a` | all | toggles the mark on every tab: all of them, or none |
| `esc` | – | cancels; nothing moves |

### Step 2 · move … to

The header reads `0-9 move and go with it · enter this one · ctrl-s stay behind`. Without a map file it adds ` · bellhop map init to pin these`, so it reads `0-9 move and go with it · enter this one · ctrl-s stay behind · bellhop map init to pin these`. When the popup is too narrow for that line, the reminder moves to a second line, so the keys are never cut off.

| key | header | what it does |
|---|---|---|
| `0-9` | move and go with it | moves the tabs to that numbered session and switches you there |
| `enter` | this one | the same for the highlighted row (type part of a name to get to it) |
| `ctrl-s` | stay behind | moves the tabs and leaves you where you are; the key is `@bellhop-move-stay-key` |
| `bellhop map init` | to pin these | not a key: a reminder, shown only without a map file, that the numbers can shift |
| `esc` | – | cancels; nothing moves |

## What you see

A popup titled ` Move tabs `, 60% of the terminal wide (wider when that can't fit step 2's header, up to the whole terminal) and 50% high. Step 1 lists the session's tabs in tab-bar order (`index  name`) with the prompt `which tabs › `. Step 2 has the prompt `move <label> to › `, where the label is the tab's name or `2 tabs`, and one row per numbered session, then a rule and the sessions without a number:

```
 1  api               · here
 2  web               3 tabs
 3  docs              2 tabs
 4  infra             3 tabs
 5  mobile            not started
    ──
    scratch           1 tab
```

Your own session (`· here`) and slots that aren't running (`not started`) are dimmed. The status line then says what happened: `Moved Write the v2 migration guide → infra`, `Moved 2 tabs → mobile (started in ~)`.

### Digits with a map

With a [map file](configuration.md#the-session-map), row N is slot N, whether or not its session is running, in slot order. The digits stay put from one day to the next, so they turn into muscle memory.

### Digits without a map

With no map file, the running sessions are numbered 1–9, then 0, in the order `prefix s` lists them (by name). An eleventh session and later ones go under the rule. The numbers shift when a session starts or ends, which is why the header suggests `bellhop map init`: it writes today's numbering into a map so it stops moving.

### Not-started slots

Pressing the digit of a slot that isn't running starts its session in the slot's folder, moves the tabs there and removes the empty tab the new session began with. The status line ends with `(started)`. When the slot's folder is gone, the session starts in your home folder and the status line ends with `(started in ~)`.

### Moving every tab

Moving all of a session's tabs ends that session, so everyone attached to it is switched to the destination first; no terminal is detached. You go along too, even with the stay-behind key.

### Your own digit

Pressing your own session's number moves nothing and says `Already here`.

### The stay-behind key and prefixes

The default stay-behind key is `ctrl-s`, not `ctrl-b`, because `ctrl-b` is tmux's default prefix. Any fzf key name works, and the header names the one you set:

```
set -g @bellhop-move-stay-key ctrl-t
```

The key reaches the popup whatever your prefix is; the tests run with prefix `C-b` and with prefix `C-a`. If `ctrl-s` does nothing on your terminal, see [Troubleshooting](troubleshooting.md#ctrl-s-does-nothing-in-move).

## Rules

What happens when…
- **you move several tabs:** they arrive after the destination's last tab, in their old tab-bar order, and you land on the first of them.
- **you press a digit with no session on it:** nothing moves.
- **the destination is a session without a number:** type part of its name, then Enter.
- **you press Esc at either step:** nothing moves.
- **the terminal closes, or the connection drops, while the popup is open:** nothing moves, and no error is left in the pane.
- **a slot's session can't be started:** the status line says `bellhop move: couldn't start <session>` and nothing moves.
- **fzf is missing or older than 0.42:** no popup opens; the status line says which fzf bellhop needs.
- **you type `bellhop move` outside tmux:** `bellhop move: only works inside tmux`, exit 1.

## Without the Claude hook

Move doesn't use Claude state at all; it works the same with or without the hook, and without Claude Code.

## For scripts

The key runs `bellhop move <client> <session_id> <window_id>`; typed with no arguments, the three come from the current pane. The numbers come from `bellhop map list`, which prints each slot's digit, session, folder and whether it is running.

## Watch it

![Move: two tabs marked in api, then 5 starts the mobile session, the two tabs move there and you go with them](img/move.gif)

## See also

- [Configuration](configuration.md): the session map, `@bellhop-move-stay-key`
- [Inbox](inbox.md) · [Find a tab](find.md) · [Restore](restore.md)

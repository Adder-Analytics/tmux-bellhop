# The Claude Code hook

An optional Claude Code hook tells bellhop what each Claude is doing and rings its tab's bell when Claude finishes or needs your permission; one command adds it and one command takes it out again.

## What it does

`bin/bellhop-hook` runs on five Claude Code events. It writes the Claude's state into its own tmux pane's options, where [the inbox](inbox.md) reads it, and rings the pane's bell so tmux flags the tab.

| event | pane options it writes | bell | save |
|---|---|---|---|
| `SessionStart` | `@bellhop_state` = idle, `@bellhop_since` = now, clears `@bellhop_note` | – | yes |
| `UserPromptSubmit` | `@bellhop_state` = working, `@bellhop_since` = now, clears `@bellhop_note` | – | – |
| `Notification` | `@bellhop_note` = the message (up to 200 characters), `@bellhop_rang` = now; for a permission prompt also `@bellhop_state` = needs-you and `@bellhop_since` = now | yes | – |
| `Stop` | `@bellhop_state` = finished, `@bellhop_since` = now, `@bellhop_rang` = now | yes | – |
| `SessionEnd` | clears `@bellhop_state`, `@bellhop_since`, `@bellhop_session` and `@bellhop_note` | – | yes |

Every event also sets `@bellhop_session` to the Claude Code session id, which [restore](restore.md) uses for `claude --resume <id>`. A notification that only says Claude is waiting for your input rings the bell but leaves the state as it was. "save" means the layout is saved in the background for restore, unless `@bellhop-autosave` is off. `PreToolUse`, `PostToolUse` and `SubagentStop` are left alone on purpose: they fire on every tool call, and a bell per subagent is noise.

## Install, status, uninstall

```
bellhop hook install      # shows the change, asks y/N, then writes it
bellhop hook status       # each event: installed, missing or stale
bellhop hook uninstall    # takes every bellhop entry out again
```

`install` takes `--yes` (don't ask; without a terminal to ask on and without `--yes`, it writes nothing and exits 2), `--dry-run` (show the change, write nothing) and `--settings PATH`; `uninstall` takes `--dry-run` and `--settings PATH`. `install` and `uninstall` need jq; `status` works without it.

Before and after, on a fictional `~/.claude/settings.json` that already allowed one command (two of the five events shown; the other three get the same group):

```json
{
  "permissions": {
    "allow": [
      "Bash(npm test:*)"
    ]
  }
}
```

```json
{
  "permissions": {
    "allow": [
      "Bash(npm test:*)"
    ]
  },
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "test -x '/path/to/tmux-bellhop/bin/bellhop-hook' && '/path/to/tmux-bellhop/bin/bellhop-hook' || true",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "test -x '/path/to/tmux-bellhop/bin/bellhop-hook' && '/path/to/tmux-bellhop/bin/bellhop-hook' || true",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

The path is the plugin's real, absolute path, in single quotes. The question is `Add bellhop's hook to 5 events? [y/N]`, and the answer line is:

```
Added 5 hooks (backup: settings.json.bellhop-backup-20260101T000000Z). New Claude Code sessions pick this up; restart open ones.
```

What install does to the file:
- For each event, it adds one matcher group with the command above, unless an entry of bellhop's is there already. The marker is the text `bellhop-hook` in the command.
- When the plugin folder moved, it points the existing entries at the new path in place.
- Your other hooks, keys and their order are untouched; the file is written back with 2-space indentation.
- A second `install` says `Already installed (~/.claude/settings.json).` and writes nothing.

`uninstall` removes every hook whose command contains `bellhop-hook`, then any matcher group, event or `hooks` key that removal left empty. One limit: a file that had an empty `"hooks": {}` or `"Stop": []` before install loses that empty entry on uninstall; the backup still has the original bytes.

`status` prints one line per event, for example:

```
Claude Code hook in ~/.claude/settings.json:
  SessionStart      installed
  UserPromptSubmit  installed
  Notification      installed
  Stop              installed
  SessionEnd        installed
```

It reports `missing`, `stale: <path> is not executable` (the plugin moved or was deleted: run `install` again), and an event that holds bellhop's entry twice (`installed, 2 entries (duplicate: it runs 2 times)`). `status --quiet` prints nothing and exits 0 only when all five events are installed with an executable path. Without jq, `status` counts the guarded entries in the file instead and says `(checked without jq: approximate)`.

## Which settings file, and backups

The file is `$BELLHOP_CLAUDE_SETTINGS`, else `$CLAUDE_CONFIG_DIR/settings.json`, else `~/.claude/settings.json`. `--settings PATH` picks another. Project `.claude/settings.json` files are never touched.

Every write:
- keeps a backup beside the file, `settings.json.bellhop-backup-<UTC time>`; the newest 3 are kept;
- writes a temporary file in the same folder, with the original's mode, and renames it over the original;
- first checks that the file still holds the bytes it read, because Claude Code rewrites this file too. If it changed, bellhop reads it again, shows the new change (asking again if it differs) and tries once more; if it keeps changing, it stops with `settings.json kept changing; nothing written`.

A file that isn't a single JSON object (or whose `hooks` isn't an object of lists) is refused with jq's error and the file name, and nothing is written.

## A symlinked settings.json

If `settings.json` is a symlink (into a config repository, say), bellhop writes through to the file it points at, so the link stays a link. The backups go beside the path you know, next to the link, so none land in the repository.

## Managed settings that turn hooks off

With `"disableAllHooks": true` or `"allowManagedHooksOnly": true` in the settings file, Claude Code runs none of the hooks listed there. `bellhop hook status` then says `disableAllHooks is true in ~/.claude/settings.json: installed hooks are there, but Claude Code won't run them`, and `bellhop doctor` warns about it too. The entries stay, harmless, until the setting changes.

## It can't hang or block Claude

- Each entry has `"timeout": 5`, so Claude Code stops the hook after 5 seconds at most. It normally takes one jq call, one tmux call and one `printf`.
- It always exits 0. A non-zero exit on some events would block your prompt or keep Claude running.
- It never prints. What a hook prints on `SessionStart` and `UserPromptSubmit` goes into Claude's context.
- The layout save runs detached, in the background.
- Outside tmux, or with no tmux binary, it does nothing.
- If the plugin folder is deleted, the guard `test -x … || true` turns every entry into a no-op; Claude Code shows no hook error.

## With and without the hook

| | with the hook | without it |
|---|---|---|
| inbox: working, idle | yes | yes, from the title glyph |
| inbox: finished | yes: the hook rings the bell | only when something else rings the tab's bell |
| inbox: needs you | yes | never |
| inbox: detail column | what it asks, `rang 4m ago`, how long | empty |
| restore | types `claude --resume <id>` | tabs and folders come back; nothing typed |
| find, move, save | the same | the same |

## Privacy

Nothing leaves your machine: the hook makes no network calls. The notification text lives only in tmux's memory, as a pane option, and is gone when the tmux server ends. Session ids, folders and tab names are saved in the layout file for restore, which is mode 600 in a folder of mode 700 ([state paths](configuration.md#state-paths)).

## See also

- [Inbox](inbox.md) · [Restore](restore.md)
- [How it works](how-it-works.md): how pane options, the title and the bell decide a state
- [Troubleshooting](troubleshooting.md)

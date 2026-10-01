# Changelog

All notable changes to tmux-bellhop are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html): while it is 0.x, a breaking change to the public interface bumps the minor version.

## [Unreleased]

## [0.9.0] - 2026-09-30

The first public release.

### Added

- **Inbox** (`prefix i`, `bellhop inbox`): every Claude Code pane on the tmux server, ordered needs you, finished (newest ring first), working, idle, with a live, sanitised preview. Enter goes to the pane; `--rows` prints the rows for scripts.
- **Find** (`prefix /`, `bellhop find`): any tab in any session by tab name or Claude Code conversation title. Enter goes there; `ctrl-g` grabs the tab into the current session.
- **Move** (`prefix m`, `bellhop move`): mark tabs, press a session's number, and they move there with you; a numbered session that isn't running is started in its folder. `@bellhop-move-stay-key` (default `ctrl-s`) moves without following.
- **Restore** (`bellhop restore`): after a reboot, brings back every saved session and tab on its folder, with `claude --resume <id>` typed but never run. Plan first, then a y/N question; `--dry-run`, `--yes`, and `-L` for other tmux servers.
- **Save** (`bellhop save`): automatic layout snapshots from three tmux hooks and the Claude Code hook, coalesced under a lock, one layout per tmux socket.
- **The Claude Code hook** (`bellhop hook install | uninstall | status`): five events, a diff and a question before every write, timestamped backups, and a guard so a deleted plugin never shows a hook error. The hook itself and `hook status` work without jq; `hook install` and `hook uninstall` need it.
- **The session map** (`bellhop map`): optional numbered sessions; without a map, running sessions are numbered 1–9, then 0.
- `bellhop doctor`, `bellhop link` / `unlink`, and `bellhop uninstall [--purge]`, which gives the keys back what they did before.
- Never-clobber key binding: keys you bound yourself are left alone and reported.
- tmux options `@bellhop-*-key`, `@bellhop-preview`, `@bellhop-fzf-opts`, `@bellhop-autosave`, `@bellhop-save-ignore`, `@bellhop-focus-cmd` and `@bellhop-tab-titles`.
- An unsupported example focus adapter in `contrib/focus/`, and snippets for Ghostty, kitty, WezTerm and iTerm2 shortcuts in the docs.
- End-to-end tests that drive real tmux servers through a pty, on macOS and Linux, with bash 3.2 and BSD awk, mawk and gawk.

Origins: a private tmux setup, generalised.

[Unreleased]: https://github.com/Adder-Analytics/tmux-bellhop/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/Adder-Analytics/tmux-bellhop/releases/tag/v0.9.0

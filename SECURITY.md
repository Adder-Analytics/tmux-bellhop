# Security

Please report a vulnerability privately, through GitHub's private vulnerability reporting: the repository's **Security** tab → **Report a vulnerability**. Please don't open a public issue for it.

The part of bellhop that types into your shells is `bellhop restore`. It types `claude --resume <id>` only for an id that is a well-formed Claude Code session id, types it literally (`tmux send-keys -l`), never presses Enter, and asks before it starts anything.

The Claude Code hook makes no network calls, never prints, and keeps what it learns in tmux pane options and in the layout file (mode 600, in a folder of mode 700).

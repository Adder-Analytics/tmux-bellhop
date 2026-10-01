Output "docs/img/restore.gif"
Source "demo/tapes/_common.tape"

# Hidden: build the world, save its layout and stop the server, as after a
# reboot. A plain shell remains, in ~.
Hide
Type@5ms `demo/setup.sh --restore-scene && . "${TMPDIR:-/tmp}/bellhop-demo.env" && cd ~ && clear`
Enter
Wait+Screen@20s /~ \$/
Sleep 500ms
Show

# docs/restore.md: the plan first, then start it, then look.
Type "bellhop restore -L bellhop-demo --dry-run"
Enter
Sleep 2s
Screenshot "docs/img/restore.png"
Sleep 400ms
Type "bellhop restore -L bellhop-demo"
Enter
Sleep 1.2s
Type "y"
Enter
Sleep 1.2s
Type "tmux -L bellhop-demo attach -t =api"
Enter
Sleep 1.5s

# Hidden: leave and remove the demo server.
Hide
Ctrl+B
Type "d"
Sleep 500ms
Type@5ms `"$REPO/demo/teardown.sh"`
Enter
Sleep 1s

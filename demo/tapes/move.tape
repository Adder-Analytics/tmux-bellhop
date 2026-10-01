Output "docs/img/move.gif"
Source "demo/tapes/_common.tape"

# Hidden: build the demo world and attach at api:1; ring.sh rings once the
# client is there.
Hide
Type@5ms `demo/setup.sh && . "${TMPDIR:-/tmp}/bellhop-demo.env" && tmux -L bellhop-demo attach -t '=api:1'`
Enter
Wait+Screen@20s /1:Fix flaky/
Sleep 1500ms
Show

# docs/move.md: mark two tabs, press a slot digit, go with them.
Ctrl+B
Type "m"
Sleep 1s
Tab
Tab
Sleep 500ms
Enter
Sleep 1.2s
Screenshot "docs/img/move.png"
Sleep 500ms
# mobile is on the map but not running, and its folder is gone.
Type "5"
Sleep 1.5s

# Hidden: leave and remove the demo server.
Hide
Ctrl+B
Type "d"
Sleep 500ms
Type@5ms `"$REPO/demo/teardown.sh"`
Enter
Sleep 1s

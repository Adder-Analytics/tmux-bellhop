Output "docs/img/inbox.gif"
Source "demo/tapes/_common.tape"

# Hidden: build the demo world and attach at api:3; ring.sh rings once the
# client is there.
Hide
Type@5ms `demo/setup.sh && . "${TMPDIR:-/tmp}/bellhop-demo.env" && tmux -L bellhop-demo attach -t '=api:3'`
Enter
Wait+Screen@20s /3:server/
Sleep 1500ms
Show

# docs/inbox.md and the README still.
Ctrl+B
Type "i"
Sleep 1.5s
Screenshot "docs/img/inbox.png"
Sleep 500ms
# The preview follows the cursor: the Edit permission box.
Down
Sleep 1s
# ctrl-p hides the preview and brings it back.
Ctrl+P
Sleep 800ms
Ctrl+P
Sleep 800ms
# Typing filters: one row.
Type "terraform"
Sleep 1s
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

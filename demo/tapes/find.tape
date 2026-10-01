Output "docs/img/find.gif"
Source "demo/tapes/_common.tape"

# Hidden: build the demo world and attach at docs:2; ring.sh rings once the
# client is there.
Hide
Type@5ms `demo/setup.sh && . "${TMPDIR:-/tmp}/bellhop-demo.env" && tmux -L bellhop-demo attach -t '=docs:2'`
Enter
Wait+Screen@20s /2:preview/
Sleep 1500ms
Show

# docs/find.md: every tab in every session, by tab name or Claude title.
Ctrl+B
Type "/"
Sleep 1s
Type "limiting"
Sleep 1.2s
Screenshot "docs/img/find.png"
Sleep 500ms
Enter
Sleep 1s
# ctrl-g grabs a tab into this session: the regex tab leaves scratch.
Ctrl+B
Type "/"
Sleep 600ms
Type "regex"
Sleep 800ms
Ctrl+G
Sleep 1.5s

# Hidden: leave and remove the demo server.
Hide
Ctrl+B
Type "d"
Sleep 500ms
Type@5ms `"$REPO/demo/teardown.sh"`
Enter
Sleep 1s

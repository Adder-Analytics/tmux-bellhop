Output "demo/out/doctor.gif"
Source "demo/tapes/_common.tape"

# Hidden: build the demo world, attach at api:3 (a shell under the server log)
# and clear it.
Hide
Type@5ms `demo/setup.sh && . "${TMPDIR:-/tmp}/bellhop-demo.env" && tmux -L bellhop-demo attach -t '=api:3'`
Enter
Wait+Screen@20s /3:server/
Sleep 1s
Type "clear"
Enter
Sleep 500ms
Show

# docs/troubleshooting.md: every line ok but the optional hook.
Type "bellhop doctor"
Enter
Sleep 2s
Screenshot "docs/img/doctor.png"
Sleep 500ms

# Hidden: leave and remove the demo server.
Hide
Ctrl+B
Type "d"
Sleep 500ms
Type@5ms `"$REPO/demo/teardown.sh"`
Enter
Sleep 1s

Output "docs/img/hero.gif"
Source "demo/tapes/_common.tape"

# Hidden: build the demo world and attach at api:3; ring.sh rings once the
# client is there.
Hide
Type@5ms `demo/setup.sh && . "${TMPDIR:-/tmp}/bellhop-demo.env" && tmux -L bellhop-demo attach -t '=api:3'`
Enter
Wait+Screen@20s /3:server/
Sleep 1500ms
Show

# README "See it": inbox → go there; find → go there; move → go with it.
# 1. The inbox: every Claude, the two waiting on you first.
Ctrl+B
Type "i"
Sleep 2s
# 2. Enter: the first row, api:1, its permission prompt on screen.
Enter
Sleep 1.5s
# 3. Find the migration guide (one row; "migr" would also match two others).
Ctrl+B
Type "/"
Sleep 600ms
Type "migration"
Sleep 1s
Enter
Sleep 1s
# 4. Move this tab to slot 4 (infra) and follow it.
Ctrl+B
Type "m"
Sleep 800ms
Enter
Sleep 1s
Type "4"
Sleep 1.5s

# Hidden: leave and remove the demo server.
Hide
Ctrl+B
Type "d"
Sleep 500ms
Type@5ms `"$REPO/demo/teardown.sh"`
Enter
Sleep 1s

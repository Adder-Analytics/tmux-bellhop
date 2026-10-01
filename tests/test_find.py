"""bellhop find (prefix /) end to end on a throwaway tmux server.

Keys go to the popup's fzf through a real client on a pty. The driver waits on
processes (the popup's fzf appearing, the popup closing) and on what fzf drew,
never on fixed sleeps.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import (BELLHOP, CTRL, ENTER, ESC, REPO, Client, Server, check, done, fzf_of,  # noqa: E402
                     popup_open, procs, run, wait_for)

PREFIX, CTRL_G = CTRL["b"], CTRL["g"]
FIND = os.path.join(REPO, "libexec", "bellhop-find")

s = Server("find")
# A map: slots 0-3 are a, b, c, d; d never runs, zz is off the map.
MAP = os.path.join(s.home, "map")
with open(MAP, "w") as f:
    f.write("# test map\n0  a  ~\n1  b  ~\n2  c  ~\n3  d  ~\n")
s.env["BELLHOP_MAP"] = MAP

# The server: a has a gap (1, 2, 5), b's tabs are Claude conversations, c is one
# tab split in two, zz is off the map.
s.start("-s", "a", "-n", "one")
s.t("new-window", "-d", "-t", "a:", "-n", "two")
s.t("new-window", "-d", "-t", "a:5", "-n", "five")
s.t("new-session", "-d", "-s", "b", "-n", "auth-refactor")
s.t("new-window", "-d", "-t", "b:", "-n", "search-bug")
s.t("new-session", "-d", "-s", "c", "-n", "sea")
s.t("split-window", "-d", "-t", "c:1")
s.t("new-session", "-d", "-s", "zz", "-n", "zed")
s.t("new-window", "-d", "-t", "zz:", "-n", "release-notes")
s.t("select-pane", "-t", "b:1", "-T", "✳ auth refactor")
s.t("select-pane", "-t", "b:2", "-T", "✳ search-bug")
s.t("set", "-p", "-t", "b:2", "@bellhop_state", "needs-you")
s.t("send-keys", "-t", "zz:2", "echo PREVIEW-MARK", "Enter")
wait_for(lambda: "PREVIEW-MARK\n" in s.t("capture-pane", "-p", "-t", "zz:2") + "\n", "echo in zz:2")
WS = s.tmux_env()


def current(session):
    return s.fmt(f"{session}:", "#{window_name}")


def said(tty, text):
    """Whether bellhop showed this status message on the client (the log also holds
    every command run, whose text could match by accident, so skip those lines)."""
    return any(text in line for line in s.t("show-messages", "-t", tty).splitlines() if " command: " not in line)


def rows(*args, env=None):
    out, err, rc = run([FIND, "--rows", *args], env=env or WS)
    return [line.split("\t") for line in out.splitlines()], rc


def find(c, query="", key=ENTER, typed_in=None, wait=()):
    """Open find (prefix /, or typed into a pane), type a query, wait until fzf has
    drawn each regex in wait, press key, wait for the popup to close. Returns
    {regex: drawn?} and leaves the buffer offset of the popup in c.last."""
    mark = len(c.buf)
    if typed_in:
        s.t("send-keys", "-t", typed_in, f"{BELLHOP} find", "Enter")
    else:
        c.keys(PREFIX, "/")
    wait_for(lambda: fzf_of(c.tty, "find"), "the popup's fzf")
    c.wait_prompt(mark, "find a tab ›")
    since = len(c.buf)
    if query:
        c.keys(query)
    seen = {}
    for want in wait:
        seen[want] = bool(wait_for(lambda: re.search(want, "\n".join(c.text(since))),
                                   f"fzf to draw {want!r}", timeout=15))
    c.last = mark
    c.keys(key)
    wait_for(lambda: not popup_open(c.tty, "find"), "the popup to close")
    return seen


try:
    # ── 1. rows: every window once, slot order then off the map, here marked, badges
    sid_a, wid_a1 = s.fmt("a:", "#{session_id}"), s.window("a:1")
    r, rc = rows(sid_a, wid_a1)
    check("rows: exits 0, 6 fields each", (rc, {len(x) for x in r}), (0, {6}))
    check("rows: every window once (c's split is one row), slots then off the map",
          [(x[3], x[4]) for x in r],
          [("a", "one"), ("a", "two"), ("a", "five"), ("b", "auth-refactor"), ("b", "search-bug"),
           ("c", "sea"), ("zz", "zed"), ("zz", "release-notes")])
    shown = {x[4]: x[5] for x in r}
    check("rows: slot column, blank off the map", (shown["one"][:4], shown["sea"][:4], shown["zed"][:4]),
          (" 0  ", " 2  ", "    "))
    check("rows: only the calling tab is marked here", [n for n, t in shown.items() if "· here" in t], ["one"])
    check("rows: Claude badges, none on plain shells",
          (shown["auth-refactor"].endswith("✳ idle"), shown["search-bug"].endswith("✳ needs-you"),
           [n for n, t in shown.items() if "✳" in t]),
          (True, True, ["auth-refactor", "search-bug"]))
    check("rows: a Claude title that differs from the tab name follows it, glyph stripped",
          shown["auth-refactor"], f" 1  {'b':<18} auth-refactor · auth refactor  ✳ idle")
    check("rows: a title equal to the tab name is not repeated",
          shown["search-bug"], f" 1  {'b':<18} search-bug  ✳ needs-you")
    check("rows: no escape bytes", any("\x1b" in x[5] for x in r), False)
    check("rows: pane id is the active pane", r[5][1], s.pane("c:1"))

    out, _, rc = run([FIND, "--rows", "--shown", sid_a, wid_a1], env=WS)
    check("rows --shown: just the text fzf matches", (rc, out.splitlines()), (0, [x[5] for x in r]))
    out, _, rc = run([FIND, "--rows", "--shown"], env=s.tmux_env(TMUX_PANE=s.pane("a:1")))
    check("rows --shown with no ids: the calling pane's tab is here",
          (rc, [line for line in out.splitlines() if "· here" in line]), (0, [shown["one"]]))

    # A long session name is cut to the column, not spilled into the tab name.
    s.t("new-session", "-d", "-s", "a-very-long-session-name-here", "-n", "lengthy")
    r2, _ = rows(sid_a, wid_a1)
    long_row = next(x[5] for x in r2 if x[4] == "lengthy")
    check("rows: a long session name is cut to 18 columns with …",
          long_row, "    a-very-long-sessi… lengthy")
    s.t("kill-session", "-t", "a-very-long-session-name-here")

    # ── 1b. preview: sanitised, trims the blank screen below the prompt
    zz2 = s.pane("zz:2")
    out, _, rc = run([FIND, "--preview", zz2], env=dict(WS, FZF_PREVIEW_LINES="3"))
    pv = out.splitlines()
    check("preview: last 3 lines end at the prompt and include the output",
          (len(pv), bool(pv) and pv[-1].strip() != "", "PREVIEW-MARK" in pv), (3, True, True))
    check("preview: nothing but SGR escapes", re.sub(r"\x1b\[[0-9;:]*m", "", out).count("\x1b"), 0)

    # ── 1c. a window linked into two sessions is "here" only in the calling one
    s.t("link-window", "-d", "-s", "a:1", "-t", "zz:")
    r, _ = rows(sid_a, wid_a1)
    check("rows: a linked tab is marked here in its own session only",
          [(x[3], x[4]) for x in r if "· here" in x[5]], [("a", "one")])
    s.t("unlink-window", "-t", "zz:3")

    # ── 1d. the command line
    out, err, rc = run([BELLHOP, "find", "--help"], env=WS)
    check("--help: keys and flags on stdout, exit 0",
          (rc, all(k in out for k in ("enter", "ctrl-g", "ctrl-p", "esc", "--rows", "--shown"))), (0, True))
    _, err, rc = run([BELLHOP, "find", "--bogus"], env=WS)
    check("unknown flag: usage on stderr, exit 2", (rc, "usage: bellhop find" in err), (2, True))
    env = {k: v for k, v in WS.items() if k not in ("TMUX", "TMUX_PANE")}
    _, err, rc = run([BELLHOP, "find"], env=env)
    check("outside tmux: exit 1, says so", (rc, err.strip()), (1, "bellhop find: only works inside tmux"))

    # ── 2. typed in a shell: a fuzzy fragment filters to one tab, the preview shows
    #       it, Enter brings the hidden off-map session here
    c1 = Client(s, "a", 160, 40)
    seen = find(c1, "rlsnts", ENTER, typed_in="a:1", wait=(r"\b1/8\b", "PREVIEW-MARK"))
    check("filter: fragment narrows 8 tabs to 1, preview shows its pane", seen,
          {r"\b1/8\b": True, "PREVIEW-MARK": True})
    check("enter: jumped to zz, on release-notes", (c1.session(), current("zz")), ("zz", "release-notes"))

    # ── 3. by key: Enter jumps to another session's non-current tab (switch-client)
    find(c1, "search", ENTER, wait=(r"\b1/8\b",))
    check("enter by key: client in b, on search-bug", (c1.session(), current("b")), ("b", "search-bug"))

    # ── 4. esc does nothing
    snap = s.windows()
    find(c1, "", ESC)
    check("esc: nothing moved, still in b", (s.windows(), c1.session()), (snap, "b"))

    # ── 4b. the calling tab is dimmed in the popup and marked here; the header
    seen = find(c1, "search", ESC, wait=(r"\b1/8\b", "· here", "ctrl-g grab it into this session"))
    raw = c1.buf[c1.last:].decode("utf-8", "replace")
    check("popup: the here row is dimmed", bool(re.search(r"\x1b\[2m[^\n]*?sear[^\n]*?· here", raw)), True)
    check("popup: the header names the keys", seen["ctrl-g grab it into this session"], True)

    # ── 5. ctrl-g grabs a tab from another session to the END of this one (a has
    #       a gap at 3-4)
    s.t("switch-client", "-c", c1.tty, "-t", "a")
    wait_for(lambda: c1.session() == "a", "client back in a")
    find(c1, "release", CTRL_G, wait=(r"\b1/8\b",))
    w = s.windows()
    check("grab: appended after a's last tab, zz keeps the rest",
          (w["a"], w["zz"]), (["one", "two", "five", "release-notes"], ["zed"]))
    check("grab: at index 6 (after 5, not the gap), selected, client stayed",
          (s.fmt("a:release-notes", "#{window_index}"), current("a"), c1.session()),
          ("6", "release-notes", "a"))

    # ── 5b. ctrl-g on a tab already in this session only goes there
    snap = s.windows()
    find(c1, "'two", CTRL_G, wait=(r"\b1/8\b",))
    check("grab own tab: nothing moved, went to two, said so",
          (s.windows(), current("a"), c1.session(), said(c1.tty, "two is already here")),
          (snap, "two", "a", True))

    # ── 5c. a user's FZF_DEFAULT_OPTS can't take ctrl-g away (or make matching exact)
    s.t("set-environment", "-g", "FZF_DEFAULT_OPTS", "--bind ctrl-g:abort --exact")
    s.t("new-session", "-d", "-s", "y", "-n", "yak")
    s.t("new-window", "-d", "-t", "y:", "-n", "yodel")
    find(c1, "ydl", CTRL_G, wait=(r"\b1/10\b",))
    check("FZF_DEFAULT_OPTS='--bind ctrl-g:abort --exact': fuzzy match, ctrl-g still grabs",
          (s.windows()["a"][-1], said(c1.tty, "Grabbed yodel from y")), ("yodel", True))
    s.t("set-environment", "-gu", "FZF_DEFAULT_OPTS")
    s.t("kill-session", "-t", "y")
    s.t("kill-window", "-t", "a:yodel")

    # ── 5d. @bellhop-preview off starts the preview hidden
    s.t("set", "-g", "@bellhop-preview", "off")
    mark = len(c1.buf)
    c1.keys(PREFIX, "/")
    pid = wait_for(lambda: fzf_of(c1.tty, "find"), "the popup's fzf")
    c1.wait_prompt(mark, "find a tab ›")
    args = procs().get(pid, ("", ""))[1]
    check("@bellhop-preview off: fzf starts with the preview hidden",
          bool(re.search(r"--preview-window=\S*,hidden\b", args)), True)
    c1.keys(ESC)
    wait_for(lambda: not popup_open(c1.tty, "find"), "the popup to close")
    s.t("set", "-gu", "@bellhop-preview")

    # ── 6. grabbing a session's last tab carries its attached client along
    c2 = Client(s, "c", 160, 40)
    find(c1, "sea$", CTRL_G, wait=(r"\b1/8\b",))          # plain "sea" also matches search-bug
    w = s.windows()
    check("grab last tab: c gone, sea at the end of a", ("c" in w, w["a"][-1]), (False, "sea"))
    check("grab last tab: c's client alive, carried to a, both on sea",
          (c2.alive(), c2.session(), c1.session(), current("a")), (True, "a", "a", "sea"))

    # ── 7. awkward tabs: a name that looks like a tmux format, an empty name, and a
    #       tab linked into this session as well as another
    s.t("new-session", "-d", "-s", "q", "-n", "keep")
    s.t("new-window", "-d", "-t", "q:", "-n", "##{session_name}-fmt")
    s.t("new-window", "-d", "-t", "q:", "-n", "")
    s.t("set", "-w", "-t", "q:3", "automatic-rename", "off")
    s.t("rename-window", "-t", "q:3", "")
    s.t("new-window", "-d", "-t", "q:", "-n", "shared")
    s.t("link-window", "-d", "-s", "q:shared", "-t", "a:")
    find(c1, "fmt", CTRL_G, wait=(r"\b1/\d+\b",))
    check("grab: a #{...} tab name is shown as typed", said(c1.tty, "Grabbed #{session_name}-fmt from q"), True)
    before = s.windows()
    find(c1, "'q 'shared", CTRL_G, wait=(r"\b1/\d+\b",))
    check("grab a tab linked here too: nothing moved, said already here",
          (s.windows(), said(c1.tty, "shared is already here")), (before, True))
    find(c1, "'q !keep !shared", CTRL_G, wait=(r"\b1/\d+\b",))
    check("grab an unnamed tab: message names nothing, not the row text", said(c1.tty, "Grabbed  from q"), True)

    # ── 8. typed in a session no client is attached to: says so (tmux would otherwise
    #       hand back c1, attached to a, and the popup would open on c1's screen)
    s.t("new-session", "-d", "-s", "solo")
    s.t("send-keys", "-t", "solo:", f"{BELLHOP} find; echo RC=$?", "Enter")
    out = wait_for(lambda: (lambda o: o if re.search(r"^RC=\d", o, re.M) else None)(
        s.t("capture-pane", "-p", "-t", "solo:")), "solo rc")
    check("no client: clear error, exit 1, no popup on another session's client",
          ("bellhop find: no client is attached to this session" in out, "RC=1" in out, popup_open(c1.tty)),
          (True, True, False))

    # ── 9. tmux's default automatic-rename: the tab is named after its command (sh,
    #       or bash where /bin/sh is bash), the Claude title is shown after it and is
    #       what you type to find it
    s.t("new-window", "-d", "-t", "zz:")
    auto = wait_for(lambda: (lambda n, c: n if n and n == c else None)(
        *s.fmt("zz:2", "#{window_name}\t#{pane_current_command}").split("\t")), "tmux to name the tab")
    s.t("select-pane", "-t", "zz:2", "-T", "✳ Tidy the release script")
    sid_a, wid = s.fmt("a:", "#{session_id}"), s.fmt("a:", "#{window_id}")
    r, _ = rows(sid_a, wid)
    row = next((x for x in r if x[0] == s.window("zz:2")), None)
    check("automatic-rename: the row is the tab name, then the title without its glyph",
          (auto in ("sh", "bash", "dash"), row and row[5]),
          (True, f"    {'zz':<18} {auto} · Tidy the release script  ✳ idle"))
    seen = find(c1, "tidy release", ENTER, wait=(r"\b1/\d+\b", f"{auto} · Tidy the release script"))
    check("automatic-rename: the conversation title is matched and shown",
          seen, {r"\b1/\d+\b": True, f"{auto} · Tidy the release script": True})
    check("automatic-rename: enter goes to that tab", c1.where()[:2], ("zz", "2"))

    # With @bellhop-tab-titles on the tab takes the title's name, so it isn't repeated.
    s.t("set", "-g", "@bellhop-tab-titles", "on")
    s.t("run-shell", os.path.join(REPO, "bellhop.tmux"))
    s.t("send-keys", "-t", "zz:2", "Enter")         # tmux renames a tab when its pane next draws
    wait_for(lambda: s.fmt("zz:2", "#{window_name}") == "Tidy the release script", "the tab named after the title")
    r, _ = rows(sid_a, wid)
    row = next((x for x in r if x[0] == s.window("zz:2")), None)
    check("@bellhop-tab-titles on: the title is the tab name and is not repeated",
          row and row[5], f"    {'zz':<18} Tidy the release script  ✳ idle")

    # ── 10. no map file: running sessions numbered 1-9 then 0 in list-sessions
    #        order, and the rows follow that numbering (the tenth, 0, comes last)
    for n in range(10 - len(s.t("list-sessions", "-F", "#{session_name}").splitlines())):
        s.t("new-session", "-d", "-s", f"m{n}", "-n", f"tab{n}")
    order = s.t("list-sessions", "-F", "#{session_name}").splitlines()
    r, _ = rows(sid_a, wid, env=s.tmux_env(BELLHOP_MAP=os.path.join(s.home, "no-such-map")))
    seen_order = []
    for x in r:
        if x[3] not in seen_order:
            seen_order.append(x[3])
    slots = {x[3]: x[5][1] for x in r}
    check("no map: sessions in list-sessions order, numbered 1-9 then 0",
          (seen_order, [slots[n] for n in seen_order]), (order, list("1234567890")))
except Exception as e:                      # a timeout or tmux error: record it, keep the artifacts
    check(f"no error ({type(e).__name__})", str(e), "")
    s.dump("find")

done()

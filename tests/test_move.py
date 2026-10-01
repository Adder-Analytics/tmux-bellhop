"""bellhop move end to end on a throwaway tmux server, driven through real clients.

The whole body runs twice: under the fixture's prefix (C-b), then with
`set -g prefix C-a`. Both runs press ctrl-a (mark all) and the stay-behind key
inside the popup, which proves they reach fzf whichever key is the prefix.

Keys go to one fzf at a time. Between steps the driver waits for the popup to
move on (a new fzf for the next step, or the popup closing) and for the new
fzf's prompt to be drawn, never on fixed sleeps.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import (BELLHOP, CTRL, ENTER, ESC, Client, Server, check, done, fzf_of,  # noqa: E402
                     popup_open, procs, wait_for)

s = Server("move")
HOME = s.home
PROJ_D = os.path.join(HOME, "proj d")          # slot 3's folder: exists, and has a space
os.makedirs(PROJ_D)
MAP = os.path.join(HOME, "map")
with open(MAP, "w") as f:
    # Slots 0-4 are a, b, c, d, e. Only a, b and c run at first; e's folder is never made.
    f.write("# test map\n0  a  ~\n1  b  ~\n2  c\n3  d  ~/proj d\n4  e  ~/gone\n")
s.env["BELLHOP_MAP"] = MAP

# A step 2 row as drawn: fzf's gutter, the digit, the session, then what else was
# drawn on that line (· here, not started; a tab count can land on a line of its own).
ROW = re.compile(r"^[▌>\s]*(\d)  (\S+)\s*(.*)$")
PREFIX = None
TROUBLE = []                                    # "something went wrong" messages, across restarts


def trouble():
    if s.alive():
        TROUBLE.extend(m for m in s.t("show-messages").splitlines() if "went wrong" in m)
    return TROUBLE


def gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def stop():
    """Kill the server and wait for its process to end (a new one can't start on a dying socket)."""
    if s.alive():
        pid = int(s.t("display-message", "-p", "#{pid}"))
        trouble()
        s.kill()
        wait_for(lambda: gone(pid), "the old server to exit")


def fresh(prefix):
    """A new server: a (one, two, three), b (bee), c (sea); the prefix under test."""
    stop()
    s.start("-s", "a", "-n", "one")
    s.t("new-window", "-d", "-t", "a:", "-n", "two")
    s.t("new-window", "-d", "-t", "a:", "-n", "three")
    s.t("new-session", "-d", "-s", "b", "-n", "bee")
    s.t("new-session", "-d", "-s", "c", "-n", "sea")
    if prefix == "C-a":
        s.t("set-option", "-g", "prefix", "C-a")


def state():
    return s.windows()


def current(session):
    return s.fmt(f"{session}:", "#{window_name}")


def message(c):
    """The newest status message shown on this client."""
    tag = f"{c.tty} message: "
    for line in s.t("show-messages").splitlines():
        if tag in line:
            return line.split(tag, 1)[1]
    return None


def move(c, *stages, typed_in=None, snapshot=False):
    """Open move (by key, or typed into a pane) and feed each stage to one fzf.

    With snapshot, returns the lines drawn up to the last stage (the rows and the
    header of step 2)."""
    mark = len(c.buf)
    if typed_in:
        s.t("send-keys", "-t", typed_in, f"{BELLHOP} move", "Enter")
    else:
        c.keys(PREFIX, "m")
    pid = wait_for(lambda: fzf_of(c.tty, "move"), "the move popup's fzf")
    drawn = None
    for i, keys in enumerate(stages):
        args = procs().get(pid, ("", ""))[1]
        want = "which tabs ›" if "which tabs" in args else " to ›"
        c.wait_prompt(mark, want)
        if snapshot and i == len(stages) - 1:
            wait_for(lambda: any("stay behind" in line for line in c.text(mark)), "the step 2 header")
            drawn = c.text(mark)
        mark = len(c.buf)
        c.keys(*keys)
        old = pid
        pid = wait_for(lambda: (fzf_of(c.tty, "move") not in (None, old) and fzf_of(c.tty, "move"))
                       or (not popup_open(c.tty, "move") and "closed"), "the next step or the popup closing")
        if pid == "closed":
            break
    wait_for(lambda: not popup_open(c.tty, "move"), "the popup to close")
    return drawn


def rows_of(drawn):
    """[(digit, session, rest of the line)] for every numbered row drawn."""
    return [m.groups() for m in map(ROW.match, drawn) if m]


def rule_drawn(drawn):
    """The rule between numbered and other sessions (not fzf's own long separators)."""
    return any(re.sub(r"^[▌>\s]*", "", line) == "──" for line in drawn)


def body(prefix):
    global PREFIX
    PREFIX = CTRL["b"] if prefix == "C-b" else CTRL["a"]
    stay = CTRL["s"]
    p = f"[{prefix}] "

    # A. typed in a shell: this tab → press 1 (slot b); you go with it
    fresh(prefix)
    c = Client(s, "a")
    drawn = move(c, (ENTER,), ("1",), typed_in="a:1", snapshot=True)
    check(p + "A typed: one tab to b by digit", state(), {"a": ["two", "three"], "b": ["bee", "one"], "c": ["sea"]})
    check(p + "A went with it, landed on the tab", (c.session(), current("b")), ("b", "one"))
    rows = rows_of(drawn)
    check(p + "A every slot in slot order", [r[:2] for r in rows],
          [("0", "a"), ("1", "b"), ("2", "c"), ("3", "d"), ("4", "e")])
    check(p + "A yours is · here, d and e are not started, b and c are not",
          [r[2] if r[2] in ("· here", "not started") else "" for r in rows],
          ["· here", "", "", "not started", "not started"])
    check(p + "A the header names ctrl-s, no map nudge",
          (any("0-9 move and go with it · enter this one · ctrl-s stay behind" in line for line in drawn),
           any("map init" in line for line in drawn)), (True, False))
    check(p + "A the prompt names the tab", any("move one to ›" in line for line in drawn), True)
    check(p + "A the message names the tab only", message(c), "Moved one → b")

    # B. ctrl-s on a typed row: move but stay behind
    move(c, (ENTER,), ("c", stay))
    check(p + "B ctrl-s moved the tab", state(), {"a": ["two", "three"], "b": ["bee"], "c": ["sea", "one"]})
    check(p + "B ...and stayed in b", c.session(), "b")
    check(p + "B message", message(c), "Moved one → c")

    # C. your own number is a no-op; esc is a no-op (b has one tab now: no step 1)
    snap = state()
    move(c, ("1",))
    check(p + "C own number does nothing", (state(), c.session(), message(c)), (snap, "b", "Already here"))
    move(c, (ESC,))
    check(p + "C esc is a no-op", state(), snap)

    # D. a not-started slot: press 3 → d starts in its folder holding just the tab; you follow
    move(c, ("3",))
    w = state()
    check(p + "D slot 3 started as d holding just the tab, b gone", (w.get("d"), "b" in w), (["bee"], False))
    check(p + "D d's folder is the slot's, client followed", (s.fmt("d:", "#{session_path}"), c.session()),
          (PROJ_D, "d"))
    check(p + "D message", message(c), "Moved bee → d (started)")

    # D2. the slot's folder is gone: e starts in ~ and the message says so
    move(c, ("4",))
    w = state()
    check(p + "D2 slot 4 started as e in ~, d gone", (w.get("e"), "d" in w, s.fmt("e:", "#{session_path}")),
          (["bee"], False, HOME))
    check(p + "D2 message says started in ~", (message(c), c.session()), ("Moved bee → e (started in ~)", "e"))

    # E. a lone tab by digit: its session ends, you arrive on the moved tab
    move(c, ("2",))
    check(p + "E lone tab to c, e gone", state(), {"a": ["two", "three"], "c": ["sea", "one", "bee"]})
    check(p + "E arrived on the moved tab", (c.session(), current("c")), ("c", "bee"))

    # F. ctrl-a marks all; esc at step 2 does nothing; then all to slot 0, appended after a's
    #    tabs in tab-bar order
    snap = state()
    move(c, (CTRL["a"], ENTER), (ESC,))
    check(p + "F esc at step 2 is a no-op", state(), snap)
    move(c, (CTRL["a"], ENTER), ("0",))
    check(p + "F all of c appended to a in tab-bar order, c gone", state(),
          {"a": ["two", "three", "sea", "one", "bee"]})
    check(p + "F followed, first moved tab selected", (c.session(), current("a")), ("a", "sea"))
    check(p + "F message counts the tabs", message(c), "Moved 3 tabs → a")

    # G. a second client on the source session is carried along too
    fresh(prefix)
    c1, c2 = Client(s, "a"), Client(s, "a")
    move(c1, (CTRL["a"], ENTER), ("2",))
    check(p + "G all tabs to c", state(), {"b": ["bee"], "c": ["sea", "one", "two", "three"]})
    check(p + "G both clients alive in c", (c1.alive(), c2.alive(), c1.session(), c2.session()),
          (True, True, "c", "c"))

    # H. a session with no slot: not reachable by a digit, reachable by name
    s.t("new-session", "-d", "-s", "zz", "-n", "zed")
    move(c1, (ENTER,), ("9",))
    check(p + "H a digit with no slot does nothing", state()["zz"], ["zed"])
    move(c1, (ENTER,), ("zz", ENTER))     # c1's tab in c is "one", the first tab G moved
    check(p + "H unslotted session reachable by name, followed", (state()["zz"], c1.session()),
          (["zed", "one"], "zz"))

    # I. @bellhop-move-stay-key picks the stay-behind key, and the header names it
    s.t("set-option", "-g", "@bellhop-move-stay-key", "ctrl-t")
    drawn = move(c1, (ENTER,), ("c", CTRL["t"]), snapshot=True)
    check(p + "I the header names ctrl-t", any("enter this one · ctrl-t stay behind" in line for line in drawn), True)
    check(p + "I ctrl-t moved the tab and stayed", (state()["c"], state()["zz"], c1.session()),
          (["sea", "two", "three", "one"], ["zed"], "zz"))
    s.t("set-option", "-gu", "@bellhop-move-stay-key")

    # J. no map: the running sessions in name order are 1-9, then 0; the 11th has no number
    #    and sits under the rule; nothing is "not started"
    fresh(prefix)
    s.t("set-environment", "-gu", "BELLHOP_MAP")          # falls back to ~/.config/bellhop/map: absent
    for name in ("ab", "d7", "d6", "d5", "d4", "d3", "d2", "d1"):
        s.t("new-session", "-d", "-s", name, "-n", "w" + name)   # made after b and c, listed by name
    c = Client(s, "a", cols=200, rows=50)                 # room for the whole header and every row
    drawn = move(c, (ENTER,), ("0",), snapshot=True)
    check(p + "J no map: running sessions numbered 1-9 then 0 in list-sessions order",
          [r[:2] for r in rows_of(drawn)],
          [("1", "a"), ("2", "ab"), ("3", "b"), ("4", "c"), ("5", "d1"), ("6", "d2"), ("7", "d3"),
           ("8", "d4"), ("9", "d5"), ("0", "d6")])
    check(p + "J no map: the 11th session is under the rule, nothing is not started",
          (rule_drawn(drawn), any(re.search(r"^[▌>\s]*d7\b", line) for line in drawn),
           any("not started" in line for line in drawn)), (True, True, False))
    check(p + "J no map: the header says how to pin the numbers",
          any("ctrl-s stay behind · bellhop map init to pin these" in line for line in drawn), True)
    w = state()
    check(p + "J no map: 0 moved the tab to the 10th session, followed",
          (w["a"], w["d6"], c.session(), current("d6")), (["two", "three"], ["wd6", "one"], "d6", "one"))

    # K. typed in a session no client is attached to: says so (tmux would otherwise
    #    hand back c, attached to d6, and the popup would open on c's screen)
    s.t("new-session", "-d", "-s", "solo")
    s.t("send-keys", "-t", "solo:", f"{BELLHOP} move; echo RC=$?", "Enter")
    out = wait_for(lambda: (lambda o: o if re.search(r"^RC=\d", o, re.M) else None)(
        s.t("capture-pane", "-p", "-t", "solo:")), "solo rc")
    check(p + "K no client: clear error, exit 1, no popup on another session's client",
          ("bellhop move: no client is attached to this session" in out, "RC=1" in out, popup_open(c.tty)),
          (True, True, False))

    stop()
    check(p + "no 'something went wrong' message on the way", trouble(), [])


try:
    for prefix in ("C-b", "C-a"):
        body(prefix)
except Exception:
    s.dump("test_move")
    raise
done()

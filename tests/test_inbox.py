"""bellhop inbox end to end on throwaway tmux servers.

Pane states come the way they do for real: titles as Claude Code sets them, pane
options from the real bin/bellhop-hook fed hook JSON, bells written by the hook
to pane ttys. The driver waits on processes and drawn text (the popup's fzf, its
prompt, the bell flag), not on fixed sleeps.
"""
import json
import os
import re
import shlex
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import (CTRL, ENTER, ESC, HOOK, REPO, TMUX, Client, Server, check, done, fzf_of,  # noqa: E402
                     popup_open, procs, skip, tempdir, uuid, wait_for)

PREFIX = CTRL["b"]                      # the fixture keeps tmux's default prefix
PROMPT = "claude ›"
BADGES = ("needs you", "finished", "working", "idle")
BELLHOP = os.path.join(REPO, "bin", "bellhop")

s = Server("inbox")
MAP = os.path.join(s.home, "map")
with open(MAP, "w") as f:
    f.write("# test map\n0  a  ~\n1  b  ~\n2  c  ~\n3  d  ~\n")
s.env["BELLHOP_MAP"] = MAP


def descends(pid, root, d):
    """True when pid is root or one of its descendants (d from procs())."""
    for _ in range(20):
        if pid == root:
            return True
        if pid not in d:
            return False
        pid = d[pid][0]
    return False


def inbox_running(server):
    """The inbox itself, or the tmux client it became to hold the popup, under this server."""
    d = procs()
    root = server.pid
    return any("libexec/bellhop-inbox" in args and re.match(r"(\S*/)?(bash|tmux) ", args) and descends(pid, root, d)
               for pid, (_, args) in d.items())


def open_popup(c, typed_in=None):
    start = len(c.buf)
    if typed_in:
        c.server.t("send-keys", "-t", typed_in, f"{shlex.quote(BELLHOP)} inbox", "Enter")
    else:
        c.keys(PREFIX, "i")
    wait_for(lambda: fzf_of(c.tty, "inbox"), "the inbox popup's fzf")
    c.wait_prompt(start, PROMPT)
    return start


def finish(c, *keys):
    c.keys(*keys)
    wait_for(lambda: not popup_open(c.tty, "inbox"), "the popup to close")
    wait_for(lambda: not inbox_running(c.server), "bellhop inbox to exit")


# ── The server: every state, two Claudes in one tab, Claudes off the map ──────
s.start("-s", "a", "-n", "one")
for name in ("two", "lobby", "work"):
    s.t("new-window", "-d", "-t", "a:", "-n", name)
s.t("split-window", "-d", "-h", "-t", "a:3")
s.t("new-session", "-d", "-s", "b", "-n", "bee")
s.t("new-window", "-d", "-t", "b:", "-n", "shell")
s.t("new-session", "-d", "-s", "c", "-n", "sea")
s.t("new-window", "-d", "-t", "c:", "-n", "bare")
s.t("new-session", "-d", "-s", "zz", "-n", "zed")
s.t("new-window", "-d", "-t", "zz:", "-n", "zwork")

P = {k: s.pane(k) for k in ("a:1", "a:2", "a:3.1", "a:3.2", "a:4", "b:1", "b:2", "c:1", "c:2", "zz:1", "zz:2")}
titles = {"a:1": "✳ home", "a:2": "✳ ask", "a:3.1": "✳ lobby done", "a:3.2": "✳ lobby idle", "a:4": "◐ building",
          "b:1": "✳ bee done", "c:1": "◐ sea work", "c:2": "✳ bare", "zz:1": "✳ zed ask", "zz:2": "◐ zed work"}
for k, title in titles.items():
    s.t("select-pane", "-t", P[k], "-T", title)

c = Client(s, "a")                      # on a:1, so bells elsewhere flag their tabs
sid = lambda p: uuid(f"{int(p.strip('%')) % 256:02x}")


def bell(key, *events, **fields):
    for event in events:
        s.hook(P[key], event, session_id=sid(P[key]), **fields)


PERM = dict(message="Claude needs your permission to use Bash")
bell("a:1", "SessionStart")
bell("a:2", "SessionStart", "UserPromptSubmit")
bell("a:2", "Notification", **PERM)
bell("a:3.1", "SessionStart", "UserPromptSubmit", "Stop")
bell("a:3.2", "SessionStart")
bell("a:4", "SessionStart", "UserPromptSubmit")
bell("b:1", "SessionStart", "UserPromptSubmit", "Stop")
bell("zz:1", "SessionStart")
bell("zz:1", "Notification", message="Claude needs your permission to run rm -rf build")
now = int(time.time())
# Pin both stamps: the hook also writes @bellhop_rang (when it last rang), which
# the inbox prefers to @bellhop_since for "rang Xm ago".
for k, ago in (("a:1", 7200), ("a:2", 60), ("a:3.1", 120), ("a:3.2", 3600), ("a:4", 180), ("b:1", 900), ("zz:1", 600)):
    s.t("set", "-p", "-t", P[k], "@bellhop_since", str(now - ago))
    s.t("set", "-p", "-t", P[k], "@bellhop_rang", str(now - ago))
flag = lambda k: s.fmt(k, "#{window_bell_flag}")
wait_for(lambda: flag("a:3") == "1" and flag("b:1") == "1", "bell flags on a:3 and b:1")
check("setup: we're on a:1, the hook rang a:3 and b:1", (c.where(), flag("a:3"), flag("b:1")),
      (("a", "1", P["a:1"]), "1", "1"))

# Something on a:2's screen for the preview to show.
s.t("send-keys", "-t", P["a:2"], "echo ASKING-FOR-BASH", "Enter")
wait_for(lambda: s.t("capture-pane", "-p", "-t", P["a:2"]).count("ASKING-FOR-BASH") >= 2, "echo on a:2")


def rows(here="", env=None):
    out, _, rc = s.bellhop("inbox", "--rows", here, env=env)
    return rc, [line.split("\t") for line in out.split("\n") if line]


# ── 1. --rows: urgency order, then newest, then slot / tab; one row per pane ──
rc, rs = rows(P["a:1"])
check("rows: exits 0, 9 columns each", (rc, {len(r) for r in rs}), (0, {9}))
check("rows: order and columns (state slot session tab title detail here)", [tuple(r[2:]) for r in rs], [
    ("needs-you", "0", "a", "2", "ask", "permission to use Bash", "0"),
    ("needs-you", "", "zz", "1", "zed ask", "permission to run rm -rf build", "0"),
    ("finished", "0", "a", "3", "lobby done", "rang 2m ago", "0"),
    ("finished", "1", "b", "1", "bee done", "rang 15m ago", "0"),
    ("working", "0", "a", "4", "building", "3m", "0"),
    ("working", "2", "c", "1", "sea work", "", "0"),
    ("working", "", "zz", "2", "zed work", "", "0"),
    ("idle", "0", "a", "1", "home", "2h", "1"),
    ("idle", "0", "a", "3", "lobby idle", "1h", "0"),
    ("idle", "2", "c", "2", "bare", "", "0"),
])
check("rows: two Claudes in lobby:3 are two rows with their own pane ids",
      [r[1] for r in rs if r[5] == "3" and r[4] == "a"], [P["a:3.1"], P["a:3.2"]])
check("rows: window ids are the tabs'", rs[0][0], s.window("a:2"))

out, _, rc = s.bellhop("inbox", "--rows", "--shown", P["a:1"])
shown = out.splitlines()
check("rows --shown: one line per row, no escapes, the text of each row",
      (rc, len(shown), any("\x1b" in line for line in shown), [line.split()[0] for line in shown][:3],
       shown[7].rstrip().endswith("· here")),
      (0, 10, False, ["needs", "needs", "finished"], True))

# The CLI edges.
out, _, rc = s.bellhop("inbox", "--help")
check("--help: keys and flags on stdout, exit 0", (rc, "ctrl-p" in out, "--rows" in out), (0, True, True))
out, _, rc = s.bellhop("help", "inbox")
check("bellhop help inbox: the same page", (rc, out.startswith("usage: bellhop inbox")), (0, True))
_, err, rc = s.bellhop("inbox", "x", "y")
check("two positional arguments: usage on stderr, exit 2", (rc, "usage: bellhop inbox" in err), (2, True))
env = dict(s.env)
env.pop("TMUX", None)
_, err, rc = s.bellhop("inbox", "--rows", env=env)
check("outside tmux: exit 1 with a message", (rc, err.strip()), (1, "bellhop inbox: only works inside tmux"))
_, err, rc = s.bellhop("inbox", env=s.tmux_env(TMUX_PANE=P["b:2"]))
check("typed where no client is attached: exit 1, no popup", (rc, "no client is attached" in err, popup_open(c.tty)),
      (1, True, False))

# fzf too old: a message on the client's status line, no popup.
FAKE = tempdir(prefix="bh-fzf.")
with open(os.path.join(FAKE, "fzf"), "w") as f:
    f.write("#!/bin/sh\necho '0.29.0 (fake)'\n")
os.chmod(os.path.join(FAKE, "fzf"), 0o755)
_, _, rc = s.bellhop("inbox", env=s.tmux_env(TMUX_PANE=P["a:1"], BELLHOP_FZF=os.path.join(FAKE, "fzf")))
msg = wait_for(lambda: "needs fzf" in s.t("show-messages") and s.t("show-messages"), "the fzf message")
check("fzf 0.29: says which fzf it needs, opens no popup, exit 0",
      ("bellhop: needs fzf ≥ 0.42 (found 0.29.0) · bellhop doctor" in msg, popup_open(c.tty), rc), (True, False, 0))

# A title longer than the list can give it: the title gives way, not the detail.
s.t("select-pane", "-t", P["a:4"], "-T", "◐ building the whole world from source, twice over")

# ── 2. typed: the here marker, badges, the preview; Enter goes to the top row ──
start = open_popup(c, typed_in=P["a:1"])
drawn = wait_for(lambda: (lambda l: any("ASKING-FOR-BASH" in x for x in l) and l)(c.text(start)), "preview of a:2")
here_rows = [line for line in drawn if "· here" in line]
check("typed: one row says · here, and it's a:1's Claude",
      (len(here_rows) > 0, all("home" in line for line in here_rows)), (True, True))
check("typed: badges drawn", all(any(b in line for line in drawn) for b in BADGES), True)
check("typed: the preview shows a:2's screen", any("ASKING-FOR-BASH" in line for line in drawn), True)
finish(c, ENTER)
check("typed: Enter jumped to the one that needs you", c.where(), ("a", "2", P["a:2"]))
check("typed: no status message after a jump", "bellhop inbox:" in s.t("show-messages"), False)

# ── 3. the key the plugin bound; Esc does nothing ─────────────────────────────
start = open_popup(c)
drawn = wait_for(lambda: (lambda l: any("· here" in x for x in l) and l)(c.text(start)), "here marker")
check("key: · here follows the pane you pressed it in (a:2)",
      all("ask" in line for line in drawn if "· here" in line), True)
finish(c, ESC)
check("key: Esc goes nowhere", c.where(), ("a", "2", P["a:2"]))

# ── 3b. what the popup draws, read off a real screen: an outer tmux whose pane
#     is a second client on a:2. Narrow puts the preview under the list, wide
#     beside it; --shown is the same text.
o = Server("inbox-outer", conf=None)
before = set(s.t("list-clients", "-F", "#{client_name}").split())
o.start("-s", "o", shlex.join([TMUX, "-S", s.socket, "attach", "-t", "a"]))
tty = wait_for(lambda: next(iter(set(s.t("list-clients", "-F", "#{client_name}").split()) - before), None),
               "outer client")
screen_of = lambda: o.t("capture-pane", "-p", "-t", "o")
# Only the popup's lines (between its borders): the pane behind it shows a:2 too.
popup_of = lambda: "\n".join(line for line in screen_of().splitlines() if line.count("│") >= 2)
HEADER = "enter go there · ctrl-p preview · esc close"
SHOWN = {}


def drawn_rows(screen):
    return [line.split("│")[1] if line.count("│") >= 2 else line
            for line in screen.splitlines() if any(b in line for b in BADGES)]


def outer_popup(cols):
    o.t("send-keys", "-t", "o", "C-b", "i")
    wait_for(lambda: fzf_of(tty, "inbox"), f"outer popup fzf at {cols}")


def outer_close():
    o.t("send-keys", "-t", "o", "Escape")
    wait_for(lambda: not popup_open(tty, "inbox"), "outer popup close")


for cols in (100, 120, 160, 180):
    o.t("resize-window", "-t", "o", "-x", str(cols))
    wait_for(lambda: f"{tty} {cols}" in s.t("list-clients", "-F", "#{client_name} #{client_width}"),
             f"client {cols} wide")
    outer_popup(cols)
    screen = wait_for(lambda: (lambda x: "ASKING-FOR-BASH" in x and "· here" in x and "bare" in x and x)(popup_of()),
                      f"popup drawn at {cols}")
    if cols == 100:
        check("screen: the header names the keys, and prefix L while L is stock",
              HEADER + " · prefix L to come back" in screen, True)
    rows_drawn = drawn_rows(screen)
    row_of = lambda title: next((line for line in rows_drawn if f" {title} " in line), "")
    check(f"screen {cols}: all 10 rows drawn, none cut by fzf (··)",
          (len(rows_drawn), [line for line in rows_drawn if "··" in line]), (10, []))
    check(f"screen {cols}: the detail keeps what it's asking; · here is whole", (
        "rang 15m ago" in row_of("bee done"),
        "permission to run rm" in row_of("zed ask"),
        "building the" in row_of("building the"),       # the title gives way (…), still named
        row_of("ask").rstrip().endswith("· here")), (True, True, True, True))
    inner = cols * 90 // 100 - 2                          # a 90% popup, less its two borders
    out, _, _ = s.bellhop("inbox", "--rows", "--shown", "--cols", str(inner), P["a:2"])
    SHOWN[inner] = out
    check(f"screen {cols}: --rows --shown --cols {inner} is the text drawn",
          [line.strip() for line in out.splitlines() if not any(line.strip() in d for d in rows_drawn)], [])
    outer_close()

# @bellhop-preview off starts the preview hidden; ctrl-p shows it. With L bound
# to something else, the header leaves "prefix L" out.
s.t("set-option", "-g", "@bellhop-preview", "off")
s.t("bind-key", "L", "display-message", "L is mine")
outer_popup(120)
screen = wait_for(lambda: (lambda x: len(drawn_rows(x)) == 10 and HEADER in x and x)(popup_of()),
                  "rows with the preview hidden")
check("@bellhop-preview off: the preview starts hidden", "ASKING-FOR-BASH" in screen, False)
check("L rebound: the header leaves out prefix L", (HEADER in screen, "prefix L" in screen), (True, False))
o.t("send-keys", "-t", "o", "C-p")
wait_for(lambda: "ASKING-FOR-BASH" in popup_of(), "ctrl-p to show the preview")
check("@bellhop-preview off: ctrl-p shows it", True, True)
outer_close()
s.t("set-option", "-gu", "@bellhop-preview")
s.t("bind-key", "L", "switch-client", "-l")
o.kill()
wait_for(lambda: tty not in s.t("list-clients", "-F", "#{client_name}"), "outer client gone")

# The same widths on every awk here (BSD awk, mawk, gawk): identical row text.
AWKS = {}
for name in ("awk", "mawk", "gawk", "nawk", "original-awk"):
    path = shutil.which(name)
    if path and os.path.realpath(path) not in AWKS.values():
        AWKS[name] = os.path.realpath(path)
if len(AWKS) < 2:
    skip("width awk dialects: --shown at 100/120/160/180 columns", f"only one awk here ({', '.join(AWKS)}); "
         "mawk and gawk run in CI")
else:
    pinned = str(int(time.time()))
    got = {}
    for name, path in AWKS.items():
        shim = tempdir(prefix=f"bh-{name}.")
        os.symlink(path, os.path.join(shim, "awk"))
        env = s.tmux_env(PATH=shim + os.pathsep + s.env["PATH"], BELLHOP_NOW=pinned)
        got[name] = [s.bellhop("inbox", "--rows", "--shown", "--cols", str(n), P["a:2"], env=env)[0]
                     for n in sorted(SHOWN)]
    first = next(iter(got.values()))
    check(f"width awk dialects ({', '.join(AWKS)}): identical row text at 100/120/160/180 columns",
          [n for n, v in got.items() if v != first], [])

# ── 4. key: filter to the second Claude in the lobby tab; Enter selects that pane
open_popup(c)
finish(c, "'lobby 'idle", ENTER)          # plain "idle" also matches i…d…l…e in "finished … lobby done"
check("key: filtered jump lands on lobby:3's second pane", c.where(), ("a", "3", P["a:3.2"]))

# ── 5. key: a Claude in a session off the map comes to this client ────────────
open_popup(c)
finish(c, "zed ask", ENTER)
check("key: off-map needs-you, client switched to zz:1", c.where(), ("zz", "1", P["zz:1"]))

# ── 6. typed in a hidden session: jumping to a slotted one switches this client
open_popup(c, typed_in=P["zz:1"])
finish(c, "'sea", ENTER)                # exact: fuzzy "sea" also matches s…e…a in other rows
check("typed: switched to c:1", c.where(), ("c", "1", P["c:1"]))

# FZF_DEFAULT_OPTS can't reach the popup: Enter still goes, and fuzzy still matches.
s.t("set-environment", "-g", "FZF_DEFAULT_OPTS", "--bind enter:abort,ctrl-p:abort --exact")
open_popup(c)
finish(c, "lbyidl", ENTER)
s.t("set-environment", "-gu", "FZF_DEFAULT_OPTS")
check("FZF_DEFAULT_OPTS='--bind enter:abort --exact' is ignored: fuzzy match, Enter jumps",
      c.where(), ("a", "3", P["a:3.2"]))

# ── 6b. which Claude rang, when a tab holds two, or one the hook state lies about
def state_of(pid):
    return next(((r[2], r[6], r[7]) for r in rows()[1] if r[1] == pid), None)


s.t("new-window", "-d", "-t", "a:", "-n", "pair")
s.t("split-window", "-d", "-h", "-t", "a:5")
P["a:5.1"], P["a:5.2"] = s.pane("a:5.1"), s.pane("a:5.2")
s.t("select-pane", "-t", P["a:5.1"], "-T", "✳ pair one")
s.t("select-pane", "-t", P["a:5.2"], "-T", "✳ pair two")
for k in ("a:5.1", "a:5.2"):
    bell(k, "SessionStart", "UserPromptSubmit", "Stop")
wait_for(lambda: flag("a:5") == "1", "a:5 rang")
s.t("select-window", "-t", "a:5")
s.t("select-window", "-t", "a:3")       # seen: the flag clears
wait_for(lambda: flag("a:5") == "0", "a:5 seen")
s.t("set", "-p", "-t", P["a:5.1"], "@bellhop_since", str(int(time.time()) - 3600))
s.t("set", "-p", "-t", P["a:5.1"], "@bellhop_rang", str(int(time.time()) - 3600))
bell("a:5.2", "UserPromptSubmit", "Stop")
wait_for(lambda: flag("a:5") == "1", "a:5 rang again")
check("pair: only the one that just rang is finished; the seen one is idle",
      (state_of(P["a:5.2"])[0], state_of(P["a:5.1"])[0:2]), ("finished", ("idle", "pair one")))

s.t("new-window", "-d", "-t", "a:", "-n", "esc")
P["a:6"] = s.pane("a:6")
s.t("select-pane", "-t", P["a:6"], "-T", "◐ running")
bell("a:6", "SessionStart", "UserPromptSubmit")
s.t("select-pane", "-t", P["a:6"], "-T", "✳ interrupted")     # Esc: no Stop, the hook still says working
bell("a:6", "Notification", message="Claude is waiting for your input")
wait_for(lambda: flag("a:6") == "1", "a:6 rang")
check("interrupted (Esc): a Claude that rang for input is finished", state_of(P["a:6"])[0], "finished")

s.t("new-window", "-d", "-t", "a:", "-n", "braille")
P["a:7"] = s.pane("a:7")
s.t("select-pane", "-t", P["a:7"], "-T", "⠂ braille spinner title")
bell("a:7", "SessionStart", "UserPromptSubmit")
check("braille spinner: working, glyph stripped", state_of(P["a:7"])[0:2], ("working", "braille spinner title"))

# ── 6c. the preview is sanitised: SGR colours only ────────────────────────────
s.t("new-window", "-d", "-t", "b:", "-n", "osc")
osc = s.pane("b:3")
# OSC 2 (title), OSC 52 (clipboard), a cursor move, colour; RE and D-OUT join
# only in the output, so the typed line never matches.
s.t("send-keys", "-t", osc,
    r"printf '\033]2;osc-title\007\033]52;c;b3NjNTI=\007\033[2C\033[31m%s%s\033[0m plain\n' RE D-OUT", "Enter")
wait_for(lambda: "RED-OUT" in s.t("capture-pane", "-p", "-t", osc), "the OSC output")
out, _, rc = s.bellhop("inbox", "--preview", osc)
escapes = re.findall(r"\x1b.?", out)
csi = re.findall(r"\x1b\[[0-9;:?<>=]*[ -/]*[@-~]", out)
check("preview: OSC 52 / OSC 2 gone, SGR kept, no other escape or control",
      (rc, "RED-OUT" in out, "\x1b[31m" in out, "\x1b]" in out, "\x07" in out,
       [e for e in csi if not e.endswith("m")], len(escapes) == len(csi),
       re.findall(r"[\x00-\x08\x0b-\x1a\x1c-\x1f\x7f]", out)),
      (0, True, True, False, False, [], True, []))

# ── 7. no Claudes at all: a message, no popup ─────────────────────────────────
e = Server("inbox-empty")
e.start("-s", "a", "-n", "one")
e.t("new-window", "-d", "-t", "a:", "-n", "two")
ce = Client(e, "a")
out, _, rc = e.bellhop("inbox", "--rows")
check("empty: --rows prints nothing", (rc, out), (0, ""))
ce.keys(PREFIX, "i")
msg = wait_for(lambda: "No Claude Code panes" in e.t("show-messages") and e.t("show-messages"), "the empty message")
wait_for(lambda: not inbox_running(e), "bellhop inbox to exit")
check("empty: says so with the hook hint, opens no popup, stays put",
      ("No Claude Code panes on this server · hook not installed: bellhop hook install" in msg,
       popup_open(ce.tty), ce.where()[:2]), (True, False, ("a", "1")))
e.t("send-keys", "-t", "a:1", f"{shlex.quote(BELLHOP)} inbox; echo inbox-rc=$?", "Enter")
rc = wait_for(lambda: re.findall(r"^inbox-rc=(\d+)", e.t("capture-pane", "-p", "-t", "a:1"), re.M),
              "typed inbox to return")
check("empty: typed exits 0", rc, ["0"])

HOOKCTL = os.path.join(REPO, "libexec", "bellhop-hookctl")
if os.path.exists(HOOKCTL):
    settings = os.path.join(e.home, "settings.json")
    entry = {"hooks": [{"type": "command", "timeout": 5, "command": f"test -x '{HOOK}' && '{HOOK}' || true"}]}
    with open(settings, "w") as f:
        json.dump({"hooks": {ev: [entry] for ev in
                             ("SessionStart", "UserPromptSubmit", "Notification", "Stop", "SessionEnd")}}, f, indent=2)
    e.t("send-keys", "-t", "a:1", "clear", "Enter")
    e.t("send-keys", "-t", "a:1",
        f"BELLHOP_CLAUDE_SETTINGS={shlex.quote(settings)} {shlex.quote(BELLHOP)} inbox; echo inbox-rc2=$?", "Enter")
    wait_for(lambda: re.search(r"^inbox-rc2=\d", e.t("capture-pane", "-p", "-t", "a:1"), re.M),
             "typed inbox with the hook installed")
    # (show-messages lists the newest first)
    last = [line for line in e.t("show-messages").splitlines() if "message: No Claude Code panes" in line][0]
    check("empty, hook installed: no hint", last.rstrip().endswith("No Claude Code panes on this server"), True)
else:
    skip("empty, hook installed: no hint", "libexec/bellhop-hookctl is not built yet")

# A last look: nothing of ours is left running under either server.
check("cleanup: no inbox process left", (inbox_running(s), inbox_running(e)), (False, False))
done()

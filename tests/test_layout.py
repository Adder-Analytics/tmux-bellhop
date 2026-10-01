"""bellhop save / bellhop restore across a tmux "reboot", on throwaway servers only.

Panes run a plain /bin/sh whose PATH is a fake `claude` + /usr/bin:/bin, so a typed
`claude --resume` can only ever reach the fake, which records its arguments and
folder. restore never presses Enter; the test does, to prove the typed line is right.
bellhop itself runs with the same PATH, so on macOS it runs under /bin/bash 3.2.
"""
import os
import re
import select
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import BELLHOP, TMUX, Server, check, done, scaled, skip, tempdir, uuid, wait_for  # noqa: E402

TMP = tempdir(prefix="bh-layout.")


def mk(*parts):
    d = os.path.join(TMP, *parts)
    os.makedirs(d, exist_ok=True)
    return d


A, SUB, B, Z = mk("proj-a"), mk("proj-a", "sub"), mk("proj-b"), mk("elsewhere")
OTHER = mk("proj-a", "other")                                   # where a:3's Claude (the inactive split) runs
WT = mk("proj-a-worktrees", "feature")                          # deleted before the restore
FAKE, ARGS = mk("fakebin"), os.path.join(TMP, "claude-args")
with open(os.path.join(FAKE, "claude"), "w") as f:
    f.write(f'#!/bin/sh\necho "$* @ $PWD" >> "{ARGS}"\n')
os.chmod(os.path.join(FAKE, "claude"), 0o755)
PATH = f"{FAKE}:/usr/bin:/bin"
if shutil.which("claude", path=PATH) != os.path.join(FAKE, "claude"):
    sys.exit("refusing: a real claude would be reachable from the restored tabs")
MAP = os.path.join(TMP, "map")
with open(MAP, "w") as f:
    f.write(f"# test map\n0  a  {A}\n1  b  {B}\n2  c  {TMP}/proj-c\n")

s = Server("layout", env=dict(BELLHOP_MAP=MAP, PATH=PATH, PS1="$ "))
STATE = os.path.join(s.home, ".local", "state", "bellhop")
LAYOUT = os.path.join(STATE, s.name, "layout")                  # its folder doesn't exist yet


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def rows(text):
    return [line.split("\t") for line in (text or "").splitlines() if line and not line.startswith("#")]


# Panes run a plain non-login /bin/sh (a login shell reads the system profile and its
# prompt). The fixture sets nothing like that, so each start sets it; a server that
# `bellhop restore` starts itself reads it from this HOME's ~/.tmux.conf.
with open(os.path.join(s.home, ".tmux.conf"), "w") as f:
    f.write("set -g base-index 1\nset -g default-command /bin/sh\n")


def start(*first_session):
    s.start(*first_session)
    s.t("set", "-g", "default-command", "/bin/sh")


core = lambda text: [r[:7] for r in rows(text)]                 # without window_id, ended, autorename
at = s.fmt
screen = lambda target: s.t("capture-pane", "-p", "-t", target)


def typed(target):
    """The lines of a pane that mention claude (what restore typed)."""
    return [line.rstrip() for line in screen(target).splitlines() if "claude" in line]


def shows(target, text, timeout=5):
    """True once a line of the pane ends with text (the shell echoes typed keys a little later)."""
    try:
        return bool(wait_for(lambda: any(line.endswith(text) for line in typed(target)), f"{text!r} in {target}",
                             timeout=timeout))
    except RuntimeError:
        return False


def bh(*args, env=None, timeout=60):
    """bellhop with stdin a pipe (never a terminal); (stdout + stderr, rc)."""
    out, err, rc = s.bellhop(*args, env=env, input="", timeout=timeout)
    return out + err, rc


def claude(target, event, session_id, **env):
    """Feed the real hook a Claude Code event for the pane at target."""
    return s.hook(s.pane(target), event, env=s.tmux_env(**env) if env else None, session_id=session_id, cwd=s.home)


def header(text):
    h = ((text or "").split("\n")[0].split() + [""] * 6)[:7]
    return h


def on_tty(args, env, answer, timeout=30):
    """Run bellhop on a pty; answer the [y/N] question. (output, rc, asked)."""
    master, slave = os.openpty()
    p = subprocess.Popen([BELLHOP, *args], stdin=slave, stdout=slave, stderr=slave, env=env,
                         start_new_session=True, close_fds=True)
    os.close(slave)
    buf, sent, t0 = b"", False, time.time()
    while time.time() - t0 < scaled(timeout):
        r, _, _ = select.select([master], [], [], 0.1)
        if r:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buf += chunk
        if not sent and b"[y/N]" in buf:
            os.write(master, answer.encode())
            sent = True
        if not r and p.poll() is not None:
            break
    rc = p.wait(timeout=scaled(10))
    os.close(master)
    return buf.decode("utf-8", "replace").replace("\r", ""), rc, sent


# ── 1. The first server ───────────────────────────────────────────────────────
# a (slot 0) with three tmux-named tabs, one of them split; b (slot 1); zz off the map,
# with a Claude that never told us its session and a tab named by hand; scratch-x,
# which @bellhop-save-ignore leaves out.
start("-s", "a", "-n", "one", "-c", SUB)
s.t("set", "-g", "@bellhop-autosave", "off")                   # saves in this part are the test's own
s.t("new-window", "-d", "-t", "a:", "-n", "two", "-c", WT)
s.t("new-window", "-d", "-t", "a:", "-n", "three", "-c", A)
s.t("split-window", "-d", "-t", "a:3", "-c", OTHER)            # -d: the plain first pane stays active
s.t("new-session", "-d", "-s", "b", "-n", "bee", "-c", B)
s.t("new-session", "-d", "-s", "zz", "-n", "zed", "-c", Z)
s.t("new-session", "-d", "-s", "scratch-x", "-n", "worker", "-c", Z)
s.t("set", "-g", "@bellhop-save-ignore", "scratch-*")
for w, n in (("a:1", "one"), ("a:2", "two"), ("a:3", "three")):
    # tmux names these tabs (automatic-rename on); a per-window format keeps the name steady
    s.t("set", "-w", "-t", w, "automatic-rename-format", n)
    s.t("set", "-w", "-t", w, "automatic-rename", "on")
s.t("rename-window", "-t", "zz:1", "backend")                  # named by hand
claude("a:1", "UserPromptSubmit", uuid("a1"))
claude("a:2", "UserPromptSubmit", uuid("a2"))
claude("a:3.1", "UserPromptSubmit", uuid("a3"))                # the Claude is in the inactive pane (0-based)
claude("b:1", "UserPromptSubmit", uuid("b1"))
claude("scratch-x:1", "UserPromptSubmit", uuid("f1"))
s.t("select-pane", "-t", "zz:1", "-T", "✳ zed")                # a Claude by its title, no session id

out, rc = bh("save")
saved = read(LAYOUT) or ""
h = header(saved)
check("save: exits 0, first line '# bellhop layout 1 <epoch> <server-id>'",
      (rc, h[:4], len(saved.split("\n")[0].split()), h[4].isdigit() and abs(int(h[4]) - time.time()) < 120,
       h[5]),
      (0, ["#", "bellhop", "layout", "1"], 6, True, s.t("display-message", "-p", "#{pid}.#{start_time}")))
want = [["0", "a", "1", "one", SUB, uuid("a1"), "idle"],
        ["0", "a", "2", "two", WT, uuid("a2"), "idle"],
        ["0", "a", "3", "three", OTHER, uuid("a3"), "idle"],
        ["1", "b", "1", "bee", B, uuid("b1"), "idle"],
        ["", "zz", "1", "backend", Z, "", "idle"]]
check("save: a line per tab, the Claude's pane's path, any pane's Claude, scratch-x ignored", core(saved), want)
check("save: window ids, nothing ended, autorename 1 for tmux-named tabs and 0 for named ones",
      [r[7:] for r in rows(saved)],
      [[at(w, "#{window_id}"), "", ar] for w, ar in (("a:1", "1"), ("a:2", "1"), ("a:3", "1"), ("b:1", "0"),
                                                     ("zz:1", "0"))])
d = os.path.dirname(LAYOUT)
check("save: written by rename, no temp files left; file 600, folder 700",
      (sorted(os.listdir(d)), oct(os.stat(LAYOUT).st_mode & 0o777), oct(os.stat(d).st_mode & 0o777)),
      (["layout", "layout.lock"], "0o600", "0o700"))
out, rc = bh("save", "--bogus")
check("save: an unknown flag is a usage error (2)", (rc, "usage: bellhop save" in out), (2, True))

# Per-socket state: save on -L X writes <state>/X/layout, never <state>/default/layout.
o = Server("other", conf=None)
o.start("-s", "d")
oenv = dict(s.env, TMUX_TMPDIR=o.tmpdir)                       # s's HOME and state, o's socket folder
_, _, rc = s.bellhop("save", "-L", o.name, env=oenv, input="")
olay = os.path.join(STATE, o.name, "layout")
check("save -L X: writes <state>/X/layout, not <state>/default/layout",
      (rc, [r[1] for r in rows(read(olay))], os.path.exists(os.path.join(STATE, "default"))), (0, ["d"], False))
os.remove(olay)
s.bellhop("save", env=dict(oenv, TMUX=f"{o.socket},{o.pid},0"), input="")
check("save inside X (from $TMUX): the same file", [r[1] for r in rows(read(olay))], ["d"])
o.kill()

# The Claude Code hook's SessionStart saves in the background (autosave on).
BELL_LAYOUT = os.path.join(TMP, "bell", "layout")
s.t("set", "-gu", "@bellhop-autosave")
claude("b:1", "SessionStart", uuid("b1"), BELLHOP_LAYOUT=BELL_LAYOUT)
wait_for(lambda: read(BELL_LAYOUT), "the hook's background save")
check("the hook's SessionStart saves in the background", core(read(BELL_LAYOUT)), want)
s.t("set", "-g", "@bellhop-autosave", "off")
out, rc = bh("save", "--from-hook", env=s.tmux_env(BELLHOP_LAYOUT=os.path.join(TMP, "off", "layout")))
check("save --from-hook with @bellhop-autosave off: exits 0, writes nothing",
      (rc, os.path.exists(os.path.join(TMP, "off"))), (0, False))

# ── 2. "Reboot": the server goes. A save with no server keeps the last good layout. ──
s.kill()
out, rc = bh("save", "-L", s.name, env=s.env)
check("save with no server: exits 0, layout untouched", (rc, read(LAYOUT)), (0, saved))

# The new server already runs b, with the plugin's save hooks live; a's worktree is gone.
start("-s", "b", "-n", "bee-new", "-c", B)
shutil.rmtree(os.path.dirname(WT))
E = s.tmux_env()

before = s.windows()
out, rc = bh("restore", "--dry-run")
lines = out.splitlines()
check("dry-run: exits 0, changes nothing", (rc, s.windows(), read(LAYOUT)), (0, before, saved))
check("dry-run: says when the layout was saved, and that nothing changes",
      (lines[0].startswith("Layout saved "), lines[0].endswith(" (dry run: nothing changes)")), (True, True))
check("dry-run: names the plan",
      [x in out for x in ("  a (slot 0)", "  zz  ", f"claude --resume {uuid('a1')}", f"claude --resume {uuid('a3')}",
                          "left alone: b", "Would start 2 sessions, 4 tabs; 3 Claudes to resume.")], [True] * 6)
m = re.search(r"two +(\S+)", out)
check("dry-run: the gone worktree falls back to the slot folder", m and m.group(1), A)
m = re.search(r"backend +(.*?)  · Claude without a session id: nothing typed$", out, re.M)
check("dry-run: a Claude known only by its title gets nothing typed, and the plan says so", m and m.group(1), Z)
check("dry-run: sessions in map order, off-map sessions after them",
      [l.split()[0] for l in lines if re.match(r"^  \S", l) and "left alone" not in l], ["a", "zz"])

# Tabs opened after a reboot all save at once. Every first save on the new server must
# pass the old layout to .prev, never the new server's.
for trial in range(3):
    ps = [subprocess.Popen([BELLHOP, "save"], env=E, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL) for _ in range(20)]
    for p in ps:
        p.wait(timeout=scaled(60))
    ok = (read(LAYOUT + ".prev"), core(read(LAYOUT))) == (saved, [["1", "b", "1", "bee-new", B, "", "none"]])
    if not ok or trial == 2:
        check("20 saves at once on a new server: the old layout is .prev, the new one is layout", ok, True)
        break
    os.remove(LAYOUT + ".prev")
    write(LAYOUT, saved)

# 20 hook saves in a burst, one per new tab, under every lock backend here: they coalesce
# (fewer snapshots than saves), and the last tab is never lost.
backends = ["mkdir"]
if shutil.which("flock"):
    backends.insert(0, "flock")
if os.access("/usr/bin/lockf", os.X_OK):
    # lockf counts only if its fd mode works here (the probe decides, as in compat.sh)
    r = subprocess.run(["/bin/sh", "-c", 'exec 7>>"$1"; /usr/bin/lockf -t 0 7', "_",
                        os.path.join(TMP, ".lockf-check")], capture_output=True)
    if r.returncode == 0:
        backends.insert(0, "lockf")
print(f"      lock backends here: {', '.join(backends)}", flush=True)
JUNK = tempdir(prefix="bh-junk.")
s.t("set-environment", "-g", "BELLHOP_STATE_DIR", JUNK)       # the plugin's own hook saves go elsewhere
for b in backends:
    root = tempdir(prefix=f"bh-state-{b}.")
    lay = os.path.join(root, s.name, "layout")
    write(lay, saved)
    log = os.path.join(root, "list-panes")
    wrapper = os.path.join(root, "tmux")
    write(wrapper, f'#!/bin/sh\ncase "$*" in *list-panes*) echo x >> "{log}" ;; esac\nexec "{TMUX}" "$@"\n')
    os.chmod(wrapper, 0o755)
    env = dict(E, BELLHOP_STATE_DIR=root, BELLHOP_LOCK=b, BELLHOP_TMUX=wrapper)
    ps = []
    for i in range(20):
        s.t("new-window", "-d", "-t", "b:", "-n", f"w{i}", "-c", B)
        ps.append(subprocess.Popen([BELLHOP, "save", "--from-hook"], env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if i == 0:
            # the rest of the burst comes once the first save is already snapshotting
            wait_for(lambda: read(log), f"the first snapshot ({b})")
    for p in ps:
        p.wait(timeout=scaled(60))
    snaps = len((read(log) or "").splitlines())
    print(f"      {b}: {snaps} snapshots for 20 hook saves", flush=True)
    check(f"20 hook saves in a burst ({b}): every tab saved, the old layout is .prev, they coalesced",
          ([r[3] for r in rows(read(lay))], read(lay + ".prev"), 2 <= snaps < 20),
          (["bee-new"] + [f"w{i}" for i in range(20)], saved, True))
    check(f"20 hook saves in a burst ({b}): nothing left behind (no .pending, no lock dir, no temp file)",
          sorted(os.listdir(os.path.dirname(lay))), ["layout", "layout.lock", "layout.prev"])
    for i in range(20):
        s.t("kill-window", "-t", f"b:w{i}")
s.t("set-environment", "-gu", "BELLHOP_STATE_DIR")

# ── 3. Restore, with no save yet on this server and the hooks re-saving as each tab opens ──
for f in (LAYOUT + ".prev", LAYOUT + ".restored"):
    if os.path.exists(f):
        os.remove(f)
write(LAYOUT, saved)
out, rc = bh("restore", "--yes")
check("restore --yes: exits 0, a and zz back in order with names, b untouched",
      (rc, s.windows()), (0, {"a": ["one", "two", "three"], "b": ["bee-new"], "zz": ["backend"]}))
check("restore: reports b skipped", "left alone: b" in out, True)
check("restore: paths (first tab respawned in its subfolder, gone worktree → slot folder, Claude's split)",
      [at(w, "#{pane_current_path}") for w in ("a:1", "a:2", "a:3", "zz:1")], [SUB, A, OTHER, Z])
check("restore: session folders (new tabs open there): slot folder, else first tab's",
      (at("a:", "#{session_path}"), at("zz:", "#{session_path}")), (A, Z))
for w, sid in (("a:1", uuid("a1")), ("a:2", uuid("a2")), ("a:3", uuid("a3"))):
    check(f"restore: {w} has 'claude --resume <id>' typed", shows(w, f"claude --resume {sid}"), True)
check("restore: the Claude known only by its title gets nothing typed", typed("zz:1"), [])
check("restore: ...and nothing run (fake claude never called)", read(ARGS), None)
check("restore: the summary",
      "Started 2 sessions, 4 tabs. 3 tabs with claude --resume typed: press Enter to resume." in out, True)
wait_for(lambda: sorted(r[1] for r in rows(read(LAYOUT))) == ["a", "a", "a", "b", "zz"], "this server's layout")
check("restore: the pre-reboot layout retired to .restored, layout is this server's",
      (read(LAYOUT + ".restored"), os.path.exists(LAYOUT + ".prev"), header(read(LAYOUT))[5]),
      (saved, False, s.t("display-message", "-p", "#{pid}.#{start_time}")))

# The test presses Enter itself: each typed line runs the (fake) Claude with its id, in its folder.
for w in ("a:1", "a:2", "a:3"):
    s.t("send-keys", "-t", w, "Enter")
wait_for(lambda: (read(ARGS) or "").count("\n") >= 3, "three fake claudes to run")
check("Enter on the typed lines: each Claude resumed with its id in its own folder",
      sorted((read(ARGS) or "").splitlines()),
      sorted([f"--resume {uuid('a1')} @ {SUB}", f"--resume {uuid('a2')} @ {A}", f"--resume {uuid('a3')} @ {OTHER}"]))

# Names are frozen. Where tmux had named the tab, a Claude's title hands naming back to
# tmux; a shell's title does not; a tab named by hand keeps its name for good.
check("names frozen; the thaw hook on tmux-named tabs only",
      (at("a:1", "#{automatic-rename}"), "pane-title-changed" in s.t("show-hooks", "-w", "-t", "a:1"),
       at("zz:1", "#{automatic-rename}"), s.t("show-hooks", "-w", "-t", "zz:1")), ("0", True, "0", ""))
s.t("select-pane", "-t", "a:1", "-T", "user@host:~/src/a")     # what many shells set at every prompt
s.t("select-pane", "-t", "zz:1", "-T", "✳ resumed")            # (hooks run in order: these before a:2's)
s.t("select-pane", "-t", "a:2", "-T", "✳ resumed")
wait_for(lambda: at("a:2", "#{automatic-rename}") == "1", "a:2 automatic-rename back on")
check("a shell title leaves the name alone", (at("a:1", "#{automatic-rename}"), at("a:1", "#W")), ("0", "one"))
check("a hand-named tab keeps its name through a Claude title",
      (at("zz:1", "#{automatic-rename}"), at("zz:1", "#W")), ("0", "backend"))
s.t("select-pane", "-t", "a:1", "-T", "◐ working")
wait_for(lambda: at("a:1", "#{automatic-rename}") == "1", "a:1 automatic-rename back on")
check("a Claude title: automatic-rename on, hook gone, other tabs untouched",
      (s.t("show", "-wv", "-t", "a:1", "automatic-rename"), s.t("show-hooks", "-w", "-t", "a:1"),
       at("a:3", "#{automatic-rename}")), ("on", "", "0"))

# A session closed on purpose after the restore stays closed.
s.t("kill-session", "-t", "zz")
wait_for(lambda: "zz" not in [r[1] for r in rows(read(LAYOUT))], "session-closed save")
out, rc = bh("restore", "--dry-run")
check("restore again after closing zz: nothing to restore", (rc, out.strip().splitlines()[-1]),
      (0, "Nothing to restore."))

# ── 4. The plugin's tmux hooks keep the layout current ─────────────────────────
HOOK_LAYOUT = os.path.join(TMP, "hook", "layout")
s.t("set-environment", "-g", "BELLHOP_LAYOUT", HOOK_LAYOUT)
sessions = lambda: [r[1] for r in rows(read(HOOK_LAYOUT))]
names = lambda: [r[3] for r in rows(read(HOOK_LAYOUT))]
s.t("new-window", "-d", "-t", "b:", "-n", "hooked")
wait_for(lambda: "hooked" in names(), "after-new-window save")
s.t("kill-window", "-t", "b:hooked")
wait_for(lambda: read(HOOK_LAYOUT) and "hooked" not in names(), "window-unlinked save")
s.t("new-session", "-d", "-s", "yy", "-n", "why", "-c", Z)
s.t("new-window", "-d", "-t", "yy:", "-n", "why2")
wait_for(lambda: "yy" in sessions(), "a save that sees yy")
s.t("kill-session", "-t", "yy")
wait_for(lambda: "yy" not in sessions(), "session-closed save")
check("hooks: new tab, closed tab and closed session each re-save", sorted(sessions()), ["a", "a", "a", "b"])
s.t("set-environment", "-gu", "BELLHOP_LAYOUT")

# ── 5. A Claude that ends keeps its id, stamped with when ───────────────────────
# (as at a shutdown, before tmux goes). Restore resumes it when it ended just before the
# last save, not when it ended long before.
claude("b:1", "UserPromptSubmit", uuid("e1"))
bh("save", env=s.tmux_env(BELLHOP_LAYOUT=HOOK_LAYOUT))
claude("b:1", "SessionEnd", uuid("e1"), BELLHOP_LAYOUT=HOOK_LAYOUT)
brow = lambda: [r for r in rows(read(HOOK_LAYOUT)) if r[1] == "b"][0]
wait_for(lambda: brow()[8] != "", "the hook's SessionEnd save")
check("SessionEnd: the id stays, with when it ended",
      (brow()[5], brow()[8].isdigit() and abs(int(brow()[8]) - time.time()) < 120), (uuid("e1"), True))
s.kill()
start("-s", "scratch", "-c", Z)
out, rc = bh("restore", "--dry-run", env=s.tmux_env(BELLHOP_LAYOUT=HOOK_LAYOUT))
check("...and restore resumes it", f"claude --resume {uuid('e1')}" in out, True)
old = read(HOOK_LAYOUT).split("\n")
head = old[0].split()
head[4] = str(int(head[4]) + 1000)                              # a save long after it ended
write(HOOK_LAYOUT, "\n".join([" ".join(head)] + old[1:]))
out, rc = bh("restore", "--dry-run", env=s.tmux_env(BELLHOP_LAYOUT=HOOK_LAYOUT))
check("...but not one closed long before the last save", (uuid("e1") in out, "  b (slot 1)" in out), (False, True))

# ── 6. Names with format sequences come back as written ─────────────────────────
Q = os.path.join(TMP, "q", "layout")
write(Q, f"# bellhop layout 1 {int(time.time())} x\n\tq\t1\t✳ PR #S fix 100%\t{Z}\t\tnone\t\t\t0\n")
out, rc = bh("restore", "--yes", env=s.tmux_env(BELLHOP_LAYOUT=Q))
check("names with # are not expanded", s.windows().get("q"), ["✳ PR #S fix 100%"])
check("one session reads as one; nothing typed, so no resume clause",
      (out.strip().splitlines()[-1], "claude --resume typed" in out), ("Started 1 session, 1 tab.", False))

# ── 7. Plan, then confirm ─────────────────────────────────────────────────────
CF = os.path.join(TMP, "cf", "layout")
write(CF, f"# bellhop layout 1 {int(time.time())} x\n\tcf\t1\tcee\t{Z}\t{uuid('c1')}\tidle\t@90\t\t1\n")
env = s.tmux_env(BELLHOP_LAYOUT=CF)
out, err, rc = s.bellhop("restore", env=env, input="")
check("no terminal and no --yes: exit 2, the plan printed, nothing started",
      (rc, "cf" in s.windows(), "  cf  " in out, "--yes" in err), (2, False, True, True))
out, rc, asked = on_tty(["restore"], env, "n\n")
check("on a terminal, answering n: asks 'Start 1 session, 1 tab? [y/N]', starts nothing, exit 1",
      (asked, "Start 1 session, 1 tab? [y/N]" in out, rc, "cf" in s.windows()), (True, True, 1, False))
out, rc, asked = on_tty(["restore"], env, "y\n")
check("on a terminal, answering y: starts it, types the resume",
      (asked, rc, s.windows().get("cf"), "1 tab with claude --resume typed" in out),
      (True, 0, ["cee"], True))
check("...typed in cf:1", (shows("cf:1", f"claude --resume {uuid('c1')}"), len(typed("cf:1"))), (True, 1))

# ── 8. Only real session ids are typed; claude must be on PATH ──────────────────
PWNED = os.path.join(TMP, "pwned")
BAD = os.path.join(TMP, "bad", "layout")
upper = uuid("d1").upper()
write(BAD, f"# bellhop layout 1 {int(time.time())} x\n"
           f"\tmx\t1\tevil\t{Z}\tx; touch {PWNED}\tidle\t@91\t\t0\n"
           f"\tmx\t2\tshort\t{Z}\tabc\tidle\t@92\t\t0\n"
           f"\tmx\t3\tgood\t{Z}\t{upper}\tidle\t@93\t\t0\n")
out, rc = bh("restore", "--yes", env=s.tmux_env(BELLHOP_LAYOUT=BAD))
good = shows("mx:3", f"claude --resume {upper}")
check("a saved id that is not a session id is never shown or typed; a real one (any case) is",
      (rc, "touch" in out, typed("mx:1"), typed("mx:2"), good),
      (0, False, [], [], True))
s.t("send-keys", "-t", "mx:1", "Enter")
s.t("send-keys", "-t", "mx:2", "Enter")
time.sleep(scaled(0.5))
check("...and pressing Enter there runs nothing", os.path.exists(PWNED), False)

if shutil.which("claude", path="/usr/bin:/bin"):
    skip("claude not on PATH", "a claude in /usr/bin or /bin")
else:
    NC = os.path.join(TMP, "nc", "layout")
    write(NC, f"# bellhop layout 1 {int(time.time())} x\n\tnc\t1\tnope\t{Z}\t{uuid('e2')}\tidle\t@94\t\t0\n")
    out, rc = bh("restore", "--yes", env=s.tmux_env(BELLHOP_LAYOUT=NC, PATH="/usr/bin:/bin"))
    check("claude not on PATH: says so once, types nothing",
          (rc, out.count("claude not found on PATH: nothing typed"), "claude --resume typed" in out,
           s.windows().get("nc"), typed("nc:1")), (0, 1, False, ["nope"], []))

# restore's own save with the mkdir backend (not re-entrant): no self-deadlock, even with
# the hook saves its new tabs fire on the same lock.
MK = os.path.join(TMP, "mk", "layout")
write(MK, f"# bellhop layout 1 {int(time.time())} x\n\tmk\t1\tm1\t{Z}\t\tnone\t@95\t\t1\n"
          f"\tmk\t2\tm2\t{Z}\t\tnone\t@96\t\t1\n\tmk\t3\tm3\t{Z}\t\tnone\t@97\t\t1\n")
s.t("set-environment", "-g", "BELLHOP_LOCK", "mkdir")
s.t("set-environment", "-g", "BELLHOP_LAYOUT", MK)
t0 = time.time()
out, rc = bh("restore", "--yes", env=s.tmux_env(BELLHOP_LAYOUT=MK, BELLHOP_LOCK="mkdir"), timeout=90)
took = time.time() - t0
check("restore with the mkdir lock backend: completes, the tabs are back, the layout saved",
      (rc, s.windows().get("mk"), took < scaled(20), "mk" in [r[1] for r in rows(read(MK))]),
      (0, ["m1", "m2", "m3"], True, True))
wait_for(lambda: not [f for f in os.listdir(os.path.dirname(MK)) if f.endswith((".d", ".pending"))],
         "the hook saves to settle")
check("...and no lock dir is left behind", sorted(os.listdir(os.path.dirname(MK))),
      ["layout", "layout.lock", "layout.restored", "restore.lock"])
s.t("set-environment", "-gu", "BELLHOP_LOCK")
s.t("set-environment", "-gu", "BELLHOP_LAYOUT")

# ── 9. restore -L starts the server itself, per-socket paths, and the server it
#       starts never keeps restore.lock ──
s.kill()
write(LAYOUT, f"# bellhop layout 1 {int(time.time())} x\n\tfresh\t1\tfirst\t{Z}\t{uuid('f2')}\tidle\t@1\t\t0\n"
              f"\tfresh\t2\tsecond\t{A}\t\tnone\t@2\t\t0\n")
for f in (LAYOUT + ".prev", LAYOUT + ".restored"):
    if os.path.exists(f):
        os.remove(f)
out, rc = bh("restore", "--yes", "-L", s.name, env=s.env)
check("restore -L with no server running: starts it, with the saved tabs",
      (rc, s.alive() and s.windows()), (0, {"fresh": ["first", "second"]}))
check("...reads and retires <state>/<socket>/layout",
      (os.path.exists(LAYOUT + ".restored"), [r[1] for r in rows(read(LAYOUT))]), (True, ["fresh", "fresh"]))
out, rc = bh("restore", "--yes", "--socket", s.name, env=s.env, timeout=90)
check("a second restore right after: restore.lock is free (the new server holds no lock fd)",
      (rc, "waiting" in out, out.strip().splitlines()[-1]), (0, False, "Nothing to restore."))
out, rc = bh("restore", "--yes", "-L", s.name, env=dict(s.env, BELLHOP_STATE_DIR=tempdir(prefix="bh-empty.")))
check("nothing saved: exit 1 with the path", (rc, "nothing saved in" in out), (1, True))
out, rc = bh("restore", "--bogus")
check("restore: an unknown flag is a usage error (2)", (rc, "usage: bellhop restore" in out), (2, True))

s.kill()
done()

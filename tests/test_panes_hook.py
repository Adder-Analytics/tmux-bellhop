"""bellhop panes, bellhop jump and bin/bellhop-hook on a throwaway tmux server.

Pane states come the way they do for real: titles as Claude Code sets them, pane
options from the real hook fed hook JSON, bells written to pane ttys.
"""
import json
import os
import shutil
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import (HOOK, REPO, Client, Server, check, done, run, scaled, skip, tempdir,  # noqa: E402
                     uuid, wait_for)

s = Server("panes")
WORK = tempdir(prefix="bh-work.")
MAP = os.path.join(s.home, "map")
with open(MAP, "w") as f:
    f.write("# test map\n0  a  ~\n1  b  ~\n2  c  ~\n3  d  ~\n")
s.env["BELLHOP_MAP"] = MAP

s.start("-s", "a", "-n", "one", "-c", WORK)
s.t("new-window", "-d", "-t", "a:", "-n", "two", "-c", WORK)
s.t("new-session", "-d", "-s", "b", "-n", "bee", "-c", WORK)
s.t("new-session", "-d", "-s", "c", "-n", "sea", "-c", WORK)
s.t("new-session", "-d", "-s", "zz", "-n", "zed", "-c", WORK)

pane = s.pane
opts = lambda p: s.fmt(p, "#{@bellhop_state}|#{@bellhop_since}|#{@bellhop_session}|#{@bellhop_note}")
state = lambda p: opts(p).split("|")[0]
flag = lambda target: s.fmt(target, "#{window_bell_flag}")
sid = lambda p: uuid(f"{int(p.strip('%')) % 256:02x}")


def bell(p, event, env=None, **fields):
    return s.hook(p, event, env=env, session_id=sid(p), cwd=s.home, **fields)


# Titles as Claude Code sets them: ✳ idle, a spinner while working.
s.t("select-pane", "-t", "a:1", "-T", "✳ alpha")
s.t("select-pane", "-t", "a:2", "-T", "◐ beta")
s.t("select-pane", "-t", "b:1", "-T", "✳ gamma")
for target in ("c:1", "zz:1"):
    s.t("select-pane", "-t", target, "-T", "plain shell")

# A client on a, so a bell in a:2 (not current) and in unattached b flags those windows.
c = Client(s, "a")
for target in ("a:2", "b:1"):
    with open(s.fmt(target, "#{pane_tty}"), "w") as f:
        f.write("\a")
wait_for(lambda: flag("a:2") == "1" and flag("b:1") == "1", "bells on a:2 and b:1")

# ── 1. the hook keeps state on the pane ───────────────────────────────────────
c1 = pane("c:1")
out, err, rc = bell(c1, "SessionStart")
check("hook: prints nothing, exits 0", (out, err, rc), ("", "", 0))
check("hook: SessionStart → idle + session id", opts(c1).split("|")[0::2], ["idle", sid(c1)])
bell(c1, "UserPromptSubmit")
check("hook: prompt → working", state(c1), "working")
bell(c1, "Notification", message="Claude needs your permission to use Bash")
check("hook: permission → needs-you with the note", (state(c1), opts(c1).split("|")[3]),
      ("needs-you", "Claude needs your permission to use Bash"))
bell(c1, "Stop")
check("hook: Stop → finished", state(c1), "finished")
bell(c1, "Notification", message="Claude is waiting for your input")
check("hook: waiting-for-input keeps state", state(c1), "finished")
bell(c1, "UserPromptSubmit")
bell(c1, "Notification", notification_type="permission_prompt", message="Claude is waiting for you")
check("hook: notification_type permission_prompt with neutral text → needs-you", state(c1), "needs-you")
bell(c1, "UserPromptSubmit")
bell(c1, "Notification", notification_type="idle_prompt", message="Claude needs your permission to use Bash")
check("hook: another notification_type ignores the text", state(c1), "working")
bell(c1, "Notification", message="x" * 150 + "é" * 150)
check("hook: the note is capped at 200 characters", len(opts(c1).split("|")[3]), 200)
bell(c1, "Notification", message="line one\nline\ttwo")
check("hook: newlines and tabs in the note become spaces", opts(c1).split("|")[3], "line one line two")
zz = pane("zz:1")
bell(zz, "SessionStart")
bell(zz, "SessionEnd")
check("hook: SessionEnd clears everything", opts(zz), "|||")

# Anything that isn't a hook payload: exit 0, no output, nothing changes.
before = opts(c1)
for label, raw in (("garbage", "not json {"), ("empty", ""), ("non-object JSON", "[1, 2]"),
                   ("unknown event", json.dumps({"hook_event_name": "PreToolUse", "session_id": uuid("ff")}))):
    for jq in (None, "/nonexistent"):
        env = s.tmux_env(**({"BELLHOP_JQ": jq} if jq else {}))
        out, err, rc = s.hook(c1, "", env=env, raw=raw)
        check(f"hook: {label} stdin{' (no jq)' if jq else ''} → exit 0, silent, no change",
              (out, err, rc, opts(c1)), ("", "", 0, before))
env = s.tmux_env()
env.pop("TMUX", None)
r = subprocess.run([HOOK], env=env, input=json.dumps({"hook_event_name": "Stop"}), capture_output=True, text=True)
check("hook: no TMUX_PANE (Claude outside tmux) → exit 0, silent", (r.stdout, r.returncode), ("", 0))

# Without jq: the bash parser sets the same state; bells only on Stop and Notification.
s.t("new-session", "-d", "-s", "nj", "-n", "nojq", "-c", WORK)
nj = pane("nj:1")
NOJQ = s.tmux_env(BELLHOP_JQ="/nonexistent")
s.t("select-window", "-t", "nj:1")
bell(nj, "SessionStart", env=NOJQ)
bell(nj, "UserPromptSubmit", env=NOJQ)
time.sleep(0.3)
check("no jq: SessionStart + prompt → working with the id, no bell", (opts(nj).split("|")[0::2], flag("nj:1")),
      (["working", sid(nj)], "0"))
s.hook(nj, "", env=NOJQ, raw=json.dumps({"hook_event_name": "Notification", "session_id": sid(nj),
                                          "message": 'Claude needs your "permission"\\ to use Bash'}))
check("no jq: escaped quotes and backslashes in the note", (state(nj), opts(nj).split("|")[3]),
      ("needs-you", 'Claude needs your "permission"\\ to use Bash'))
bell(nj, "Stop", env=NOJQ)
wait_for(lambda: flag("nj:1") == "1", "the Stop bell without jq")
check("no jq: Stop → finished and the window rang", (state(nj), flag("nj:1")), ("finished", "1"))

HOOKCTL = os.path.join(REPO, "libexec", "bellhop-hookctl")
if os.path.exists(HOOKCTL):
    settings = os.path.join(s.home, "settings.json")
    entry = lambda: {"hooks": [{"type": "command", "timeout": 5,
                                "command": f"test -x '{HOOK}' && '{HOOK}' || true"}]}
    with open(settings, "w") as f:
        json.dump({"hooks": {e: [entry()] for e in
                             ("SessionStart", "UserPromptSubmit", "Notification", "Stop", "SessionEnd")}}, f, indent=2)
    _, _, rc = s.bellhop("hook", "status", "--quiet", env=s.tmux_env(BELLHOP_JQ="/nonexistent",
                                                                     BELLHOP_CLAUDE_SETTINGS=settings))
    check("no jq: hook status --quiet finds five installed entries", rc, 0)
    with open(settings, "w") as f:
        f.write("{}\n")
    _, _, rc = s.bellhop("hook", "status", "--quiet", env=s.tmux_env(BELLHOP_JQ="/nonexistent",
                                                                     BELLHOP_CLAUDE_SETTINGS=settings))
    check("no jq: hook status --quiet fails with nothing installed", rc != 0, True)
else:
    skip("no jq: hook status --quiet", "libexec/bellhop-hookctl is not built yet")

# The detached save: SessionStart and SessionEnd only, and never with autosave off.
# A copy of the hook in a scratch root whose bin/bellhop only records its arguments.
FAKE = tempdir(prefix="bh-fakeroot.")
os.makedirs(os.path.join(FAKE, "bin"))
os.makedirs(os.path.join(FAKE, "lib", "bellhop"))
shutil.copy(HOOK, os.path.join(FAKE, "bin", "bellhop-hook"))
shutil.copy(os.path.join(REPO, "lib", "bellhop", "compat.sh"), os.path.join(FAKE, "lib", "bellhop"))
REC = os.path.join(FAKE, "saves")
with open(os.path.join(FAKE, "bin", "bellhop"), "w") as f:
    f.write(f'#!/bin/sh\necho "$*" >> "{REC}"\n')
os.chmod(os.path.join(FAKE, "bin", "bellhop"), 0o755)
saves = lambda: open(REC).read().splitlines() if os.path.exists(REC) else []


def fake_hook(event):
    e = s.tmux_env(TMUX_PANE=zz)
    subprocess.run([os.path.join(FAKE, "bin", "bellhop-hook")], env=e, capture_output=True, text=True,
                   input=json.dumps({"hook_event_name": event, "session_id": sid(zz)}))


fake_hook("SessionStart")
wait_for(lambda: saves(), "the SessionStart save")
for event in ("UserPromptSubmit", "Stop", "Notification"):
    fake_hook(event)
fake_hook("SessionEnd")
wait_for(lambda: len(saves()) >= 2, "the SessionEnd save")
time.sleep(0.5)
check("hook: `bellhop save --from-hook` on SessionStart and SessionEnd only", saves(),
      ["save --from-hook", "save --from-hook"])
s.t("set-option", "-g", "@bellhop-autosave", "off")
fake_hook("SessionStart")
time.sleep(1)
s.t("set-option", "-gu", "@bellhop-autosave")
check("hook: no save with @bellhop-autosave off", len(saves()), 2)

# Latency: the median of 20 runs (one jq, one tmux, one printf).
lat = []
p = pane("zz:1")
payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": sid(p)})
env = s.tmux_env(TMUX_PANE=p)
for _ in range(20):
    t0 = time.time()
    subprocess.run([HOOK], env=env, input=payload, capture_output=True, text=True)
    lat.append((time.time() - t0) * 1000)
med = statistics.median(lat)
print(f"      hook latency: median {med:.0f} ms over 20 runs (max {max(lat):.0f} ms)")
check("hook: median latency under 250 ms", med < 250 * max(1.0, scaled(1)), True)

# ── 2. bellhop panes classifies ───────────────────────────────────────────────
bell(zz, "SessionStart")
bell(zz, "SessionEnd")
bell(c1, "Notification", message="Claude needs your permission to use Bash")
# (tmux strips a tab from a title or a window name itself; a note is free text.)
s.t("set-option", "-p", "-t", zz, "@bellhop_note", "tab\tin\tnote")
out, err, rc = s.bellhop("panes")
lines = out.split("\n")[:-1]
rows = {r.split("\t")[1] + ":" + r.split("\t")[4]: r.split("\t") for r in lines}
check("panes: exits 0 with 16 columns", (rc, {len(r) for r in rows.values()}), (0, {16}))
cls = {k: v[12] for k, v in rows.items()}
check("panes: idle / working / finished (bell) / needs-you / none",
      (cls["a:1"], cls["a:2"], cls["b:1"], cls["c:1"], cls["zz:1"]),
      ("idle", "working", "finished", "needs-you", "none"))
check("panes: slot column, empty off the map", (rows["a:1"][0], rows["b:1"][0], rows["zz:1"][0]), ("0", "1", ""))
check("panes: a tab inside a note becomes a space, columns hold", rows["zz:1"][15], "tab in note")
check("panes: session id, window id, bell, path",
      (rows["b:1"][2][0], rows["b:1"][3][0], rows["b:1"][6], rows["a:1"][10]), ("$", "@", "1", WORK))

# A braille spinner is working once the hook knows the session; alone it is just a title.
s.t("new-window", "-d", "-t", "zz:", "-n", "br", "-c", WORK)
br = pane("zz:2")
s.t("select-pane", "-t", br, "-T", "⠂ braille spinner title")
row = lambda p: next((l.split("\t") for l in s.bellhop("panes")[0].splitlines() if l.split("\t")[7] == p), None)
check("panes: a braille title without the hook is none", row(br)[12], "none")
bell(br, "SessionStart")
check("panes: a braille title with a hook session is working", row(br)[12], "working")
s.t("select-pane", "-t", br, "-T", "✳ braille spinner title")
check("panes: ✳ with a hook session, no bell, is idle", row(br)[12], "idle")

# --autorename adds the 17th column; a tab named by hand (rename-window, or -n) reads 0.
s.t("new-window", "-d", "-t", "zz:", "-c", WORK)
s.t("new-window", "-d", "-t", "zz:", "-c", WORK)
s.t("rename-window", "-t", "zz:4", "named")
out, _, rc = s.bellhop("panes", "--autorename")
ar = {r.split("\t")[1] + ":" + r.split("\t")[4]: r.split("\t") for r in out.splitlines()}
check("panes --autorename: 17 columns, 1 for auto-named, 0 for renamed or -n",
      (rc, {len(r) for r in ar.values()}, ar["zz:3"][16], ar["zz:4"][16], ar["a:1"][16]), (0, {17}, "1", "0", "0"))

# No map file: running sessions numbered 1-9 then 0 in list-sessions order.
out, _, _ = s.bellhop("panes", env=s.tmux_env(BELLHOP_MAP=os.path.join(s.home, "no-such-map")))
slots = {}
for r in out.splitlines():
    f = r.split("\t")
    slots[f[1]] = f[0]
check("panes without a map: sessions numbered in list-sessions order",
      [slots[k] for k in sorted(slots)], [str(i) for i in range(1, len(slots) + 1)])

# The map file: comments, folders with spaces, ~, bad lines skipped (warned only with --warn).
MAP2 = os.path.join(s.home, "map2")
with open(MAP2, "w") as f:
    f.write("# digit  session  folder\n\n"
            "3  docs   ~/src/team docs  \n"
            "1  api    ~/src/api\n"
            "12 bad    ~\n"
            "2  x.y    ~\n"
            "1  again  ~\n"
            "4  infra\n"
            "5\n"
            "   0  zero  /abs/path\n")


def map_rows(*args):
    return run(["bash", "-c", f'. "{REPO}/lib/bellhop/common.sh"; bh_map_rows "$@"', "_", *args],
               env=dict(s.tmux_env(), BELLHOP_MAP=MAP2))


out, err, rc = map_rows()
H = s.home
check("map: valid lines in digit order, first duplicate wins, ~ expanded, folder keeps spaces",
      (rc, [l.split("\t") for l in out.splitlines()]),
      (0, [["0", "zero", "/abs/path", "1"], ["1", "api", f"{H}/src/api", "1"], ["3", "docs", f"{H}/src/team docs", "1"],
           ["4", "infra", H, "1"]]))
check("map: silent without --warn", err, "")
out, err, rc = map_rows("--warn")
check("map --warn: one line per skipped line (bad digit, bad name, duplicate, no session)",
      [l.split(": ", 1)[0].rsplit(":", 1)[1] for l in err.splitlines()], ["5", "6", "7", "9"])

# ── the dispatcher ────────────────────────────────────────────────────────────
BELLHOP = os.path.join(REPO, "bin", "bellhop")
out, err, rc = run([BELLHOP, "version"], env=s.env)
check("bellhop version prints VERSION", (rc, out), (0, open(os.path.join(REPO, "VERSION")).read()))
out, err, rc = run([BELLHOP, "no-such-command"], env=s.env)
check("bellhop <unknown>: usage on stderr, exit 2", (rc, out, "usage: bellhop" in err), (2, "", True))
out, err, rc = run([BELLHOP], env=s.env)
check("bellhop with no command: usage on stderr, exit 2", (rc, "usage: bellhop" in err), (2, True))
out, err, rc = run([BELLHOP, "help"], env=s.env)
check("bellhop help: usage on stdout, exit 0", (rc, "usage: bellhop" in out), (0, True))
out, err, rc = run([BELLHOP, "help", "panes"], env=s.env)
check("bellhop help panes: the 16 columns", (rc, "slot session session_id" in out), (0, True))
LINK = os.path.join(tempdir(prefix="bh-link."), "bellhop")
os.symlink(BELLHOP, LINK)
out, _, rc = run([LINK, "panes"], env=s.tmux_env())
check("bellhop through a symlink finds its folder", (rc, len(out.splitlines()) > 3), (0, True))
BARE = tempdir(prefix="bh-bare.")
for d in ("bin", "lib"):
    shutil.copytree(os.path.join(REPO, d), os.path.join(BARE, d))
shutil.copy(os.path.join(REPO, "VERSION"), BARE)
for cmd, script in (("inbox", "bellhop-inbox"), ("restore", "bellhop-layout"), ("hook", "bellhop-hookctl"),
                    ("uninstall", "bellhop-setup")):
    out, err, rc = run([os.path.join(BARE, "bin", "bellhop"), cmd], env=s.tmux_env())
    check(f"bellhop {cmd} with libexec/{script} missing: a clear message, exit 2",
          (rc, f"missing libexec/{script}" in err), (2, True))
FAKEX = os.path.join(BARE, "libexec")
os.makedirs(FAKEX)
with open(os.path.join(FAKEX, "bellhop-layout"), "w") as f:
    f.write('#!/usr/bin/env bash\necho "layout $*"\n')
os.chmod(os.path.join(FAKEX, "bellhop-layout"), 0o755)
with open(os.path.join(FAKEX, "bellhop-setup"), "w") as f:          # not executable: run with bash
    f.write('echo "setup $*"\n')
out, _, _ = run([os.path.join(BARE, "bin", "bellhop"), "restore", "--dry-run", "-L", "x"], env=s.tmux_env())
out2, _, _ = run([os.path.join(BARE, "bin", "bellhop"), "unlink"], env=s.tmux_env())
check("bellhop restore / unlink hand the subcommand and flags to libexec", (out, out2),
      ("layout restore --dry-run -L x\n", "setup unlink\n"))

# ── 3. bellhop jump ───────────────────────────────────────────────────────────
win = s.window
_, _, rc = s.bellhop("jump", win("c:1"), "", c.tty)
check("jump: client switched to c", (rc, c.session()), (0, "c"))
s.bellhop("jump", win("a:2"), "", c.tty)
check("jump: back to a, on the second tab", (c.session(), s.fmt("a:", "#{window_index}")), ("a", "2"))
_, _, rc = s.bellhop("jump", win("zz:1"), "", c.tty)
check("jump: a hidden session off the map comes here", (rc, c.session()), (0, "zz"))
s.bellhop("jump", win("a:1"), "", c.tty)

# The focus seam: adapters get <slot> <session> <window-id> when another client shows it.
ADAPT = tempdir(prefix="bh-adapt.")
ARGS = os.path.join(ADAPT, "args")


def adapter(name, body):
    path = os.path.join(ADAPT, name)
    with open(path, "w") as f:
        f.write(f'#!/bin/sh\necho "$# [$1] [$2] [$3] tmux=$BELLHOP_TMUX" >> "{ARGS}"\n{body}\n')
    os.chmod(path, 0o755)
    return path


called = lambda: open(ARGS).read().splitlines() if os.path.exists(ARGS) else []
ok0, fail1, slow = adapter("ok", "exit 0"), adapter("fails", "exit 1"), adapter("slow", "sleep 10")
c2 = Client(s, "b")


def jump(target, adapter_path, use_option=False):
    if os.path.exists(ARGS):
        os.remove(ARGS)
    s.bellhop("jump", win("a:1"), "", c.tty, env=s.tmux_env(BELLHOP_FOCUS_CMD=""))   # start on a
    env = s.tmux_env()
    if use_option:
        env.pop("BELLHOP_FOCUS_CMD")
        s.t("set-option", "-g", "@bellhop-focus-cmd", adapter_path)
    else:
        env["BELLHOP_FOCUS_CMD"] = adapter_path
    t0 = time.time()
    _, err, rc = s.bellhop("jump", win(target), "", c.tty, env=env)
    s.t("set-option", "-gu", "@bellhop-focus-cmd")
    return rc, c.session(), called(), time.time() - t0


rc, where, args, _ = jump("b:1", ok0)
check("focus: exit 0 → the adapter focused it; no switch-client",
      (rc, where, args), (0, "a", [f"3 [1] [b] [{win('b:1')}] tmux={s.env['BELLHOP_TMUX']}"]))
rc, where, args, _ = jump("b:1", ok0, use_option=True)
check("focus: @bellhop-focus-cmd is used when BELLHOP_FOCUS_CMD is unset", (rc, where, len(args)), (0, "a", 1))
s.t("set-option", "-g", "@bellhop-focus-cmd", ok0)
if os.path.exists(ARGS):
    os.remove(ARGS)
s.bellhop("jump", win("b:1"), "", c.tty)            # the harness env has BELLHOP_FOCUS_CMD=''
s.t("set-option", "-gu", "@bellhop-focus-cmd")
check("focus: BELLHOP_FOCUS_CMD='' forces switch-client", (c.session(), called()), ("b", []))
rc, where, args, _ = jump("b:1", fail1)
check("focus: exit 1 → switch-client", (rc, where, len(args)), (0, "b", 1))
rc, where, args, took = jump("b:1", slow)
# (On a loaded machine the adapter may be killed before it logs its call.)
check("focus: a hung adapter is cut off after ~2 s, then switch-client",
      (rc, where, len(args) <= 1, 1.5 < took < scaled(8)), (0, "b", True, True))
rc, where, args, _ = jump("zz:1", ok0)
check("focus: no other client shows the session → no adapter, switch-client", (rc, where, args), (0, "zz", []))
s.t("switch-client", "-c", c2.tty, "-t", "a")          # another client on a as well
rc, where, args, _ = jump("a:2", ok0)
check("focus: the caller is already on that session → no adapter", (rc, where, args), (0, "a", []))
c2.close()

# Outside tmux with no client: a hint and exit 2. With TMUX unset, tmux talks to
# the "default" socket, so this case gets its own server named default, inside
# this test's private TMUX_TMPDIR (never the real one).
DEFAULT = [s.cmd[0], "-L", "default"]
try:
    subprocess.run(DEFAULT + ["-f", "/dev/null", "new-session", "-d", "-s", "zz", "sh"], env=s.env, check=True)
    w = subprocess.run(DEFAULT + ["display-message", "-p", "-t", "zz:", "#{window_id}"], env=s.env,
                       capture_output=True, text=True).stdout.strip()
    env = dict(s.env)
    env.pop("TMUX", None)
    _, err, rc = s.bellhop("jump", w, env=env)
    check("jump: no client and outside tmux → exit 2 with the attach hint",
          (rc, "tmux attach -t '=zz'" in err), (2, True))
finally:
    subprocess.run(DEFAULT + ["kill-server"], env=s.env, capture_output=True)

done()

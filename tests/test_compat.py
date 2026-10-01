"""lib/bellhop/compat.sh (and the small helpers in common.sh) on the host running the tests.

Locks: every backend available here, forced with BELLHOP_LOCK, each on its own
state dir, under 20-way contention; then the unforced probe, which must pick a
backend that really excludes (a waiter still waits while a helper holds the lock).
Also bh_date, bh_locale, bh_realpath, bh_now, bh_watchdog, bh_tmux, the width awk
functions and the preview sanitiser. No tmux server is needed except for the
server-id and `bellhop save` cases.
"""
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import REPO, TMUX, Server, base_env, check, done, run, scaled, skip, tempdir, wait_for  # noqa: E402

COMPAT = os.path.join(REPO, "lib", "bellhop", "compat.sh")
COMMON = os.path.join(REPO, "lib", "bellhop", "common.sh")
WIDTH = os.path.join(REPO, "lib", "bellhop", "width.awk.sh")
BASH = shutil.which("bash")
BASHES = [BASH] + ([b for b in ("/bin/bash",) if os.path.exists(b) and os.path.realpath(b) != os.path.realpath(BASH)])
HOME = tempdir(prefix="bh-home.")
ENV = dict(base_env(), HOME=HOME, XDG_STATE_HOME=os.path.join(HOME, "state"), BELLHOP_TMUX=TMUX)


def bash(script, *args, env=None, lib=COMPAT, shell=None, timeout=60):
    """Run a bash snippet with compat.sh (or common.sh) sourced; (stdout, stderr, rc)."""
    return run([shell or BASH, "-c", f'. "{lib}"\n{script}', "_", *args], env=env or ENV, timeout=timeout)


def popen(script, *args, env=None):
    return subprocess.Popen([BASH, "-c", f'. "{COMPAT}"\n{script}', "_", *args], env=env or ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


# ── locks ─────────────────────────────────────────────────────────────────────
def probe(root):
    out, _, _ = bash("bh_lock_backend", env=dict(ENV, BELLHOP_STATE_DIR=root))
    return out.strip()


backends = ["mkdir"]
if shutil.which("flock"):
    backends.insert(0, "flock")
if os.access("/usr/bin/lockf", os.X_OK):
    # lockf counts only if its fd mode works here (the probe decides, as in compat.sh)
    out, _, rc = run(["/bin/sh", "-c", 'f=$1; exec 7>>"$f"; /usr/bin/lockf -t 0 7', "_",
                      os.path.join(HOME, ".lockf-check")])
    if rc == 0:
        backends.insert(0, "lockf")
print(f"      lock backends available here: {', '.join(backends)}")

# A worker: take the lock, read-increment-write a counter slowly, log in/out.
WORKER = r'''
D=$1 style=$2
F=$D/test.lock
if [ "$style" = open ]; then bh_lock_open 9 "$F" || exit 4; bh_lock 9 60 || exit 3
else exec 9>>"$F"; bh_lock 9 60 "$F" || exit 3; fi
echo "in $$" >>"$D/log"
n=$(cat "$D/count" 2>/dev/null || echo 0)
sleep 0.05
echo $((n + 1)) >"$D/count"
echo "out $$" >>"$D/log"
bh_unlock 9 "$F"
'''

# A holder: $1 the lock file, $2 a dir for the held / release signals.
HOLDER = r'''
bh_lock_open 9 "$1"
bh_lock 9 10 || exit 3
: >"$2/held"
while [ ! -e "$2/release" ]; do sleep 0.05; done
bh_unlock 9
'''

for b in backends:
    root = tempdir(prefix=f"bh-lock-{b}.")
    env = dict(ENV, BELLHOP_STATE_DIR=root, BELLHOP_LOCK=b)
    ps = [popen(WORKER, root, "open" if i % 2 else "file", env=env) for i in range(20)]
    rcs = [p.wait(timeout=scaled(120)) for p in ps]
    log = open(os.path.join(root, "log")).read().split("\n")[:-1]
    paired = all(log[i].split()[0] == "in" and log[i + 1] == "out " + log[i].split()[1] for i in range(0, len(log), 2))
    check(f"lock {b}: 20 processes at once all get the lock, one at a time",
          (rcs, open(os.path.join(root, "count")).read().strip(), len(log), paired), ([0] * 20, "20", 40, True))
    check(f"lock {b}: forcing a backend writes no cache", os.path.exists(os.path.join(root, "lock-backend")), False)
    check(f"lock {b}: nothing left behind (no .d dir, no probe file)",
          sorted(f for f in os.listdir(root) if f not in ("log", "count")), ["test.lock"])

    # While a holder has it: bh_lock_nb fails at once, bh_lock gives up after its timeout.
    h = popen(HOLDER, os.path.join(root, "test.lock"), root, env=env)
    wait_for(lambda: os.path.exists(os.path.join(root, "held")), f"{b} holder")
    t0 = time.time()
    _, _, rc_nb = bash('bh_lock_open 9 "$1/test.lock"; bh_lock_nb 9', root, env=env)
    t1 = time.time()
    _, _, rc_to = bash('bh_lock_open 9 "$1/test.lock"; bh_lock 9 1', root, env=env)
    t2 = time.time()
    check(f"lock {b}: held → bh_lock_nb fails at once, bh_lock 1 s gives up after ~1 s",
          (rc_nb != 0, t1 - t0 < scaled(1.5), rc_to != 0, 0.8 < t2 - t1 < scaled(4)), (True, True, True, True))
    open(os.path.join(root, "release"), "w").close()
    h.wait(timeout=scaled(10))
    _, _, rc = bash('bh_lock_open 9 "$1/test.lock"; bh_lock_nb 9 && bh_unlock 9', root, env=env)
    check(f"lock {b}: released → bh_lock_nb succeeds", (h.returncode, rc), (0, 0))

# mkdir specifics: a dead holder's lock is taken over; the EXIT trap releases; a
# caller's own EXIT trap is kept; the file behind an fd is found without being told.
root = tempdir(prefix="bh-lock-mkdir2.")
env = dict(ENV, BELLHOP_STATE_DIR=root, BELLHOP_LOCK="mkdir")
F = os.path.join(root, "x.lock")
dead = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
dead.wait()
os.makedirs(F + ".d")
with open(os.path.join(F + ".d", "pid"), "w") as f:
    f.write(f"{dead.pid}\n")
out, _, rc = bash('bh_lock_open 9 "$1"; bh_lock_nb 9 && cat "$1.d/pid" && echo "$$"', F, env=env)
got = out.split()
check("mkdir: a lock whose holder is gone is taken over", (rc, len(got) == 2 and got[0] == got[1]), (0, True))
check("mkdir: the EXIT trap removed it when the holder exited", os.path.exists(F + ".d"), False)
out, _, rc = bash('trap "echo caller-trap" EXIT; bh_lock_open 9 "$1"; bh_lock_nb 9; echo got-it', F, env=env)
check("mkdir: a caller's own EXIT trap is kept", (rc, out.split()), (0, ["got-it", "caller-trap"]))
out, _, rc = bash('bh_lock_nb 9 "$1" && echo ok', F, env=env)
check("mkdir: ...and its lock (dead holder) is taken over by the next process", (rc, out.strip()), (0, "ok"))
out, _, rc = bash('exec 9>>"$1"; bh_lock 9 2 && echo ok && [ -d "$1.d" ] && bh_unlock 9 && [ ! -d "$1.d" ] && echo released',
                  F, env=env)
check("mkdir: bh_lock FD with no file named finds it from the fd", (rc, out.split()), (0, ["ok", "released"]))

# The same primitives under every bash here (the floor is 3.2): hold, exclude, release.
EXCLUDE = r'''
bh_lock_open 9 "$1" && bh_lock 9 2 || exit 3
( bh_lock_open 8 "$1"; if bh_lock_nb 8; then echo not-excluded; else echo excluded; fi )
bh_unlock 9
( bh_lock_open 8 "$1"; if bh_lock_nb 8; then echo free; bh_unlock 8; else echo stuck; fi )
'''
for sh in BASHES:
    for b in backends:
        root = tempdir(prefix=f"bh-lock-sh-{b}.")
        out, _, rc = bash(EXCLUDE, os.path.join(root, "x.lock"), env=dict(ENV, BELLHOP_STATE_DIR=root, BELLHOP_LOCK=b),
                          shell=sh)
        check(f"lock {b} under {'bash on PATH' if sh == BASH else sh}: held excludes a second open, released is free", (rc, out.split()),
              (0, ["excluded", "free"]))

# The unforced probe: picks one backend per state root, caches it, and that backend excludes.
root = tempdir(prefix="bh-lock-probe.")
env = {k: v for k, v in dict(ENV, BELLHOP_STATE_DIR=root).items() if k != "BELLHOP_LOCK"}
picked = probe(root)
cache = os.path.join(root, "lock-backend")
print(f"      the probe picked: {picked}")
check("probe: picks an available backend and caches it",
      (picked in backends, open(cache).read().strip() if os.path.exists(cache) else None), (True, picked))
check("probe: leaves no probe file behind", [f for f in os.listdir(root) if f.startswith(".lockprobe")], [])
before = open(cache).read()
h = popen(HOLDER, os.path.join(root, "layout.lock"), root, env=env)
wait_for(lambda: os.path.exists(os.path.join(root, "held")), "the probe-backend holder")
w = popen('bh_lock_open 9 "$1/layout.lock"; bh_lock 9 10 && echo got', root, env=env)
time.sleep(1)
waiting = w.poll() is None
open(os.path.join(root, "release"), "w").close()
out, _ = w.communicate(timeout=scaled(15))
check(f"probe ({picked}): a waiter is still waiting after 1 s, and gets the lock once released",
      (waiting, w.returncode, out.strip(), h.wait(timeout=scaled(10))), (True, 0, "got", 0))
check("probe: lock-backend is the same before and after", open(cache).read(), before)
with open(cache, "w") as f:
    f.write("bogus\n")
check("probe: an unusable cached value is replaced", (probe(root), open(cache).read().strip()), (picked, picked))

LAYOUT = os.path.join(REPO, "libexec", "bellhop-layout")
if os.path.exists(LAYOUT):
    # The same with a real `bellhop save`: it must wait while layout.lock is held.
    srv = Server("compat")
    root = os.path.join(srv.home, "state")
    srv.env["BELLHOP_STATE_DIR"] = root
    srv.env.pop("BELLHOP_LOCK", None)
    srv.start("-s", "a", "-n", "one")
    sock = os.path.basename(srv.socket)
    os.makedirs(os.path.join(root, sock), exist_ok=True)
    env = srv.tmux_env()
    h = popen(HOLDER, os.path.join(root, sock, "layout.lock"), srv.home, env=env)
    wait_for(lambda: os.path.exists(os.path.join(srv.home, "held")), "the layout.lock holder")
    before = open(os.path.join(root, "lock-backend")).read()
    sv = subprocess.Popen([os.path.join(REPO, "bin", "bellhop"), "save"], env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    waiting = sv.poll() is None
    open(os.path.join(srv.home, "release"), "w").close()
    rc = sv.wait(timeout=scaled(20))
    check("probe + `bellhop save`: a plain save waits for a held layout.lock, then saves",
          (waiting, rc, os.path.exists(os.path.join(root, sock, "layout")), h.wait(timeout=scaled(10))),
          (True, 0, True, 0))
    check("probe + `bellhop save`: lock-backend unchanged", open(os.path.join(root, "lock-backend")).read(), before)
    srv.kill()
else:
    skip("probe + `bellhop save` contention", "libexec/bellhop-layout is not built yet (test_layout covers saves)")

# ── time, locale, paths, watchdog, tmux ────────────────────────────────────────
for sh in BASHES:
    tag = "" if sh == BASH else f" ({sh})"
    out, _, rc = bash('bh_date 1767225600 "%a %-d %b %H:%M"; bh_date 1767225600 "+%Y-%m-%d"; bh_date 0 "%H:%M"',
                      env=dict(ENV, TZ="UTC"), shell=sh)
    check(f"bh_date: GNU or BSD date, with or without +{tag}", (rc, out.splitlines()),
          (0, ["Thu 1 Jan 00:00", "2026-01-01", "00:00"]))
    out, _, _ = bash("bh_now; BELLHOP_NOW=1767225600 bh_now", shell=sh)
    now, pinned = out.split()
    check(f"bh_now: the clock, or BELLHOP_NOW{tag}", (abs(int(now) - time.time()) < 60, pinned), (True, "1767225600"))

locales = run(["locale", "-a"])[0].split()
utf8 = [l for l in locales if l.lower().replace("-", "") in ("c.utf8", "en_us.utf8")]
if utf8:
    for sh in BASHES:
        tag = "" if sh == BASH else f" ({sh})"
        e = {k: v for k, v in ENV.items() if not k.startswith("LC_")}
        e.update(LANG="C", LC_ALL="", LC_CTYPE="")
        out, _, rc = bash('bh_locale; echo "rc=$? LC_CTYPE=${LC_CTYPE:-} LC_ALL=${LC_ALL-unset}"', env=e, shell=sh)
        got = dict(kv.split("=", 1) for kv in out.split())
        check(f"bh_locale: LANG=C → a UTF-8 LC_CTYPE spelled as `locale -a` prints it{tag}",
              (got["rc"], got["LC_CTYPE"] in locales, "utf" in got["LC_CTYPE"].lower()), ("0", True, True))
        e["LC_ALL"] = "C"
        out, _, _ = bash('bh_locale; echo "LC_ALL=${LC_ALL-unset}"', env=e, shell=sh)
        check(f"bh_locale: a non-UTF-8 LC_ALL is dropped{tag}", out.strip(), "LC_ALL=unset")
    e = dict(ENV, LC_ALL="", LANG="en_US.UTF-8", LC_CTYPE="")
    out, _, _ = bash('bh_locale; echo "LC_CTYPE=${LC_CTYPE:-}"', env=e)
    check("bh_locale: an effective UTF-8 locale is left alone", out.strip(), "LC_CTYPE=")
else:
    skip("bh_locale", "this system lists no C.UTF-8 or en_US.UTF-8 locale")

P = tempdir(prefix="bh-paths.")
os.makedirs(os.path.join(P, "real", "sub"))
open(os.path.join(P, "real", "sub", "file"), "w").close()
os.symlink("real", os.path.join(P, "rel"))
os.symlink(os.path.join(P, "rel", "sub"), os.path.join(P, "abs"))
os.symlink("abs/file", os.path.join(P, "chain"))
for sh in BASHES:
    tag = "" if sh == BASH else f" ({sh})"
    out, _, rc = bash('for p; do bh_realpath "$p"; done', os.path.join(P, "chain"), os.path.join(P, "rel"),
                      os.path.join(P, "abs", "missing"), P + "/rel/../real", shell=sh)
    check(f"bh_realpath: symlink chains, relative links, a missing last part{tag}", (rc, out.splitlines()),
          (0, [f"{P}/real/sub/file", f"{P}/real", f"{P}/real/sub/missing", f"{P}/real"]))

t0 = time.time()
out, _, rc = bash('bh_watchdog 1 sleep 10; echo "rc=$?"; bh_watchdog 5 sh -c "exit 7"; echo "rc=$?"')
check("bh_watchdog: a hung command is killed after SECS (124); a quick one keeps its status",
      (out.split(), time.time() - t0 < scaled(6)), (["rc=124", "rc=7"], True))

fake = os.path.join(P, "my-tmux")
with open(fake, "w") as f:
    f.write("#!/bin/sh\necho fake\n")
os.chmod(fake, 0o755)
out, _, _ = bash('echo "$TMUX_BIN"; tmux', env=dict(ENV, BELLHOP_TMUX=fake))
check("bh_tmux: BELLHOP_TMUX wins, and tmux() calls it", out.split(), [fake, "fake"])
out, _, _ = bash('echo "$TMUX_BIN"', env={k: v for k, v in ENV.items() if k != "BELLHOP_TMUX"})
check("bh_tmux: else tmux from PATH", out.strip(), shutil.which("tmux", path=ENV["PATH"]))
srv = Server("compat-id", conf=None).start("-s", "a")
out, _, _ = bash("bh_server_id", env=srv.tmux_env())
check("bh_server_id: <pid>.<start_time> from tmux formats", out.strip(),
      srv.t("display-message", "-p", "#{pid}.#{start_time}"))
srv.kill()

# ── width awk: ulen / cut / pad count UTF-8 characters in byte-mode awk ────────
PROG = r'''{ printf "%d|%s|%s|\n", ulen($0), cut($0, 5), pad($0, 6) }'''
INPUTS = "abc\n✳ Fix it\nhéllo wörld\n◐◓◑◒ spin\n\n1234567\n"
# pad(s, 6): cut to 6 characters, then spaces to 6, then one more (the column gap)
WANT = ["3|abc|abc    |", "8|✳ Fi…|✳ Fix… |", "11|héll…|héllo… |", "9|◐◓◑◒…|◐◓◑◒ … |", "0||       |",
        "7|1234…|12345… |"]
awks = []
for name in ("awk", "mawk", "gawk", "original-awk", "nawk", "busybox"):
    path = shutil.which(name)
    if path and os.path.realpath(path) not in [os.path.realpath(a[1]) for a in awks]:
        awks.append((name, path))
results = {}
for name, path in awks:
    cmd = [path] + (["awk"] if name == "busybox" else [])
    out, err, rc = run(["bash", "-c", f'. "{WIDTH}"; LC_ALL=C "$@" "$BH_AWK_WIDTH$PROG"', "_", *cmd], input=INPUTS,
                       env=dict(ENV, PROG=PROG))
    results[name] = out.splitlines()
    check(f"width awk ({name}): ulen / cut / pad in characters, … when cut", (rc, results[name]), (0, WANT))
if len(results) > 1:
    check("width awk: every dialect here gives the same text", len({tuple(v) for v in results.values()}), 1)
else:
    skip("width awk dialect comparison", f"only one awk here ({awks[0][0]}); mawk and gawk run in CI")

# ── common.sh helpers: sanitiser, badges, text ─────────────────────────────────
ESC = "\x1b"
dirty = (f"a{ESC}]52;c;c2VjcmV0{ESC}\\b{ESC}]2;title\x07c{ESC}[31mred{ESC}[0m{ESC}[2J{ESC}[?25l{ESC}[3;5H"
         f"{ESC}(Bd\x01\x08e\tf\r\n{ESC}[1;38;5;214mkeep{ESC}[0m\n\n   \n")
p = subprocess.run([BASH, "-c", f'. "{COMMON}"; bh_sanitize'], input=dirty.encode(), capture_output=True, env=ENV)
check("bh_sanitize: OSC 52 and OSC 2 gone, CSI moves gone, controls gone, SGR and tabs kept, blank tail trimmed",
      p.stdout.decode(), f"abc{ESC}[31mred{ESC}[0mde\tf\n{ESC}[1;38;5;214mkeep{ESC}[0m\n")
p = subprocess.run([BASH, "-c", f'. "{COMMON}"; bh_sanitize'], input=("".join(f"{i}\n" for i in range(100))).encode(),
                   capture_output=True, env=dict(ENV, FZF_PREVIEW_LINES="3"))
check("bh_sanitize: keeps the last FZF_PREVIEW_LINES lines", p.stdout.decode(), "97\n98\n99\n")
out, _, _ = bash('for s in needs-you finished working idle none; do bh_badge "$s"; done; plural 1 tab; plural 3 tab; '
                 'tildify "$HOME/src/a"; echo; tildify "${HOME}x"; echo; session_name "/x/my.app: v2"',
                 lib=COMMON)
check("common: one badge palette; plural, tildify, session_name", out.splitlines(),
      ["1;31", "38;5;214", "34", "2", "0", "1 tab", "3 tabs", "~/src/a", HOME + "x", "my_app__v2"])

done()

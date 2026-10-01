"""Shared test harness: throwaway tmux servers, pty clients, process waits.

Nothing here can touch your tmux server or your HOME:
- every Server has its own socket name (-L bellhop-test-<name>-<pid>) in its own
  TMUX_TMPDIR (a short dir under /tmp, for the 104-byte socket path limit on macOS);
- every process it starts (the server, clients, bellhop itself) gets a temp HOME,
  XDG_CONFIG_HOME and XDG_STATE_HOME, and no TMUX / TMUX_PANE from the caller;
- atexit kills every server and removes every temp dir, pass or fail.

Waits are on processes and drawn text (wait_for), never fixed sleeps. Every timeout
is multiplied by BELLHOP_TEST_TIMEOUT_SCALE (CI sets 2 on macOS).
Python >= 3.9.
"""
import atexit
import fcntl
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BELLHOP = os.path.join(REPO, "bin", "bellhop")
HOOK = os.path.join(REPO, "bin", "bellhop-hook")
FIXTURE = os.path.join(REPO, "tests", "fixtures", "tmux.conf")
ARTIFACTS = os.path.join(REPO, "tests", ".artifacts")
SCALE = float(os.environ.get("BELLHOP_TEST_TIMEOUT_SCALE") or 1)
TMUX = os.environ.get("BELLHOP_TMUX") or shutil.which("tmux")
if not TMUX:
    sys.exit("tests need tmux on PATH (or BELLHOP_TMUX)")
TMUX = os.path.realpath(TMUX)

ENTER, ESC, TAB = "\r", "\x1b", "\t"
CTRL = {c: chr(ord(c) - 96) for c in "abcdefghijklmnopqrstuvwxyz"}   # CTRL["b"] == "\x02"

_servers = []
_tempdirs = []
_clients = []


def scaled(seconds):
    return seconds * SCALE


def tempdir(prefix="bh-", base=None):
    """A temp dir removed at exit; realpath, since panes report /private/var/… on macOS."""
    d = os.path.realpath(tempfile.mkdtemp(prefix=prefix, dir=base))
    _tempdirs.append(d)
    return d


def _on_term(signum, frame):
    sys.exit(128 + signum)                     # run the atexit cleanup when run.sh's watchdog kills us


signal.signal(signal.SIGTERM, _on_term)


@atexit.register
def _cleanup():
    for c in _clients:
        c.close()
    for s in _servers:
        s.kill()
    for d in _tempdirs:
        shutil.rmtree(d, ignore_errors=True)


# ── results ──────────────────────────────────────────────────────────────────
fails = 0


def check(name, got, want):
    """One PASS/FAIL line; the got/want diff under a FAIL."""
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n      got  {got!r}\n      want {want!r}"), flush=True)
    return ok


def skip(name, why):
    print(f"SKIP  {name}: {why}", flush=True)


def done():
    """Print the summary and exit with the number of failures (capped at 1 for the shell)."""
    print(f"\nfailures: {fails}", flush=True)
    sys.exit(1 if fails else 0)


def wait_for(pred, what, timeout=25):
    """Poll pred every 0.1 s until it returns something truthy; return that."""
    t0 = time.time()
    limit = scaled(timeout)
    while time.time() - t0 < limit:
        v = pred()
        if v:
            return v
        time.sleep(0.1)
    raise RuntimeError(f"timed out after {limit:.0f}s waiting for {what}")


# ── processes ────────────────────────────────────────────────────────────────
def procs():
    """{pid: (ppid, args)} for every process (portable ps flags)."""
    out = subprocess.run(["ps", "-ww", "-eo", "pid=,ppid=,args="], capture_output=True, text=True).stdout
    d = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            d[parts[0]] = (parts[1], parts[2])
    return d


FZF_NAMES = {"fzf", os.path.basename(os.environ.get("BELLHOP_FZF") or "fzf")}
PICK = re.compile(r"libexec/bellhop-(inbox|find|move) --pick ")


def _is_fzf(args):
    first = args.split(None, 1)[0] if args else ""
    return os.path.basename(first) in FZF_NAMES


def fzf_of(tty, tool=None):
    """The pid of the fzf a popup on this client is showing, or None.

    Its parent (or grandparent: fzf runs from a command substitution) is
    `libexec/bellhop-<tool> --pick <tty> …`."""
    d = procs()
    for pid, (ppid, args) in d.items():
        if not _is_fzf(args):
            continue
        p = ppid
        for _ in range(3):
            if p not in d:
                break
            m = PICK.search(d[p][1])
            if m and f"--pick {tty} " in d[p][1] + " " and (tool is None or m.group(1) == tool):
                return pid
            p = d[p][0]
    return None


def popup_open(tty, tool=None):
    """True while any `libexec/bellhop-<tool> --pick <tty>` process lives."""
    for _, args in procs().values():
        m = PICK.search(args)
        if m and f"--pick {tty} " in args + " " and (tool is None or m.group(1) == tool):
            return True
    return False


# ── servers ──────────────────────────────────────────────────────────────────
def base_env():
    """The caller's environment minus anything that could reach a real server or config."""
    drop = ("TMUX", "TMUX_PANE", "TMUX_TMPDIR", "FZF_DEFAULT_OPTS", "FZF_DEFAULT_OPTS_FILE", "ENV", "BASH_ENV",
            "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME")
    env = {k: v for k, v in os.environ.items() if k not in drop and not k.startswith(("BELLHOP_", "WS_"))}
    env["TERM"] = "xterm-256color"
    for k in ("BELLHOP_TEST_TIMEOUT_SCALE", "BELLHOP_FZF"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


class Server:
    """A throwaway tmux server: unique socket, temp HOME/XDG, short TMUX_TMPDIR."""

    def __init__(self, name, conf=FIXTURE, env=None):
        self.name = f"bellhop-test-{name}-{os.getpid()}"
        self.tmpdir = tempdir(prefix="bh.", base="/tmp")          # sockets: keep the path short
        self.home = tempdir(prefix="bh-home.")
        self.conf = conf
        e = base_env()
        e.update(HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                 XDG_STATE_HOME=os.path.join(self.home, ".local", "state"), TMUX_TMPDIR=self.tmpdir,
                 BELLHOP_TMUX=TMUX, BELLHOP_ROOT=REPO, BELLHOP_FOCUS_CMD="", SHELL="/bin/sh")
        e.update(env or {})
        self.env = e
        self.cmd = [TMUX, "-L", self.name]
        self._pid = None
        _servers.append(self)

    # tmux against this server; raises on failure unless check=False
    def t(self, *args, check=True, env=None, timeout=20):
        r = subprocess.run(self.cmd + list(args), env=env or self.env, capture_output=True, text=True,
                           timeout=scaled(timeout))
        if check and r.returncode:
            raise RuntimeError(f"tmux {args}: {r.stderr.strip()}")
        return r.stdout.rstrip("\n")

    def start(self, *first_session):
        """Start the server with the fixture config (or conf=None → -f /dev/null) and one session."""
        self.kill()
        conf = self.conf or "/dev/null"
        args = list(first_session) or ["-s", "a", "-n", "one"]
        self.t("-f", conf, "new-session", "-d", "-x", "120", "-y", "40", *args)
        self._pid = None
        if self.conf == FIXTURE:
            wait_for(lambda: self.t("show-options", "-gqv", "@bellhop-root", check=False), "the plugin to load")
        return self

    def alive(self):
        return subprocess.run(self.cmd + ["has-session"], env=self.env, capture_output=True).returncode == 0

    def kill(self):
        subprocess.run(self.cmd + ["kill-server"], env=self.env, capture_output=True)
        self._pid = None

    @property
    def socket(self):
        return self.t("display-message", "-p", "#{socket_path}")

    @property
    def pid(self):
        if not self._pid:
            self._pid = self.t("display-message", "-p", "#{pid}")
        return self._pid

    def tmux_env(self, **extra):
        """The env of a script run "inside" this server: TMUX names its socket and real pid."""
        e = dict(self.env, TMUX=f"{self.socket},{self.pid},0")
        e.update(extra)
        return e

    def bellhop(self, *args, env=None, input=None, timeout=30):
        """Run bin/bellhop inside this server; (stdout, stderr, returncode)."""
        r = subprocess.run([BELLHOP, *args], env=env or self.tmux_env(), capture_output=True, text=True,
                           input=input, timeout=scaled(timeout))
        return r.stdout, r.stderr, r.returncode

    def hook(self, pane, event, env=None, raw=None, **fields):
        """Feed bin/bellhop-hook one Claude Code hook payload for a pane, as Claude Code would."""
        import json
        payload = raw if raw is not None else json.dumps(dict(hook_event_name=event, **fields))
        e = dict(env or self.tmux_env(), TMUX_PANE=pane)
        r = subprocess.run([HOOK], env=e, input=payload, capture_output=True, text=True, timeout=scaled(20))
        return r.stdout, r.stderr, r.returncode

    def pane(self, target):
        return self.t("display-message", "-p", "-t", target, "#{pane_id}")

    def window(self, target):
        return self.t("display-message", "-p", "-t", target, "#{window_id}")

    def fmt(self, target, f):
        return self.t("display-message", "-p", "-t", target, f)

    def windows(self):
        """{session: [window names in order]}."""
        d = {}
        for line in self.t("list-windows", "-a", "-F", "#{session_name}\t#{window_name}").splitlines():
            s, n = line.split("\t", 1)
            d.setdefault(s, []).append(n)
        return d

    def dump(self, label):
        """Save messages and every pane's screen under tests/.artifacts/ (for CI failures)."""
        try:
            os.makedirs(ARTIFACTS, exist_ok=True)
            path = os.path.join(ARTIFACTS, f"{label}-{self.name}.txt")
            with open(path, "w") as f:
                f.write(self.t("show-messages", check=False) + "\n")
                for p in self.t("list-panes", "-a", "-F", "#{pane_id} #{session_name}:#{window_index}",
                                check=False).splitlines():
                    pid = p.split()[0]
                    f.write(f"\n=== {p}\n" + self.t("capture-pane", "-p", "-t", pid, check=False) + "\n")
        except Exception:
            pass


# ── clients ──────────────────────────────────────────────────────────────────
def _make_ctty():
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class Client:
    """A real tmux client on a pty (os.openpty; no pty.fork, no os.ptsname)."""

    def __init__(self, server, session, cols=120, rows=40):
        self.server = server
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.tty = os.ttyname(slave)
        self.fd = master
        self.proc = subprocess.Popen(server.cmd + ["attach", "-t", session], stdin=slave, stdout=slave,
                                     stderr=slave, env=server.env, start_new_session=True,
                                     preexec_fn=_make_ctty, close_fds=True)
        os.close(slave)
        self.buf = b""
        self._closed = False
        threading.Thread(target=self._drain, daemon=True).start()
        _clients.append(self)
        wait_for(lambda: self.tty in server.t("list-clients", "-F", "#{client_name}", check=False).split("\n"),
                 "client attach")

    def _drain(self):
        try:
            while True:
                chunk = os.read(self.fd, 65536)
                if not chunk:
                    break
                self.buf += chunk
        except OSError:
            pass

    def keys(self, *seq, gap=0.25):
        for k in seq:
            os.write(self.fd, k.encode())
            time.sleep(gap)

    def where(self):
        """(session, window index, pane id) this client is looking at."""
        for line in self.server.t("list-clients", "-F",
                                  "#{client_name}\t#{session_name}\t#{window_index}\t#{pane_id}").splitlines():
            name, *rest = line.split("\t")
            if name == self.tty:
                return tuple(rest)
        return None

    def session(self):
        w = self.where()
        return w[0] if w else None

    def alive(self):
        return self.proc.poll() is None

    def text(self, since=0):
        """What was drawn since a buffer offset: colours dropped, cursor moves as line breaks."""
        raw = self.buf[since:].decode("utf-8", "replace")
        raw = re.sub(r"\x1b\[[0-9;:?]*m", "", raw)
        raw = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "\n", raw)
        raw = re.sub(r"\x1b[^\x1b]{0,2}", "", raw)
        return [line.strip() for line in raw.split("\n") if line.strip()]

    def wait_prompt(self, since=0, prompt="›"):
        """Wait until fzf has drawn its prompt (so keys reach fzf, not the pane).

        text() strips each line, and an empty query leaves the prompt at the end
        of its line, so the default is the bare "›" with no trailing space."""
        return wait_for(lambda: any(prompt in line for line in self.text(since)), f"prompt {prompt!r} drawn")

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.proc.poll() is None:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=5)
        except Exception:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


def uuid(suffix):
    """The only session ids tests use: 00000000-0000-4000-8000-0000000000NN."""
    return f"00000000-0000-4000-8000-0000000000{suffix}"


def run(cmd, env=None, input=None, timeout=30, cwd=None):
    """subprocess.run with text output and a scaled timeout; (stdout, stderr, rc)."""
    r = subprocess.run(cmd, env=env, input=input, capture_output=True, text=True, timeout=scaled(timeout), cwd=cwd)
    return r.stdout, r.stderr, r.returncode

"""The admin commands on throwaway tmux servers: bellhop map, bellhop doctor
(--ci and full), bellhop link / unlink, and bellhop uninstall end to end
(settings entries, link, keys and save hooks off the running server)."""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import BELLHOP, REPO, Server, base_env, check, done, run, tempdir  # noqa: E402

PLUGIN = os.path.join(REPO, "bellhop.tmux")
ROOT = os.path.realpath(REPO)
BIN = os.path.join(ROOT, "bin", "bellhop")
# How tildify shows ROOT: where /tmp links to /private/tmp (macOS), as /tmp/….
SHOWN_ROOT = ROOT
if ROOT.startswith("/private/tmp/") and os.path.samefile("/tmp", "/private/tmp"):
    SHOWN_ROOT = ROOT[len("/private"):]


def keyline(s, key):
    for line in s.t("list-keys", "-T", "prefix").splitlines():
        f = line.split()
        i = 4 if len(f) > 4 and f[1] == "-r" else 3
        if len(f) > i and f[i] == key:
            return line
    return ""


def lines(out, status):
    """The check lines of doctor output with that status, without the status word."""
    return [l[6:] for l in out.splitlines() if l.startswith(status + " ")]


def fixes(out):
    return [l.strip()[5:] for l in out.splitlines() if l.startswith("      fix: ")]


# ── 1. bellhop map ────────────────────────────────────────────────────────────
s = Server("admin")
H = s.home
os.makedirs(os.path.join(H, "src", "api"))
os.makedirs(os.path.join(H, "src", "team docs"))
s.start("-s", "a", "-n", "one", "-c", H)
s.t("new-session", "-d", "-s", "b", "-c", os.path.join(H, "src", "api"))
s.t("new-window", "-d", "-t", "b:")
MAP = os.path.join(H, ".config", "bellhop", "map")


def bh(*args, env=None, cwd=None, input=""):
    return run([BELLHOP, *args], env=env or s.tmux_env(), cwd=cwd, input=input)


def mapfile():
    with open(MAP) as f:
        return f.read()


def slot_lines():
    return [l for l in mapfile().splitlines() if l and not l.startswith("#")]


out, _, rc = bh("map", "path")
check("map path: under XDG_CONFIG_HOME", (rc, out), (0, MAP + "\n"))
out, _, rc = bh("map")
check("map list, no file: the running sessions, numbered, running",
      (rc, "no map file" in out, re.findall(r"(?m)^  (\d)  (\S+) .*(running, \d tabs?)$", out)),
      (0, True, [("1", "a", "running, 1 tab"), ("2", "b", "running, 2 tabs")]))
check("map list, no file: nothing written", os.path.exists(MAP), False)
out, _, rc = bh("map", "init")
check("map init: writes the running sessions as slots 1 and 2, folders from ~",
      (rc, slot_lines()), (0, ["1  a  ~", "2  b  ~/src/api"]))
out, err, rc = bh("map", "init")
check("map init: refuses to overwrite without --force", (rc, "--force" in err), (1, True))
_, _, rc = bh("map", "init", "--force")
check("map init --force: replaces it", rc, 0)

_, _, rc = bh("map", "set", "3", cwd=os.path.join(H, "src", "team docs"))
check("map set 3 (from a folder with a space): dir = here, session = its name with _",
      (rc, slot_lines()), (0, ["1  a  ~", "2  b  ~/src/api", "3  team_docs  ~/src/team docs"]))
_, _, rc = bh("map", "set", "0", "~/src/api", "zero")
_, err, rc2 = bh("map", "set", "5", os.path.join(H, "src", "mobile"), "mobile")
check("map set: a folder that doesn't exist yet is kept, with a note",
      (rc, rc2, "does not exist yet" in err, slot_lines()[-1]), (0, 0, True, "5  mobile  ~/src/mobile"))
check("map set: slots in digit order (0 first), comments first",
      ([l.split()[0] for l in slot_lines()], mapfile().startswith("# bellhop session map")),
      (["0", "1", "2", "3", "5"], True))
before = mapfile()
for args, why in ((["set", "x"], "a digit that isn't 0-9"), (["set", "12"], "two digits"),
                  (["set", "4", H, "has.dot"], "a session with a dot"),
                  (["set", "4", H, "has space"], "a session with a space"),
                  (["set", "4", H, "a:b"], "a session with a colon")):
    _, err, rc = bh("map", *args)
    check(f"map set refuses {why}: exit 2, the map unchanged", (rc, mapfile() == before), (2, True))
_, _, rc = bh("map", "set", "2", os.path.join(H, "src", "team docs"), "docs2")
check("map set on a used digit replaces that line", [l for l in slot_lines() if l.startswith("2 ")],
      ["2  docs2  ~/src/team docs"])
_, _, rc = bh("map", "unset", "2")
check("map unset: the line is gone", (rc, [l.split()[0] for l in slot_lines()]), (0, ["0", "1", "3", "5"]))
out, _, rc = bh("map", "unset", "2")
check("map unset on a free digit: says so, exit 0", (rc, "not on the map" in out), (0, True))
out, _, rc = bh("map", "list")
check("map list: running / not started, folders from ~",
      re.findall(r"(?m)^  (\d)  (\S+) +(.+?) +(running, \d tabs?|not started)$", out),
      [("0", "zero", "~/src/api", "not started"), ("1", "a", "~", "running, 1 tab"),
       ("3", "team_docs", "~/src/team docs", "not started"), ("5", "mobile", "~/src/mobile", "not started")])
with open(MAP, "a") as f:
    f.write("7 bad.name ~\n1 dup ~\n")
out, err, rc = bh("map", "list")
check("map list: each bad line is named on stderr, the rest still listed",
      (rc, len(re.findall(r"line skipped", err)), "bad session name" in err, "duplicate digit 1" in err,
       "0  zero" in out), (0, 2, True, True, True))
out, _, _ = bh("panes")
check("map: panes reads the same slots (a is 1)", [l.split("\t")[0] for l in out.splitlines()
                                                 if l.split("\t")[1] == "a"], ["1"])

ED = os.path.join(tempdir(prefix="bh-ed."), "ed.sh")
with open(ED, "w") as f:
    f.write('#!/bin/sh\nprintf "4  web  ~/src/web\\n" >> "$1"\n')
os.chmod(ED, 0o755)
os.remove(MAP)
_, _, rc = bh("map", "edit", env=dict(s.tmux_env(), VISUAL="", EDITOR=ED))
check("map edit: creates the map from the commented template, then runs $EDITOR on it",
      (rc, mapfile().startswith("# bellhop session map"), slot_lines()), (0, True, ["4  web  ~/src/web"]))
_, _, rc = bh("map", "bogus")
check("map: an unknown subcommand → exit 2", rc, 2)

# ── 2. bellhop doctor --ci (no server, no TMUX) ─────────────────────────────
CIH = tempdir(prefix="bh-ci-home.")
CIENV = dict(base_env(), HOME=CIH, XDG_CONFIG_HOME=os.path.join(CIH, ".config"),
             XDG_STATE_HOME=os.path.join(CIH, ".local", "state"),
             TMUX_TMPDIR=tempdir(prefix="bh.", base="/tmp"))   # a stray tmux call finds no server
out, err, rc = run([BELLHOP, "doctor", "--ci"], env=CIENV)
check("doctor --ci: exit 0, no failures", (rc, lines(out, "fail")), (0, []))
check("doctor --ci: versions, awk, lock backend, locale, state and map are checked",
      [any(l.startswith(p) for l in lines(out, "ok")) for p in
       ("tmux ", "fzf ", "bash ", "awk: ", "lock backend: ", "locale: ", "state: ", "map: ")], [True] * 8)
check("doctor --ci: everything that needs a server, settings or PATH is skipped",
      lines(out, "skip"), ["inside tmux (--ci)", "plugin and keys (--ci)", "monitor-bell (--ci)", "save hooks (--ci)",
                           "Claude Code hook (--ci)", "Claude Code settings (--ci)", "focus adapter (--ci)",
                           "command on PATH (--ci)"])
check("doctor --ci: paths shown from ~ (the temp HOME never appears)",
      (CIH in out, "state: ~/.local/state/bellhop/default writable" in out), (False, True))
backend = [l for l in lines(out, "ok") if l.startswith("lock backend: ")][0].split(": ")[1]
check("doctor --ci: the lock backend is one compat knows", backend in ("flock", "lockf", "mkdir"), True)

SHIMB = tempdir(prefix="bh-bash32.")
os.symlink("/bin/bash", os.path.join(SHIMB, "bash"))
want = subprocess.run(["/bin/bash", "-c", 'echo "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}.${BASH_VERSINFO[2]}"'],
                      capture_output=True, text=True).stdout.strip()
out, _, rc = run([BELLHOP, "doctor", "--ci"], env=dict(CIENV, PATH=SHIMB + os.pathsep + CIENV["PATH"]))
check(f"doctor --ci under /bin/bash first on PATH: reports bash {want}",
      (rc, [l for l in lines(out, "ok") if l.startswith("bash ")]), (0, [f"bash {want} ({os.path.realpath('/bin/bash')})"]))

out, _, rc = run([BELLHOP, "doctor", "--ci"], env=dict(CIENV, BELLHOP_FZF="/nonexistent/fzf"))
check("doctor --ci: no fzf is a failure with a fix, exit 1",
      (rc, [l for l in lines(out, "fail") if l.startswith("fzf")], any("install fzf" in x for x in fixes(out))),
      (1, ["fzf: not found (/nonexistent/fzf)"], True))
os.makedirs(os.path.join(CIH, ".config", "bellhop"))
with open(os.path.join(CIH, ".config", "bellhop", "map"), "w") as f:
    f.write("1 api ~/src/api\nx web ~\n1 again ~\n")
out, _, rc = run([BELLHOP, "doctor", "--ci"], env=CIENV)
check("doctor --ci: bad map lines are warnings (fix: bellhop map edit), exit 0",
      (rc, len([l for l in lines(out, "warn") if l.startswith("map: ")]), fixes(out).count("bellhop map edit")),
      (0, 2, 2))
check("doctor --ci: a missing folder of a slot that isn't running is ok",
      [l for l in lines(out, "ok") if l.startswith("map: ")], ["map: 1 slot in ~/.config/bellhop/map · api (will start in ~)"])
out, _, rc = run([BELLHOP, "doctor", "--bogus"], env=CIENV)
check("doctor: an unknown option → exit 2", rc, 2)

# ── 3. bellhop doctor inside tmux ────────────────────────────────────────────
os.remove(MAP)
bh("map", "set", "1", H, "a")
bh("map", "set", "2", os.path.join(H, "src", "gone"), "b")
bh("map", "set", "3", os.path.join(H, "src", "mobile"), "mobile")
out, _, rc = bh("doctor")
check("doctor: exit 0 on a loaded server; the only warnings are the hook and a running slot's gone folder",
      (rc, lines(out, "fail"), lines(out, "warn")),
      (0, [], ["map: slot 2 (b) is running, but its folder ~/src/gone is gone", "Claude Code hook: not installed (optional)"]))
check("doctor: each warning has its fix line", fixes(out), ["bellhop map set 2 <folder>", "bellhop hook install"])
ok = lines(out, "ok")
check("doctor: inside tmux, plugin loaded from this folder, keys bound",
      [l for l in ok if l.startswith(("inside tmux", "plugin:", "inbox:", "find:", "move:"))],
      [f"inside tmux (server {s.name})", f"plugin: loaded from {SHOWN_ROOT}",
       "inbox: prefix i", "find: prefix /", "move: prefix m"])
check("doctor: monitor-bell, save hooks, map (will start in ~), focus adapter",
      [l for l in ok if l.startswith(("monitor-bell", "save hooks", "map:", "focus adapter"))],
      ["monitor-bell on", "save hooks: 3 at [77]", "map: 3 slots in ~/.config/bellhop/map · mobile (will start in ~)",
       "focus adapter: none (jump switches your client)"])
check("doctor: paths shown from ~ (the temp HOME never appears)", H in out, False)

s.t("set-option", "-gw", "monitor-bell", "off")
s.t("bind-key", "m", "display-message mine")
s.t("run-shell", PLUGIN)
s.t("set-option", "-g", "@bellhop-focus-cmd", "/nonexistent/adapter")
e = s.tmux_env()
del e["BELLHOP_FOCUS_CMD"]
out, _, rc = bh("doctor", env=e)
w = lines(out, "warn")
check("doctor: monitor-bell off is a warning with the fix",
      ("monitor-bell is off: a Claude that finishes never shows as finished" in w, "set -g monitor-bell on" in fixes(out)),
      (True, True))
check("doctor: a skipped key says why and how to pick another",
      ([x for x in w if x.startswith("move:")], any("set -g @bellhop-move-key" in x for x in fixes(out))),
      (["move: not bound, because prefix m already does something else (your binding was kept)"], True))
check("doctor: a focus adapter that isn't executable is a warning",
      [x for x in w if x.startswith("focus adapter:")],
      ["focus adapter: /nonexistent/adapter (@bellhop-focus-cmd) is not an executable file, so jump switches your client"])
s.t("set-option", "-gw", "monitor-bell", "on")
s.t("unbind-key", "m")
s.t("set-option", "-gu", "@bellhop-prev-m")
s.t("run-shell", PLUGIN)
s.t("set-option", "-gu", "@bellhop-focus-cmd")

SETTINGS = os.path.join(H, ".claude", "settings.json")
bh("hook", "install", "--yes")
out, _, rc = bh("doctor")
check("doctor: with the hook installed, it is ok", [l for l in lines(out, "ok") if l.startswith("Claude Code hook")],
      ["Claude Code hook: installed for 5 events in ~/.claude/settings.json"])
with open(SETTINGS) as f:
    doc = json.load(f)
doc["disableAllHooks"] = True
with open(SETTINGS, "w") as f:
    json.dump(doc, f, indent=2)
out, _, rc = bh("doctor")
check("doctor: disableAllHooks is a warning", [l for l in lines(out, "warn") if l.startswith("Claude Code settings")],
      ["Claude Code settings: disableAllHooks is true in ~/.claude/settings.json, so Claude Code runs no hooks from it"])
del doc["disableAllHooks"]
with open(SETTINGS, "w") as f:
    json.dump(doc, f, indent=2)

OTHER = tempdir(prefix="bh-other.")
with open(os.path.join(OTHER, "bellhop"), "w") as f:
    f.write("#!/bin/sh\necho acoustics\n")
os.chmod(os.path.join(OTHER, "bellhop"), 0o755)
out, _, _ = bh("doctor", env=s.tmux_env(PATH=OTHER + os.pathsep + s.env["PATH"]))
check("doctor: another program called bellhop on PATH is a warning",
      [l for l in lines(out, "warn") if l.startswith("command:")][0].endswith(
          "is some other program called bellhop (an acoustics toolbox ships one too)"), True)
LINKD = tempdir(prefix="bh-linkdir.")
bh("link", "--dir", LINKD)
out, _, _ = bh("doctor", env=s.tmux_env(PATH=LINKD + os.pathsep + OTHER + os.pathsep + s.env["PATH"]))
check("doctor: our link first on PATH is ok", [l for l in lines(out, "ok") if l.startswith("command:")],
      [f"command: {LINKD}/bellhop is this bellhop"])

bare = Server("admin-bare", conf=None).start("-s", "a", "-c", H)
out, _, rc = run([BELLHOP, "doctor"], env=bare.tmux_env())
check("doctor: plugin not loaded is a failure, exit 1",
      (rc, [l for l in lines(out, "fail")], any("bellhop.tmux" in x for x in fixes(out))),
      (1, ["plugin: not loaded on this server"], True))
bare.kill()

# ── 4. bellhop link / unlink ─────────────────────────────────────────────────
LD = os.path.join(tempdir(prefix="bh-link."), "bin")
env = s.tmux_env(SHELL="/bin/bash")
out, _, rc = bh("link", "--dir", LD, env=env)
link = os.path.join(LD, "bellhop")
check("link: a symlink to bin/bellhop, folder created",
      (rc, os.path.islink(link), os.path.realpath(link) == os.path.realpath(BIN)), (0, True, True))
check("link: DIR not on PATH → the exact line for ~/.bashrc, still exit 0",
      (f'export PATH="{LD}:$PATH"' in out, "~/.bashrc" in out), (True, True))
out, _, rc = bh("link", "--dir", LD, env=s.tmux_env(SHELL="/bin/zsh", PATH=LD + os.pathsep + s.env["PATH"]))
check("link again (on PATH): already linked, no PATH line", (rc, "already points" in out, "export PATH" in out),
      (0, True, False))
out, _, rc = bh("link", env=s.tmux_env(SHELL="/bin/zsh"))
check("link (default ~/.local/bin): the PATH line uses $HOME and names ~/.zshrc",
      (rc, 'export PATH="$HOME/.local/bin:$PATH"' in out, "~/.zshrc" in out,
       os.path.islink(os.path.join(H, ".local", "bin", "bellhop"))), (0, True, True, True))
bh("unlink")
FD = tempdir(prefix="bh-file.")
with open(os.path.join(FD, "bellhop"), "w") as f:
    f.write("#!/bin/sh\n")
_, err, rc = bh("link", "--dir", FD)
check("link: never over a file that isn't our link", (rc, "left alone" in err, os.path.islink(os.path.join(FD, "bellhop"))),
      (1, True, False))
_, err, rc = bh("unlink", "--dir", FD)
check("unlink: a file that isn't our link is left alone, exit 1", (rc, os.path.exists(os.path.join(FD, "bellhop"))),
      (1, True))
out, _, rc = bh("unlink", "--dir", LD)
check("unlink: our link is removed", (rc, os.path.lexists(link)), (0, False))
out, _, rc = bh("unlink", "--dir", LD)
check("unlink again: nothing there, exit 0", (rc, "no link" in out), (0, True))
bh("unlink", "--dir", LINKD)

# ── 5. bellhop uninstall, end to end ─────────────────────────────────────────
u = Server("admin-uninstall").start("-s", "a", "-c", H)
UH = u.home
prev = {k: u.t("show-options", "-gqv", f"@bellhop-prev-{k}") for k in ("i", "/", "m")}
check("uninstall setup: the plugin bound i, / and m over tmux's own",
      [f"'{BIN}' " in keyline(u, k) for k in ("i", "/", "m")] + [bool(prev[k]) for k in prev], [True] * 6)
os.makedirs(os.path.join(UH, ".claude"))
with open(os.path.join(UH, ".claude", "settings.json"), "w") as f:
    f.write('{\n  "model": "example-model"\n}\n')
ue = u.tmux_env()
run([BELLHOP, "hook", "install", "--yes"], env=ue)
run([BELLHOP, "link"], env=ue)
run([BELLHOP, "map", "set", "1", UH, "a"], env=ue)
os.makedirs(os.path.join(UH, ".local", "state", "bellhop", "default"), exist_ok=True)
with open(os.path.join(UH, ".tmux.conf"), "w") as f:
    f.write("set -g base-index 1\nrun-shell ~/.tmux/plugins/tmux-bellhop/bellhop.tmux\n")
out, err, rc = run([BELLHOP, "uninstall"], env=ue)
check("uninstall: exit 0", (rc, err), (0, ""))
with open(os.path.join(UH, ".claude", "settings.json")) as f:
    after = f.read()
check("uninstall: the hook entries are out, the rest of settings.json is as it was",
      after, '{\n  "model": "example-model"\n}\n')
check("uninstall: the link is gone", os.path.lexists(os.path.join(UH, ".local", "bin", "bellhop")), False)
check("uninstall: prefix i, / and m are tmux's own again (m marks a pane, / describes a key)",
      [keyline(u, k) == prev[k] for k in ("i", "/", "m")], [True, True, True])
check("uninstall: the [77] save hooks and @bellhop-* options are gone",
      (["bellhop" in u.t("show-hooks", "-g", h, check=False)
        for h in ("after-new-window", "window-unlinked", "session-closed")],
       [l for l in u.t("show-options", "-g").splitlines() if l.startswith("@bellhop")]),
      ([False] * 3, []))
check("uninstall: names the tmux.conf line to delete, and TPM's prefix alt-u",
      ("~/.tmux.conf:2: run-shell ~/.tmux/plugins/tmux-bellhop/bellhop.tmux" in out, "prefix alt-u" in out),
      (True, True))
check("uninstall: the map and state are kept, with the rm line",
      (os.path.exists(os.path.join(UH, ".config", "bellhop", "map")),
       "rm -rf ~/.local/state/bellhop ~/.config/bellhop" in out), (True, True))
out, _, rc = run([BELLHOP, "uninstall", "--purge"], env=ue)
check("uninstall --purge: again exit 0; the map and saved layouts are removed",
      (rc, os.path.exists(os.path.join(UH, ".config", "bellhop")),
       os.path.exists(os.path.join(UH, ".local", "state", "bellhop"))), (0, False, False))
check("uninstall twice: every step says there is nothing left",
      ("nothing to remove" in out or "does not exist" in out, "no bellhop link" in out, "not loaded" in out),
      (True, True, True))
_, _, rc = run([BELLHOP, "uninstall", "--dir", "x"], env=ue)
check("uninstall: --dir is not an option of uninstall → exit 2", rc, 2)

done()

"""bellhop hook install / uninstall / status against Claude Code settings files.

Every fixture is generated at run time into a temp dir (none are committed):
absent, {}, foreign hooks plus permissions, foreign hooks on the same events,
not-jq-formatted JSON, empty hook containers, invalid JSON, a symlinked file,
CLAUDE_CONFIG_DIR and the default ~/.claude/settings.json under a temp HOME.
No tmux server is needed; nothing outside the temp dirs is touched."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import BELLHOP, REPO, base_env, check, done, run, tempdir  # noqa: E402

JQ = shutil.which("jq")
if not JQ:
    sys.exit("test_hookctl needs jq on PATH")
CMP = shutil.which("cmp")
EVENTS = ("SessionStart", "UserPromptSubmit", "Notification", "Stop", "SessionEnd")
HOOK = os.path.join(os.path.realpath(REPO), "bin", "bellhop-hook")
CMD = f"test -x '{HOOK}' && '{HOOK}' || true"

HOME = tempdir(prefix="bh-hookctl-home.")
ENV = dict(base_env(), HOME=HOME, XDG_CONFIG_HOME=os.path.join(HOME, ".config"),
           XDG_STATE_HOME=os.path.join(HOME, ".local", "state"),
           TMUX_TMPDIR=tempdir(prefix="bh.", base="/tmp"))     # no tmux server is ever reachable


def hook(*args, settings=None, env=None, input=None, bellhop=BELLHOP):
    """Run `bellhop hook ARGS`; (stdout, stderr, rc)."""
    e = dict(ENV)
    if settings:
        e["BELLHOP_CLAUDE_SETTINGS"] = settings
    e.update(env or {})
    return run([bellhop, "hook", *args], env=e, input=input if input is not None else "")


def jqfmt(obj):
    """obj as jq prints it: 2-space indent and a trailing newline."""
    return subprocess.run([JQ, "."], input=json.dumps(obj), capture_output=True, text=True, check=True).stdout


def fixture(name, content):
    """A settings file in a fresh temp dir; content is bytes-as-str, or None for absent."""
    d = tempdir(prefix=f"bh-{name}.")
    p = os.path.join(d, "settings.json")
    if content is not None:
        with open(p, "w") as f:
            f.write(content)
    return p


def read(p):
    with open(p) as f:
        return f.read()


def backups(p):
    d, base = os.path.split(p)
    return sorted(f for f in os.listdir(d) if f.startswith(base + ".bellhop-backup-"))


def our_cmds(doc, event):
    return [h.get("command") for g in doc.get("hooks", {}).get(event, []) for h in g.get("hooks", [])
            if "bellhop-hook" in str(h.get("command", ""))]


def installed_right(doc):
    return all(our_cmds(doc, e) == [CMD] for e in EVENTS)


FOREIGN = {
    "permissions": {"allow": ["Bash(npm test)", "Read(~/src/**)"], "deny": []},
    "model": "example-model",
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}],
    },
    "statusLine": {"type": "command", "command": "echo status"},
}
SAME_EVENTS = {
    "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "printf done >> /tmp/example-log"}]}],
        "Notification": [{"matcher": "", "hooks": [{"type": "command", "command": "echo note", "timeout": 3}]}],
        "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}],
    },
    "env": {"EXAMPLE": "1"},
}

# ── 1. round trips: install then uninstall ────────────────────────────────────
cases = [
    ("{}", "{}\n"),
    ("foreign hooks + permissions", jqfmt(FOREIGN)),
    ("hooks on the same events", jqfmt(SAME_EVENTS)),
    ("non-ASCII text", jqfmt({"note": "café ✳ →", "x": [1, 2.5, None, True]})),
]
for name, content in cases:
    p = fixture("rt", content)
    out, err, rc = hook("install", "--yes", settings=p)
    doc = json.loads(read(p))
    ok_install = rc == 0 and installed_right(doc) and "Added 5 hooks (backup: settings.json.bellhop-backup-" in out
    out2, err2, rc2 = hook("uninstall", settings=p)
    check(f"round trip ({name}): install adds 5, uninstall gives back the same bytes",
          (ok_install, rc2, "Removed 5 hooks" in out2, read(p) == content), (True, 0, True, True))

# Foreign groups, keys and key order are untouched; ours is appended at the end.
p = fixture("order", jqfmt(SAME_EVENTS))
hook("install", "--yes", settings=p)
doc = json.loads(read(p))
check("install: keys keep their order, new events are appended, ours comes after the foreign group",
      (list(json.loads(read(p)).keys()), list(doc["hooks"].keys()),
       [g["hooks"][0]["command"] for g in doc["hooks"]["Stop"]]),
      (["hooks", "env"], ["Stop", "Notification", "SessionStart", "UserPromptSubmit", "SessionEnd"],
       ["printf done >> /tmp/example-log", CMD]))
check("install: the entry is the documented group (type, command, timeout 5)",
      doc["hooks"]["UserPromptSubmit"], [{"hooks": [{"type": "command", "command": CMD, "timeout": 5}]}])

# Not jq-formatted input: equal as JSON (jq -S), not byte-identical.
raw = json.dumps(FOREIGN, indent=4) + "\n"
p = fixture("fmt", raw)
hook("install", "--yes", settings=p)
hook("uninstall", settings=p)
check("round trip (4-space, not jq-formatted): the same JSON, now in jq's format",
      (json.loads(read(p)) == FOREIGN, read(p) == jqfmt(FOREIGN)), (True, True))

# Empty containers: the documented exception, they are gone after the round trip.
for name, obj, want in (
        ('"hooks": {}', {"model": "m", "hooks": {}}, {"model": "m"}),
        ('"Stop": []', {"hooks": {"Stop": [], "PreToolUse": [{"hooks": [{"type": "command", "command": "x"}]}]}},
         {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "x"}]}]}})):
    p = fixture("empty", jqfmt(obj))
    hook("install", "--yes", settings=p)
    hook("uninstall", settings=p)
    check(f"round trip ({name}): equal apart from the empty container it started with",
          json.loads(read(p)), want)

# Absent file: created with its folder, and {} after uninstall.
p = os.path.join(tempdir(prefix="bh-absent."), "nested", "settings.json")
out, _, rc = hook("install", "--yes", settings=p)
created = os.path.exists(p) and installed_right(json.loads(read(p)))
check("absent: install creates the folder and the file, no backup", (rc, created, "(new file " in out, backups(p)),
      (0, True, True, []))
hook("uninstall", settings=p)
check("absent: after uninstall the file is {}", read(p), "{}\n")
p = os.path.join(tempdir(prefix="bh-absent2."), "settings.json")
out, _, rc = hook("uninstall", settings=p)
check("absent: uninstall with no file changes nothing", (rc, os.path.exists(p), "does not exist" in out),
      (0, False, True))

# ── 2. idempotence, dry run, the question ────────────────────────────────────
p = fixture("twice", jqfmt(FOREIGN))
hook("install", "--yes", settings=p)
before, nb = read(p), backups(p)
out, _, rc = hook("install", "--yes", settings=p)
check("install twice: the second is a no-op (same bytes, no new backup)",
      (rc, out.startswith("Already installed"), read(p) == before, backups(p) == nb), (0, True, True, True))
hook("uninstall", settings=p)
before, nb = read(p), backups(p)
out, _, rc = hook("uninstall", settings=p)
check("uninstall twice: the second is a no-op", (rc, "nothing to remove" in out, read(p) == before, backups(p) == nb),
      (0, True, True, True))

p = fixture("dry", jqfmt(FOREIGN))
out, _, rc = hook("install", "--dry-run", settings=p)
check("install --dry-run: prints the diff, writes nothing",
      (rc, "+++ " in out and f'+            "command": "{CMD}",' in out, read(p) == jqfmt(FOREIGN), backups(p)),
      (0, True, True, []))
out, _, rc = hook("install", settings=p, input="n\n")
check("install, answered n: nothing written, exit 1",
      (rc, "Add bellhop's hook to 5 events? [y/N]" in out, "Nothing written." in out, read(p) == jqfmt(FOREIGN)),
      (1, True, True, True))
out, err, rc = hook("install", settings=p, input="")
check("install with no terminal and no answer: nothing written, says --yes, exit 2",
      (rc, read(p) == jqfmt(FOREIGN), "no terminal to ask on; nothing written (--yes writes without asking)" in err),
      (2, True, True))
out, _, rc = hook("install", settings=p, input="y\n")
check("install, answered y: written", (rc, installed_right(json.loads(read(p)))), (0, True))
hook("install", settings=p)
out, _, rc = hook("uninstall", "--dry-run", settings=p)
check("uninstall --dry-run: prints the diff, writes nothing",
      (rc, "-            \"command\"" in out, installed_right(json.loads(read(p)))), (0, True, True))

# ── 3. invalid input is refused, and nothing is ever written ─────────────────
for name, content in (("invalid JSON", '{\n  "model": "m",\n  "hooks": {\n}\n'),
                      ("a list at the top", "[]\n"),
                      ("two objects", "{}\n{}\n"),
                      ("an empty file", ""),
                      ('"hooks" not an object', '{"hooks": "x"}\n'),
                      ('"hooks.Stop" not a list', '{"hooks": {"Stop": {"hooks": []}}}\n')):
    p = fixture("bad", content)
    out, err, rc = hook("install", "--yes", settings=p)
    out2, err2, rc2 = hook("uninstall", settings=p)
    refused = rc == 1 and "nothing written" in err and "settings.json" in err
    check(f"{name}: install refused (message names the file), nothing written, no backup",
          (refused, read(p) == content, backups(p), sorted(os.listdir(os.path.dirname(p)))),
          (True, True, [], ["settings.json"]))
    if name == "invalid JSON":
        check("invalid JSON: jq's own error is shown", "parse error" in err or "jq: error" in err, True)
        check("invalid JSON: uninstall refused too", (rc2, read(p) == content), (1, True))
        _, err3, rc3 = hook("status", settings=p)
        check("invalid JSON: status says it can't read the file", rc3, 1)

# ── 4. backups ───────────────────────────────────────────────────────────────
p = fixture("bak", jqfmt(FOREIGN))
os.chmod(p, 0o600)
old = [f"settings.json.bellhop-backup-2020010{i}T000000Z" for i in range(1, 6)]
for name in old:
    with open(os.path.join(os.path.dirname(p), name), "w") as f:
        f.write("{}\n")
orig = read(p)
out, _, rc = hook("install", "--yes", settings=p)
b = backups(p)
newest = [x for x in b if x not in old]
check("backups: the new backup holds the original bytes; pruned to the newest 3",
      (rc, len(newest), newest and read(os.path.join(os.path.dirname(p), newest[0])) == orig, b[:2]),
      (0, 1, True, ["settings.json.bellhop-backup-20200104T000000Z", "settings.json.bellhop-backup-20200105T000000Z"]))
check("backups: the file keeps its mode (600) through the temp-file rename",
      stat.S_IMODE(os.stat(p).st_mode), 0o600)
hook("uninstall", settings=p)
check("backups: uninstall backs up too, still 3", len(backups(p)), 3)

# ── 5. a symlinked settings file stays a symlink ─────────────────────────────
d = tempdir(prefix="bh-link.")
os.makedirs(os.path.join(d, "config-repo"))
os.makedirs(os.path.join(d, ".claude"))
target = os.path.join(d, "config-repo", "claude-settings.json")
with open(target, "w") as f:
    f.write(jqfmt(FOREIGN))
link = os.path.join(d, ".claude", "settings.json")
os.symlink("../config-repo/claude-settings.json", link)
out, _, rc = hook("install", "--yes", env={"HOME": d})
check("symlink: install through the default ~/.claude/settings.json writes the target, the link stays",
      (rc, os.path.islink(link), os.readlink(link), installed_right(json.loads(read(target)))),
      (0, True, "../config-repo/claude-settings.json", True))
check("symlink: the backup sits beside the link, not in the linked folder",
      (len(backups(link)), [f for f in os.listdir(os.path.dirname(target)) if "backup" in f]), (1, []))
hook("uninstall", env={"HOME": d})
check("symlink: uninstall gives back the bytes, still a link", (os.path.islink(link), read(target) == jqfmt(FOREIGN)),
      (True, True))
dangle = os.path.join(d, ".claude", "dangle.json")
os.symlink("../config-repo/nope/new.json", dangle)
_, err, rc = hook("install", "--yes", settings=dangle, env={"HOME": d})
check("symlink: a link into a missing folder is refused, still a link, nothing made",
      (rc, "missing folder" in err, os.path.islink(dangle), os.path.exists(os.path.join(d, "config-repo", "nope"))),
      (1, True, True, False))

# ── 6. which file: CLAUDE_CONFIG_DIR, BELLHOP_CLAUDE_SETTINGS, --settings ────
d = tempdir(prefix="bh-ccd.")
ccd = os.path.join(d, "claude-config")
out, _, rc = hook("install", "--yes", env={"HOME": d, "CLAUDE_CONFIG_DIR": ccd})
check("CLAUDE_CONFIG_DIR: $CLAUDE_CONFIG_DIR/settings.json is written (folder created), not ~/.claude",
      (rc, os.path.exists(os.path.join(ccd, "settings.json")), os.path.exists(os.path.join(d, ".claude"))),
      (0, True, False))
_, _, rc = hook("status", "--quiet", env={"HOME": d, "CLAUDE_CONFIG_DIR": ccd})
check("CLAUDE_CONFIG_DIR: status --quiet reads the same file", rc, 0)
a, b2 = fixture("env", "{}\n"), fixture("flag", "{}\n")
hook("install", "--yes", "--settings", b2, settings=a)
check("--settings wins over BELLHOP_CLAUDE_SETTINGS", (read(a), installed_right(json.loads(read(b2)))), ("{}\n", True))

# ── 7. a moved plugin, and the guard when the path is gone ───────────────────
COPY = os.path.join(tempdir(prefix="bh-oldroot."), "tmux-bellhop")
for sub in ("bin", "lib", "libexec"):
    shutil.copytree(os.path.join(REPO, sub), os.path.join(COPY, sub))
shutil.copy(os.path.join(REPO, "VERSION"), COPY)
p = fixture("moved", jqfmt(SAME_EVENTS))
hook("install", "--yes", settings=p, bellhop=os.path.join(COPY, "bin", "bellhop"))
doc = json.loads(read(p))
old_cmd = our_cmds(doc, "Stop")[0]
check("moved: the old copy's entry points into the old folder", os.path.realpath(COPY) in old_cmd, True)
env = dict(ENV, PATH=os.environ.get("PATH", ""))
r = subprocess.run(["/bin/sh", "-c", old_cmd], env=env, input='{"hook_event_name":"Stop"}', capture_output=True,
                   text=True)
check("guard: with the path present the command runs the hook and exits 0 silently",
      (r.returncode, r.stdout, r.stderr), (0, "", ""))
shutil.rmtree(COPY)
r = subprocess.run(["/bin/sh", "-c", old_cmd], env=env, capture_output=True, text=True)
check("guard: with the plugin folder gone the command exits 0 and prints nothing", (r.returncode, r.stdout, r.stderr),
      (0, "", ""))
out, _, rc = hook("status", settings=p)
check("status: an entry whose path is gone is stale; exit 1",
      (rc, out.count("stale: "), "fix: bellhop hook install" in out), (1, 5, True))
_, _, rc = hook("status", "--quiet", settings=p)
check("status --quiet: stale is not installed", rc, 1)
out, _, rc = hook("install", "--yes", settings=p)
doc2 = json.loads(read(p))
same_shape = all(len(doc2["hooks"][e]) == len(doc["hooks"][e]) for e in doc["hooks"])
positions = [[i for i, g in enumerate(doc2["hooks"][e]) if "bellhop-hook" in json.dumps(g)] for e in EVENTS]
positions_before = [[i for i, g in enumerate(doc["hooks"][e]) if "bellhop-hook" in json.dumps(g)] for e in EVENTS]
check("moved: install rewrites the command in place (same groups, same positions, new path)",
      (rc, same_shape, positions == positions_before, installed_right(doc2), "Updated 5 hooks" in out),
      (0, True, True, True, True))
check("moved: the foreign groups are untouched",
      [g for e in doc2["hooks"] for g in doc2["hooks"][e] if "bellhop-hook" not in json.dumps(g)],
      [g for e in doc["hooks"] for g in doc["hooks"][e] if "bellhop-hook" not in json.dumps(g)])

# ── 8. the cmp re-check (a cmp shim rewrites the file mid-write) ─────────────
SHIM = tempdir(prefix="bh-shim.")
with open(os.path.join(SHIM, "cmp"), "w") as f:
    f.write(f"""#!/bin/sh
# Test hook: when bellhop compares the live settings file, change it first,
# the way Claude Code would, up to $BH_TEST_TIMES times.
for a in "$@"; do
  if [ "$a" = "$BH_TEST_WATCH" ]; then
    n=$(cat "$BH_TEST_COUNT" 2>/dev/null || echo 0)
    n=$((n + 1))
    echo "$n" > "$BH_TEST_COUNT"
    if [ "$n" -le "$BH_TEST_TIMES" ]; then
      if [ -n "${{BH_TEST_APPEND:-}}" ]; then
        echo >> "$BH_TEST_WATCH"
      else
        printf '{{\\n  "model": "changed-%s"\\n}}\\n' "$n" > "$BH_TEST_WATCH"
      fi
    fi
  fi
done
exec {CMP} "$@"
""")
os.chmod(os.path.join(SHIM, "cmp"), 0o755)


def shimmed(p, times):
    return {"PATH": SHIM + os.pathsep + os.environ.get("PATH", ""), "BH_TEST_WATCH": os.path.realpath(p),
            "BH_TEST_COUNT": p + ".count", "BH_TEST_TIMES": str(times)}


p = fixture("race", jqfmt(FOREIGN))
out, err, rc = hook("install", "--yes", settings=p, env=shimmed(p, 99))
check("cmp re-check: a file that keeps changing aborts, and nothing of ours is written",
      (rc, "settings.json kept changing; nothing written" in err, "bellhop-hook" in read(p),
       read(p) == '{\n  "model": "changed-2"\n}\n', backups(p)), (1, True, False, True, []))
check("cmp re-check: no temp file is left behind",
      sorted(f for f in os.listdir(os.path.dirname(p)) if f.startswith(".")), [])
p = fixture("race1", jqfmt(FOREIGN))
out, err, rc = hook("install", "--yes", settings=p, env=shimmed(p, 1))
doc = json.loads(read(p))
check("cmp re-check: changed once, read again: the new content plus our 5 hooks",
      (rc, "reading it again" in out, doc.get("model"), "permissions" in doc, installed_right(doc)),
      (0, True, "changed-1", False, True))
check("cmp re-check: the one backup holds what was replaced",
      [read(os.path.join(os.path.dirname(p), x)) for x in backups(p)], ['{\n  "model": "changed-1"\n}\n'])
os.remove(p + ".count")
out, err, rc = hook("uninstall", settings=p, env=dict(shimmed(p, 99), BH_TEST_APPEND="1"))
check("cmp re-check: uninstall aborts the same way, our hooks still there",
      (rc, "kept changing" in err, installed_right(json.loads(read(p)))), (1, True, True))
os.remove(p + ".count")
out, err, rc = hook("uninstall", settings=p, env=shimmed(p, 1))
check("cmp re-check: uninstall reads the file again; the new one has no hook, so nothing to remove",
      (rc, "nothing to remove" in out, read(p)), (0, True, '{\n  "model": "changed-1"\n}\n'))

# ── 9. status: duplicates, disableAllHooks, allowManagedHooksOnly, no jq ─────
entry = {"hooks": [{"type": "command", "command": CMD, "timeout": 5}]}
dup = {"disableAllHooks": True, "hooks": {e: [entry] for e in EVENTS}}
dup["hooks"]["Stop"] = [entry, entry]
p = fixture("dup", jqfmt(dup))
out, _, rc = hook("status", settings=p)
check("status: all five installed; a duplicate is reported",
      (rc, len(re.findall(r"(?m)^  \w+ +installed", out)),
       bool(re.search(r"(?m)^  Stop +installed, 2 entries \(duplicate", out))), (0, 5, True))
check("status: disableAllHooks is reported (installed, but Claude Code won't run it)",
      "disableAllHooks is true" in out and "won't run them" in out, True)
check("status: the duplicate's fix", "fix: bellhop hook uninstall && bellhop hook install" in out, True)
p = fixture("managed", jqfmt({"allowManagedHooksOnly": True}))
out, _, rc = hook("status", settings=p)
check("status: allowManagedHooksOnly is reported; nothing installed → exit 1",
      (rc, "allowManagedHooksOnly is true" in out, out.count("missing")), (1, True, 5))

NOJQ = {"BELLHOP_JQ": "/nonexistent/jq"}
p = fixture("nojq", jqfmt(FOREIGN))
out, err, rc = hook("install", "--yes", settings=p, env=NOJQ)
check("no jq: install refuses with the install line, nothing written",
      (rc, "needs jq" in err, "brew install jq" in err, read(p) == jqfmt(FOREIGN)), (1, True, True, True))
_, _, rc = hook("status", "--quiet", settings=p, env=NOJQ)
check("no jq: status --quiet fails when nothing is installed", rc, 1)
hook("install", "--yes", settings=p)
out, _, rc = hook("status", settings=p, env=NOJQ)
check("no jq: status is approximate and finds the five entries",
      (rc, "(checked without jq: approximate)" in out, "installed: 5" in out), (0, True, True))
_, _, rc = hook("status", "--quiet", settings=p, env=NOJQ)
check("no jq: status --quiet exits 0 with all five installed", rc, 0)
with open(p) as f:
    minified = json.dumps(json.load(f))
p2 = fixture("nojq-min", minified + "\n")
_, _, rc = hook("status", "--quiet", settings=p2, env=NOJQ)
check("no jq: a one-line file is counted by entry, not by line", rc, 0)

# ── 10. usage ────────────────────────────────────────────────────────────────
_, err, rc = hook("install", "--quiet")
check("usage: a flag of another subcommand → exit 2", (rc, "unknown option" in err), (2, True))
_, err, rc = hook("bogus")
check("usage: an unknown subcommand → exit 2", rc, 2)
out, _, rc = hook("--help")
check("usage: --help prints the three forms", (rc, all(s in out for s in ("install [--yes]", "uninstall", "status"))),
      (0, True))
p = fixture("default", None)
out, _, rc = hook(settings=p)
check("no subcommand: status", (rc, out.startswith("Claude Code hook: ")), (1, True))

done()

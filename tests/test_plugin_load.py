"""bellhop.tmux on throwaway tmux servers: keys bound when stock and skipped when
taken (never-clobber), options, notes, the [77] save hooks, re-sourcing, unload,
tab titles, the demo caption and the tmux version gate."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import REPO, TMUX, Client, Server, check, done, run, tempdir, wait_for  # noqa: E402

PLUGIN = os.path.join(REPO, "bellhop.tmux")
BIN = os.path.join(REPO, "bin", "bellhop")
HOOKS = ("after-new-window", "window-unlinked", "session-closed")


def keyline(s, key):
    """The prefix-table line for one key ('' when unbound)."""
    for line in s.t("list-keys", "-T", "prefix").splitlines():
        f = line.split()
        i = 4 if len(f) > 4 and f[1] == "-r" else 3
        if len(f) > i and f[i] == key:
            return line
    return ""


def ours(s, key, tool):
    return f"'{BIN}' {tool} " in keyline(s, key)


def hooks(s):
    """{hook: [lines]} for the three save hooks."""
    return {h: [l for l in s.t("show-hooks", "-g", h, check=False).splitlines() if "[" in l.split(" ", 1)[0]]
            for h in HOOKS}


def load(s, *args):
    return s.t("run-shell", " ".join([PLUGIN, *args]))


opt = lambda s, name: s.t("show-options", "-gqv", name)
isset = lambda s, name: s.t("show-options", "-gq", name) != ""

# ── a stock server: all three defaults bound, stock bindings recorded ──────────
s = Server("plugin", conf=None).start("-s", "a", "-n", "one")
STOCK = {k: keyline(s, k) for k in ("i", "/", "m")}
STOCK_NOTES = [l for l in s.t("list-keys", "-N", "-T", "prefix").splitlines()
               if l.split()[1:2] in (["i"], ["/"], ["m"])]
check("stock tmux: i, / and m are bound to tmux's defaults",
      (STOCK["i"].split()[-1], "select-pane -m" in STOCK["m"], "command-prompt -k -p key" in STOCK["/"]),
      ("display-message", True, True))
s.t("set-hook", "-g", "after-new-window[0]", "display-message user-hook")
s.t("bind-key", "Z", "display-message user-key")
out = load(s)
check("load: prints nothing (run-shell would show it)", out, "")
check("load: all three keys bound to bin/bellhop", (ours(s, "i", "inbox"), ours(s, "/", "find"), ours(s, "m", "move")),
      (True, True, True))
check("load: the inbox key passes client, session, window and pane",
      f"'{BIN}' inbox '#{{client_name}}' '#{{session_id}}' '#{{window_id}}' '#{{pane_id}}'" in keyline(s, "i"), True)
notes = s.t("list-keys", "-N", "-T", "prefix")
check("load: each key has a note for prefix ?",
      [n in notes for n in ("bellhop: Claude inbox", "bellhop: find a tab", "bellhop: move tabs")], [True] * 3)
check("load: the stock bindings are recorded in @bellhop-prev-<key>",
      [opt(s, f"@bellhop-prev-{k}") == STOCK[k] for k in ("i", "/", "m")], [True] * 3)
check("load: @bellhop-root is the plugin folder, nothing skipped",
      (opt(s, "@bellhop-root"), isset(s, "@bellhop-skipped")), (REPO, False))
hk = hooks(s)
check("load: one save hook at [77] per event, guarded by -x",
      [[l.split()[0] for l in hk[h] if "bellhop" in l] for h in HOOKS], [[f"{h}[77]"] for h in HOOKS])
check("load: the hook runs `save --from-hook` only when bin/bellhop is executable",
      f"[ -x '{BIN}' ] && '{BIN}' save --from-hook || true" in hk["after-new-window"][-1], True)
check("load: no global options changed (rename format, prefix, monitor-bell)",
      (s.t("show-options", "-gwv", "automatic-rename-format"), opt(s, "prefix"), s.t("show-options", "-gwv", "monitor-bell")),
      ("#{?pane_in_mode,[tmux],#{pane_current_command}}#{?pane_dead,[dead],}", "C-b", "on"))

# Re-sourcing replaces, never stacks, and never overwrites a record.
load(s)
load(s)
hk = hooks(s)
check("re-source: still one hook at [77] per event, the user's [0] untouched",
      [sorted(l.split()[0] for l in hk[h]) for h in HOOKS],
      [["after-new-window[0]", "after-new-window[77]"], ["window-unlinked[77]"], ["session-closed[77]"]])
check("re-source: the keys are ours and the records are still the stock ones",
      (ours(s, "i", "inbox"), [opt(s, f"@bellhop-prev-{k}") == STOCK[k] for k in ("i", "/", "m")]),
      (True, [True] * 3))

# Unload: our keys get their stock bindings back; our hooks go; the user's stay.
out = load(s, "unload")
check("unload: i, / and m are stock again", [keyline(s, k) == STOCK[k] for k in ("i", "/", "m")], [True] * 3)
check("unload: their prefix ? notes are back",
      ([l for l in s.t("list-keys", "-N", "-T", "prefix").splitlines() if l.split()[1:2] in (["i"], ["/"], ["m"])],
       len(STOCK_NOTES)), (STOCK_NOTES, 3))
hk = hooks(s)
check("unload: our hooks are gone, the user's hook and key remain",
      ([l.split()[0] for h in HOOKS for l in hk[h]], "user-key" in keyline(s, "Z")), (["after-new-window[0]"], True))
check("unload: no @bellhop-* options left",
      [l for l in s.t("show-options", "-g").splitlines() if l.startswith("@bellhop")], [])

# ── never-clobber: a key the user bound is skipped, and doctor can see it ─────
s = Server("plugin-taken", conf=None).start("-s", "a", "-n", "one")
c = Client(s, "a")
s.t("bind-key", "m", "display-message mine")
load(s)
check("taken: prefix m keeps the user's binding, the others are bound",
      ("display-message mine" in keyline(s, "m"), ours(s, "i", "inbox"), ours(s, "/", "find")), (True, True, True))
check("taken: @bellhop-skipped names the key, no record is made for it",
      (opt(s, "@bellhop-skipped"), isset(s, "@bellhop-prev-m")), ("m", False))
msg = wait_for(lambda: "prefix m is bound to something else" in s.t("show-messages") and s.t("show-messages"),
               "the skipped-key message")
check("taken: a message says which option picks another key", "set @bellhop-move-key to pick a key" in msg, True)

# An explicit option binds anyway, and unload gives the user's binding back.
s.t("set-option", "-g", "@bellhop-move-key", "m")
load(s)
check("explicit key: @bellhop-move-key m binds over the user's key; nothing skipped",
      (ours(s, "m", "move"), isset(s, "@bellhop-skipped")), (True, False))
load(s, "unload")
check("explicit key: unload gives the user's binding back", "display-message mine" in keyline(s, "m"), True)

# '' binds nothing; another key moves the tool there, and a change hands the old key back.
s.t("set-option", "-g", "@bellhop-inbox-key", "")
s.t("set-option", "-g", "@bellhop-find-key", "F")
s.t("set-option", "-gu", "@bellhop-move-key")
load(s)
check("'' binds nothing: prefix i is stock", keyline(s, "i") == STOCK["i"], True)
check("@bellhop-find-key F: F is ours, / stays stock", (ours(s, "F", "find"), keyline(s, "/") == STOCK["/"]),
      (True, True))
s.t("set-option", "-g", "@bellhop-find-key", "G")
load(s)
check("changing the key: G is ours, F is unbound again", (ours(s, "G", "find"), keyline(s, "F")), (True, ""))
load(s, "unload")
check("unload: G unbound, / and i stock", (keyline(s, "G"), keyline(s, "/") == STOCK["/"], keyline(s, "i") == STOCK["i"]),
      ("", True, True))
c.close()

# ── options read at load: demo caption, autosave, tab titles ──────────────────
s = Server("plugin-opts", conf=None).start("-s", "a", "-n", "one")
s.t("set-option", "-g", "@bellhop-demo-caption", "on")
s.t("set-option", "-g", "@bellhop-autosave", "off")
load(s)
check("demo caption: each key first flashes ' ⌨ prefix <key> '",
      [f'display-message -d 900 " ⌨ prefix {k} "' in keyline(s, k) for k in ("i", "/", "m")], [True] * 3)
check("demo caption: ...then runs bellhop", ours(s, "m", "move"), True)
check("@bellhop-autosave off: no save hooks", [l for h in HOOKS for l in hooks(s)[h]], [])
s.t("set-option", "-gu", "@bellhop-autosave")
load(s)
check("@bellhop-autosave back on: the hooks return", [len(hooks(s)[h]) for h in HOOKS], [1, 1, 1])

DEFAULT_FMT = s.t("show-options", "-gwv", "automatic-rename-format")
s.t("set-option", "-g", "@bellhop-tab-titles", "on")
load(s)
w2 = s.t("new-window", "-d", "-P", "-F", "#{window_id}", "-t", "a:", "sh")
w3 = s.t("new-window", "-d", "-P", "-F", "#{window_id}", "-t", "a:", "sh")
s.t("select-pane", "-t", w2, "-T", "✳ Fix the flaky test")
s.t("select-pane", "-t", w3, "-T", "user@host:~/src/a")
name = lambda w: s.fmt(w, "#{window_name}")
wait_for(lambda: name(w2) == "Fix the flaky test", "the Claude tab named after its title")
check("@bellhop-tab-titles on: a Claude tab is named after its title, glyph stripped; a shell keeps tmux's name",
      (name(w2), name(w3) == s.fmt(w3, "#{pane_current_command}")), ("Fix the flaky test", True))
s.t("set-option", "-gu", "@bellhop-tab-titles")
load(s)
check("@bellhop-tab-titles off again: tmux's default format is back",
      s.t("show-options", "-gwv", "automatic-rename-format"), DEFAULT_FMT)

# ── the version gate: tmux -V below 3.3 binds nothing ─────────────────────────
FAKES = tempdir(prefix="bh-fake-tmux.")


def fake_tmux(version):
    path = os.path.join(FAKES, f"tmux-{version.replace(' ', '_')}")
    with open(path, "w") as f:
        f.write(f'#!/bin/sh\nif [ "$1" = -V ]; then echo "tmux {version}"; exit 0; fi\nexec "{TMUX}" "$@"\n')
    os.chmod(path, 0o755)
    return path


for version, binds in (("3.2a", False), ("2.9", False), ("3.3a", True), ("next-3.6", True), ("master", True)):
    s = Server("plugin-v", conf=None).start("-s", "a", "-n", "one")
    out, err, rc = run([PLUGIN], env=s.tmux_env(BELLHOP_TMUX=fake_tmux(version)))
    check(f"version gate: tmux {version} → {'keys bound' if binds else 'nothing bound, exit 0'}",
          (rc, out, ours(s, "i", "inbox"), isset(s, "@bellhop-root"), len(hooks(s)["session-closed"])),
          (0, "", binds, binds, 1 if binds else 0))
    s.kill()

done()

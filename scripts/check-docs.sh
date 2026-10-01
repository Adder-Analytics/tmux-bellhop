#!/usr/bin/env bash
# scripts/check-docs.sh: the docs say what the code does, and show only the
# fictional demo world. `make docs-check` and CI's lint job run it.
# Exit 0 when every check passes, 1 with the list of misses, 2 when the repo
# can't be read.
#
# 1. Keys. Every fzf --header in libexec/bellhop-{inbox,find,move} is read from
#    the code: a $var set by `var=$(bh_opt NAME DEFAULT)` becomes its default,
#    and `header="$header · more"` adds a second form with the suffix. Each form
#    must appear word for word in the "## Keys" section of docs/<tool>.md, and
#    each " · " part of it ("enter go there") must be one row of a table there,
#    key cell + header cell (| `enter` | go there | …).
# 2. Images. Every image in README.md and docs/*.md is a file in docs/img and
#    has alt text. Remote images are refused, except CI badges (…/badge.svg).
# 3. Links. Every relative link in the docs (README.md, docs/*.md,
#    CONTRIBUTING.md, CHANGELOG.md, SECURITY.md, tests/README.md) resolves,
#    #anchors included (GitHub's heading slugs).
# 4. Names. Every session name and tab or conversation title the docs quote
#    comes from demo/world.tsv or is a placeholder (<session>, work, the
#    neutral test names). Checked where names are quoted: the popup rows under
#    "What you see", the restore plan, and the messages Moved X → S, Grabbed X
#    from S, `X is already here`, left alone: S, typed in: S:X, `claude · X`,
#    `S (slot N)`, attach -t S and -L S.
# 5. Skeleton. Each tool page opens with its "# Tool · key" title, one
#    sentence and its still, and keeps the shared section order. README.md
#    keeps its first ten lines' shape: the still, then the four bullets, and
#    line 9 blank.
#
# CHECK_DOCS_VERBOSE=1 lists every quoted name it checked on stderr.
# bash 3.2, BSD awk, mawk and gawk; every awk runs under LC_ALL=C.
set -uo pipefail

ROOT=$(CDPATH='' cd -P -- "$(dirname -- "$0")/.." && pwd -P) || exit 2
cd "$ROOT" || exit 2
export LC_ALL=C
shopt -s nullglob

WORLD=demo/world.tsv
IMGDOCS=(README.md docs/*.md)
ALLDOCS=(README.md docs/*.md CONTRIBUTING.md CHANGELOG.md SECURITY.md tests/README.md)
DOT='·' ARROW='→' STAR='✳'

for f in "$WORLD" "${ALLDOCS[@]}"; do
  [ -f "$f" ] || { echo "check-docs: $f is missing" >&2; exit 2; }
done

problems=''
miss() { problems+="$1"$'\n'; }

# ---------------------------------------------------------------- 1. keys

# header_forms FILE: "=<TAB>line<TAB>header" per form fzf can show, or
# "?<TAB>line<TAB>text" for a header with a $variable that has no default.
header_forms() {
  awk -v Q="'" '
    function subst(t,   v) {
      for (v in dflt) { gsub("\\$\\{" v "\\}", dflt[v], t); gsub("\\$" v, dflt[v], t) }
      return t
    }
    function emit(t) {
      t = subst(t)
      if (index(t, "$")) printf "?\t%d\t%s\n", FNR, t
      else printf "=\t%d\t%s\n", FNR, t
    }
    /^[ \t]*#/ { next }
    match($0, /[A-Za-z_][A-Za-z0-9_]*=\$\(bh_opt [A-Za-z0-9_-]+ [^ )]+\)/) {
      s = substr($0, RSTART, RLENGTH)
      v = s; sub(/=.*/, "", v)
      d = s; sub(/^[^ ]+ [^ ]+ /, "", d); sub(/\)$/, "", d)
      dflt[v] = d
    }
    match($0, "--header=" Q "[^" Q "]*" Q) { emit(substr($0, RSTART + 10, RLENGTH - 11)); next }
    match($0, /--header="[^"]*"/) {
      t = substr($0, RSTART + 10, RLENGTH - 11)
      if (t != "$header") emit(t)
      next
    }
    match($0, "^[ \t]*header=(" Q "[^" Q "]*" Q "|\"[^\"]*\")") {
      t = substr($0, RSTART, RLENGTH); sub(/^[ \t]*header=/, "", t)
      t = substr(t, 2, length(t) - 2)
      if (substr(t, 1, 7) == "$header") emit(base substr(t, 8))
      else { base = t; emit(t) }
    }
  ' "$1"
}

# keys_section FILE: the "## Keys" section, up to the next "## " heading.
keys_section() {
  awk '/^[ \t]*(```|~~~)/ { f = !f }
    !f && /^## / { if (on) exit; on = ($0 ~ /^## Keys[ \t]*$/); next }
    on' "$1"
}

# key_rows: each table row as "key-cell header-cell", backticks dropped.
key_rows() {
  awk -F '|' '/^[ \t]*\|/ && !/^[ \t]*\|[- \t:|]*$/ {
    r = $2 " " $3; gsub(/`/, "", r); gsub(/[ \t]+/, " ", r)
    sub(/^ /, "", r); sub(/ $/, "", r); print r }'
}

nheaders=0
for tool in inbox find move; do
  src=libexec/bellhop-$tool man=docs/$tool.md
  [ -f "$src" ] || { miss "$src: missing"; continue; }
  [ -f "$man" ] || { miss "$man: missing"; continue; }
  forms=$(header_forms "$src")
  [ -n "$forms" ] || { miss "$src: no fzf --header found"; continue; }
  keys=$(keys_section "$man")
  [ -n "$keys" ] || { miss "$man: no \"## Keys\" section"; continue; }
  rows=$(key_rows <<<"$keys")
  done_segs=$'\n'
  while IFS=$'\t' read -r kind line text; do
    if [ "$kind" = '?' ]; then
      miss "$src:$line: header \"$text\" has a \$variable without a bh_opt default; check-docs can't read it"
      continue
    fi
    nheaders=$((nheaders + 1))
    case $keys in
      *"$text"*) ;;
      *) miss "$man: the Keys section doesn't quote the header \"$text\" ($src:$line)" ;;
    esac
    rest=$text
    while [ -n "$rest" ]; do
      case $rest in
        *" $DOT "*) seg=${rest%%" $DOT "*} rest=${rest#*" $DOT "} ;;
        *) seg=$rest rest='' ;;
      esac
      case $done_segs in *$'\n'"$seg"$'\n'*) continue ;; esac
      done_segs+="$seg"$'\n'
      grep -qxF -- "$seg" <<<"$rows" ||
        miss "$man: no Keys table row reads \"$seg\" as key cell + header cell ($src:$line)"
    done
  done <<<"$forms"
done

# ------------------------------------------------------ 2. images, 3. links

# refs FILE...: HDR<TAB>file<TAB>anchor, IMG<TAB>file<TAB>line<TAB>target<TAB>alt
# and LNK<TAB>file<TAB>line<TAB>target, outside fenced code and code spans.
refs() {
  awk -v OFS='\t' '
    function slug(h,   s) {
      s = tolower(h)
      gsub(/[^a-z0-9 _-]/, "", s)   # punctuation and every non-ASCII byte go
      gsub(/ /, "-", s)
      return s
    }
    FNR == 1 { f = 0; split("", seen) }
    /^[ \t]*(```|~~~)/ { f = !f; next }
    f { next }
    /^#+[ \t]/ {
      h = $0; sub(/^#+[ \t]+/, "", h); sub(/[ \t]+#+[ \t]*$/, "", h); sub(/[ \t]+$/, "", h)
      s = slug(h); n = seen[s]++
      print "HDR", FILENAME, (n ? s "-" n : s)
    }
    {
      line = $0
      gsub(/`[^`]*`/, "", line)
      if (match(line, /^ ? ? ?\[[^]]+\]:[ \t]+[^ \t]+/)) {
        t = substr(line, RSTART, RLENGTH); sub(/^[^]]*\]:[ \t]+/, "", t)
        print "LNK", FILENAME, FNR, t
        next
      }
      rest = line; out = ""
      while (match(rest, /!\[[^]]*\]\([^)]*\)/)) {
        m = substr(rest, RSTART, RLENGTH)
        out = out substr(rest, 1, RSTART - 1) "IMAGE"
        rest = substr(rest, RSTART + RLENGTH)
        alt = m; sub(/^!\[/, "", alt); sub(/\]\(.*$/, "", alt)
        t = m; sub(/^[^]]*\]\(/, "", t); sub(/\)$/, "", t); sub(/[ \t]+".*"$/, "", t)
        print "IMG", FILENAME, FNR, t, alt
      }
      rest = out rest
      while (match(rest, /\[[^]]*\]\([^)]*\)/)) {
        m = substr(rest, RSTART, RLENGTH); rest = substr(rest, RSTART + RLENGTH)
        t = m; sub(/^[^]]*\]\(/, "", t); sub(/\)$/, "", t); sub(/[ \t]+".*"$/, "", t)
        print "LNK", FILENAME, FNR, t
      }
      rest = line
      while (match(rest, /<img[^>]*>/)) {
        m = substr(rest, RSTART, RLENGTH); rest = substr(rest, RSTART + RLENGTH)
        alt = ""; t = ""
        if (match(m, /alt="[^"]*"/)) alt = substr(m, RSTART + 5, RLENGTH - 6)
        if (match(m, /src="[^"]*"/)) t = substr(m, RSTART + 5, RLENGTH - 6)
        print "IMG", FILENAME, FNR, t, alt
      }
    }' "$@"
}

# normpath PATH: drop "." and fold "dir/.." (repo-relative, no symlinks).
normpath() {
  local in=$1 out='' seg
  while [ -n "$in" ]; do
    case $in in
      */*) seg=${in%%/*} in=${in#*/} ;;
      *) seg=$in in='' ;;
    esac
    case $seg in
      '' | .) ;;
      ..)
        case $out in
          '' | .. | ../* | */..) out=${out:+$out/}.. ;;
          */*) out=${out%/*} ;;
          *) out='' ;;
        esac
        ;;
      *) out=${out:+$out/}$seg ;;
    esac
  done
  printf '%s\n' "${out:-.}"
}

records=$(refs "${ALLDOCS[@]}")
headings=$(grep '^HDR' <<<"$records")
nimages=0 nlinks=0
while IFS=$'\t' read -r kind file line target alt; do
  dir=${file%/*}
  [ "$dir" != "$file" ] || dir=.
  case $kind in
    IMG)
      case " ${IMGDOCS[*]} " in *" $file "*) ;; *) continue ;; esac
      nimages=$((nimages + 1))
      [ -n "${alt//[[:space:]]/}" ] || miss "$file:$line: image $target has no alt text"
      case $target in
        http://* | https://*)
          case $target in
            */badge.svg) ;;
            *) miss "$file:$line: remote image $target (images live in docs/img)" ;;
          esac
          continue
          ;;
      esac
      p=$(normpath "$dir/$target")
      case $p in
        docs/img/*) [ -f "$p" ] || miss "$file:$line: image $target not found ($p)" ;;
        *) miss "$file:$line: image $target is not in docs/img" ;;
      esac
      ;;
    LNK)
      case $target in
        http://* | https://* | mailto:*) continue ;;
        '') miss "$file:$line: empty link"; continue ;;
      esac
      nlinks=$((nlinks + 1))
      case $target in
        '#'*) p=$file anchor=${target#\#} ;;
        *'#'*) p=$(normpath "$dir/${target%%#*}") anchor=${target#*#} ;;
        *) p=$(normpath "$dir/$target") anchor='' ;;
      esac
      [ -e "$p" ] || { miss "$file:$line: link $target: $p not found"; continue; }
      if [ -n "$anchor" ]; then
        case $p in
          *.md)
            case " ${ALLDOCS[*]} " in
              *" $p "*) have=$headings ;;
              *) have=$(refs "$p" | grep '^HDR') ;;
            esac
            grep -qxF -- "HDR	$p	$anchor" <<<"$have" ||
              miss "$file:$line: link $target: no heading #$anchor in $p"
            ;;
        esac
      fi
      ;;
  esac
done <<<"$records"

# ---------------------------------------------------------------- 4. names

names=$(awk -F '\t' -v verbose="${CHECK_DOCS_VERBOSE:-}" -v WORLD="$WORLD" -v DOT="$DOT" -v ARROW="$ARROW" -v STAR="$STAR" '
  function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
  function holder(v) { return v ~ /<[^>]*>/ || v == "…" }
  function ok(kind, v) {
    if (holder(v)) return 1
    if (kind == "session") return (v in sess) || (v in neutral)
    if (kind == "socket") return (v in sockets) || (v in sess) || (v in neutral)
    return (v in tab) || (v in sess) || (v in neutral) || (v in tmuxname) || v ~ /^[0-9]+ tabs?$/
  }
  function chk(kind, v) {
    v = trim(v)
    if (v == "") return
    checked++
    if (verbose) printf "#name %s:%d: %s \"%s\"\n", FILENAME, FNR, kind, v
    if (!ok(kind, v))
      printf "%s:%d: %s \"%s\" is not in %s and not a placeholder\n", FILENAME, FNR, kind, v, WORLD
  }
  function word(s) { sub(/[] `(),.;:[].*$/, "", s); return s }
  # Popup rows (inbox, find, move): columns are 2+ spaces apart. Slot digits,
  # badges, states, details and "· here" are skipped; the first name left is
  # the session, the rest are tab names or titles ("claude · title").
  function rows(l,   n, c, i, v, first, k, p, j) {
    n = split(trim(l), c, "  +"); first = 1
    for (i = 1; i <= n; i++) {
      v = trim(c[i])
      if (v == "" || v ~ /^[0-9]$/ || v ~ /^(needs you|finished|working|idle|not started)$/) continue
      if (v ~ /^[0-9]+ tabs?$/ || v ~ /^permission to use / || v ~ /^rang [0-9]+[smhd] ago$/) continue
      if (v ~ /^[0-9]+[smhd]$/ || v ~ /^[^A-Za-z0-9<]+$/) continue
      if (index(v, STAR " ") == 1 || index(v, DOT " ") == 1) continue
      if (first) { chk("session", v); first = 0; continue }
      k = split(v, p, " " DOT " ")
      for (j = 1; j <= k; j++) chk("tab", p[j])
    }
  }
  # The restore plan: sessions indented 2, tabs indented 4 (name, folder, marker).
  function plan(l,   v, i) {
    if (l ~ /^  [^ ]/) { v = substr(l, 3); sub(/ .*$/, "", v); chk("session", v); return }
    if (l !~ /^    [^ ]/) return
    v = substr(l, 5); i = index(v, "  " DOT " ")
    if (i) v = substr(v, 1, i - 1)
    sub(/ +[~\/][^ ]*$/, "", v)
    chk("tab", v)
  }
  FILENAME == WORLD {
    if ($1 == "map") sess[$3] = 1
    if ($1 == "tab") {
      sess[$2] = 1; tab[$4] = 1
      if ($5 != "-") { t = $5; sub(/^[^ ]+ /, "", t); tab[t] = 1 }
    }
    next
  }
  FNR == 1 {
    split("a b c d zz scratch-x search-bug release-notes lobby alpha beta gamma backend", w, " ")
    for (i in w) neutral[w[i]] = 1
    split("work default bellhop-demo NAME SOCKET X", w, " "); for (i in w) sockets[w[i]] = 1
    split("claude node sh bash zsh", w, " "); for (i in w) tmuxname[w[i]] = 1
    fence = 0; head = ""; level = 0
    doc = FILENAME; sub(/^.*\//, "", doc)
  }
  /^[ \t]*(```|~~~)/ { fence = !fence; if (fence) { bhead = head; blevel = level }; next }
  !fence && /^#+[ \t]/ {
    level = index($0, " ") - 1; head = $0; sub(/^#+[ \t]+/, "", head); sub(/[ \t]+$/, "", head)
    next
  }
  fence && bhead == "What you see" && (doc == "inbox.md" || doc == "find.md" || doc == "move.md") { rows($0) }
  fence && blevel == 1 && doc == "restore.md" && FILENAME ~ /^docs\// { plan($0) }
  {
    r = $0
    while (match(r, "Moved [^`]* " ARROW " [^` ]+")) {
      m = substr(r, RSTART + 6, RLENGTH - 6); r = substr(r, RSTART + RLENGTH)
      i = index(m, " " ARROW " "); chk("tab", substr(m, 1, i - 1))
      chk("session", word(substr(m, i + length(ARROW) + 2)))
    }
    r = $0
    while (match(r, /Grabbed [^`]* from [^` ]+/)) {
      m = substr(r, RSTART + 8, RLENGTH - 8); r = substr(r, RSTART + RLENGTH)
      i = index(m, " from "); chk("tab", substr(m, 1, i - 1)); chk("session", word(substr(m, i + 6)))
    }
    r = $0
    while (match(r, /`[^`]* is already here/)) {
      m = substr(r, RSTART + 1, RLENGTH - 17); r = substr(r, RSTART + RLENGTH); chk("tab", m)
    }
    r = $0
    while (match(r, /left alone: [^`]+/)) {
      m = substr(r, RSTART + 12, RLENGTH - 12); r = substr(r, RSTART + RLENGTH)
      k = split(m, p, ", *"); for (j = 1; j <= k; j++) chk("session", p[j])
    }
    r = $0
    while (match(r, /typed in: [^`:]+:[^`]+/)) {
      m = substr(r, RSTART + 10, RLENGTH - 10); r = substr(r, RSTART + RLENGTH)
      i = index(m, ":"); chk("session", substr(m, 1, i - 1)); chk("tab", substr(m, i + 1))
    }
    r = $0
    while (match(r, "`(claude|node|sh|bash|zsh) " DOT " [^`]+`")) {
      m = substr(r, RSTART + 1, RLENGTH - 2); r = substr(r, RSTART + RLENGTH)
      sub("^[a-z]+ " DOT " ", "", m); chk("tab", m)
    }
    r = $0
    while (match(r, /[A-Za-z0-9_.-]+ \(slot [0-9]\)/)) {
      m = substr(r, RSTART, RLENGTH); r = substr(r, RSTART + RLENGTH)
      sub(/ \(slot.*$/, "", m); chk("session", m)
    }
    r = $0
    while (match(r, /attach(-session)? +-t +=?[^ `'"'"'"]+/)) {
      m = substr(r, RSTART, RLENGTH); r = substr(r, RSTART + RLENGTH)
      sub(/^.* +/, "", m); sub(/^=/, "", m); sub(/:.*$/, "", m); chk("session", word(m))
    }
    r = $0
    while (match(r, /(^|[ `[(])-L +[^ `'"'"'"]+/)) {
      m = substr(r, RSTART, RLENGTH); r = substr(r, RSTART + RLENGTH)
      sub(/^.*-L +/, "", m); chk("socket", word(m))
    }
  }
  END { printf "#checked %d\n", checked }
' "$WORLD" "${ALLDOCS[@]}")
nnames=$(sed -n 's/^#checked //p' <<<"$names")
while IFS= read -r l; do
  case $l in
    '#name '*) printf '%s\n' "${l#\#name }" >&2 ;;
    '#checked '* | '') ;;
    *) miss "$l" ;;
  esac
done <<<"$names"

# ------------------------------------------------------------- 5. skeleton

# skeleton FILE TITLE STILL GIF SECTION...
skeleton() {
  local file=$1 title=$2 still=$3 gif=$4
  shift 4
  local order
  order=$(printf '%s|' "$@")
  awk -v title="$title" -v still="$still" -v gif="$gif" -v order="${order%|}" '
    BEGIN { n = split(order, want, "|"); next_want = 1; step = 0 }
    /^[ \t]*(```|~~~)/ { f = !f }
    FNR == 1 { if ($0 != title) printf "%s:1: the title should read \"%s\"\n", FILENAME, title; next }
    step < 2 && !f && NF {
      if (step == 0) {
        if ($0 ~ /^(!|#|\||```|- |<)/) printf "%s:%d: one sentence should follow the title\n", FILENAME, FNR
        step = 1
      } else if (step == 1 && $0 !~ /^[ \t]*$/) {
        if (index($0, "![") != 1 || index($0, "](" still ")") == 0)
          printf "%s:%d: the still %s should follow the first sentence\n", FILENAME, FNR, still
        step = 2
      }
      next
    }
    !f && /^## / {
      h = substr($0, 4); sec = h
      if (next_want <= n && h == want[next_want]) next_want++
    }
    sec == "Watch it" && index($0, "](" gif ")") { sawgif = 1 }
    END {
      if (next_want <= n)
        printf "%s: the section \"## %s\" is missing or out of order (want: %s)\n", FILENAME, want[next_want], order
      if (!sawgif) printf "%s: \"## Watch it\" should show %s\n", FILENAME, gif
    }' "$file"
}

TOOL_ORDER=("Open it" "Keys" "What you see" "Rules" "Without the Claude hook" "For scripts" "Watch it" "See also")
skel=$(
  skeleton docs/inbox.md "# Inbox $DOT prefix i" img/inbox.png img/inbox.gif "${TOOL_ORDER[@]}"
  skeleton docs/find.md "# Find a tab $DOT prefix /" img/find.png img/find.gif "${TOOL_ORDER[@]}"
  skeleton docs/move.md "# Move tabs $DOT prefix m" img/move.png img/move.gif "${TOOL_ORDER[@]}"
  skeleton docs/restore.md "# Restore $DOT bellhop restore" img/restore.png img/restore.gif \
    "Run it" "Flags" "What you see" "Rules" "Without the Claude hook" "For scripts" "Watch it" "See also"
)
while IFS= read -r l; do [ -z "$l" ] || miss "$l"; done <<<"$skel"

# The README's top: the image line runs straight into the four-tool list, and
# line 9 stays blank (else CommonMark folds line 10 into the Restore bullet).
top=$(awk 'NR == 1 && $0 != "# tmux-bellhop" { print "README.md:1: the first line should read \"# tmux-bellhop\"" }
  NR == 4 && !/^!\[[^]]+\]\(docs\/img\/inbox\.png\)$/ { print "README.md:4: should be the inbox still, with alt text" }
  NR >= 5 && NR <= 8 && !/^- \*\*/ { print "README.md:" NR ": should be a \"- **Tool** · …\" bullet, straight after the image" }
  NR == 9 && NF { print "README.md:9: must stay blank" }
  NR == 10 { exit }' README.md)
while IFS= read -r l; do [ -z "$l" ] || miss "$l"; done <<<"$top"

# ----------------------------------------------------------------- report

if [ -n "$problems" ]; then
  list=$(printf '%s' "$problems" | awk '!seen[$0]++')
  count=$(printf '%s\n' "$list" | awk 'END { print NR }')
  printf 'check-docs: %s problem(s)\n' "$count"
  printf '%s\n' "$list" | sed 's/^/  /'
  exit 1
fi
printf 'check-docs: ok (%d fzf headers, %d images, %d relative links, %d quoted names, 4 manual pages)\n' \
  "$nheaders" "$nimages" "$nlinks" "${nnames:-0}"

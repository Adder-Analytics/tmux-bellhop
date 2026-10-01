#!/usr/bin/env bash
# demo/render.sh: renders every image in docs/img from demo/tapes with vhs,
# against the fictional demo server (demo/setup.sh), never a real screen.
#
#   demo/render.sh            every tape (hero inbox find move restore doctor)
#   demo/render.sh inbox ...  only these
#
# It refuses to run unless the repo is at /tmp/tmux-bellhop (doctor prints the
# plugin folder, so no frame may show a home folder or a CI work path), and
# unless a font with every glyph the frames use is installed. During the first
# tape it checks the client is at least 156 columns wide. Afterwards every GIF
# goes through gifsicle -O3 --lossy=40, every image loses its metadata
# (exiftool -all=), and an image over 2 MB or a GIF over 15 s fails the render.
set -euo pipefail
REPO=$(CDPATH='' cd -P -- "$(dirname -- "$0")/.." && pwd -P)
cd "$REPO"
die() {
  printf 'demo/render.sh: %s\n' "$*" >&2
  exit 1
}

case $REPO in
  /tmp/tmux-bellhop | /private/tmp/tmux-bellhop) ;;
  *) die "the repo is at $REPO; render from /tmp/tmux-bellhop (make demos copies it there)" ;;
esac
for t in vhs ttyd ffmpeg gifsicle exiftool fc-list tmux fzf jq; do
  command -v "$t" >/dev/null 2>&1 || die "$t is not installed"
done

# The glyphs the frames draw: the tools' own (✳ ◐ ⌨ › → ─ · … – ▌ ┃ │ ╭╮╰╯)
# and every non-ASCII character in the demo screens and world.
CHARSET="2733 25d0 2328 203a 2192 2500 b7 2026 2013 258c 2503 2502 256d 256e 2570 256f"
extra=$(LC_ALL=C cat demo/screens/*.txt demo/world.tsv | LC_ALL=C od -An -v -tu1 | LC_ALL=C awk '
  { for (i = 1; i <= NF; i++) b[++n] = $i }
  END {
    for (i = 1; i <= n; i++) {
      c = b[i]
      if (c < 128) continue
      if (c >= 240) { cp = (c - 240) * 262144 + (b[i+1] - 128) * 4096 + (b[i+2] - 128) * 64 + b[i+3] - 128; i += 3 }
      else if (c >= 224) { cp = (c - 224) * 4096 + (b[i+1] - 128) * 64 + b[i+2] - 128; i += 2 }
      else if (c >= 192) { cp = (c - 192) * 64 + b[i+1] - 128; i += 1 }
      else continue
      if (!(cp in seen)) { seen[cp] = 1; printf "%x ", cp }
    }
  }')
CHARSET="$CHARSET $extra"
FONT=
for fam in "DejaVu Sans Mono" "Menlo" "Liberation Mono"; do
  if [ -n "$(fc-list ":family=$fam:charset=$CHARSET" family 2>/dev/null)" ]; then
    FONT=$fam
    break
  fi
done
[ -n "$FONT" ] || die "no installed font covers U+${CHARSET// /, U+}; install DejaVu Sans Mono (fonts-dejavu-core, or brew install --cask font-dejavu)"
echo "font: $FONT"

TAPES=("$@")
[ ${#TAPES[@]} -gt 0 ] || TAPES=(hero inbox find move restore doctor)
for t in "${TAPES[@]}"; do
  [ -f "demo/tapes/$t.tape" ] || die "no tape demo/tapes/$t.tape"
done

# The tapes with the font substituted, sourcing the substituted common file.
OUT=demo/out
rm -rf "$OUT"
mkdir -p "$OUT/tapes" docs/img
for f in demo/tapes/*.tape; do
  LC_ALL=C sed -e "s|^Set FontFamily .*|Set FontFamily \"$FONT\"|" \
    -e 's|^Source "demo/tapes/_common.tape"|Source "demo/out/tapes/_common.tape"|' \
    "$f" >"$OUT/tapes/${f##*/}"
done

# The tapes run their own shell: nothing of the caller's tmux may leak in.
unset TMUX TMUX_PANE
"$REPO/demo/teardown.sh" >/dev/null 2>&1 || true

first=1
for t in "${TAPES[@]}"; do
  echo "render: $t"
  vhs -q "$OUT/tapes/$t.tape" &
  vpid=$!
  if [ -n "$first" ]; then
    # The client's width, as soon as the tape attaches.
    (
      while kill -0 "$vpid" 2>/dev/null; do
        w=$(tmux -L bellhop-demo list-clients -F '#{client_width}' 2>/dev/null | head -n 1 || true)
        if [ -n "$w" ]; then
          echo "$w" >"$OUT/width"
          [ "$w" -ge 156 ] || kill "$vpid" 2>/dev/null
          exit 0
        fi
        sleep 0.5
      done
    ) &
    wpid=$!
  fi
  rc=0
  wait "$vpid" || rc=$?
  "$REPO/demo/teardown.sh" >/dev/null 2>&1 || true
  if [ -n "$first" ]; then
    wait "$wpid" 2>/dev/null || true
    w=$(cat "$OUT/width" 2>/dev/null || true)
    [ -n "$w" ] || die "$t: no demo client appeared; is vhs working?"
    [ "$w" -ge 156 ] || die "client is $w columns; lower FontSize in _common.tape"
    echo "client: $w columns"
    first=
  fi
  [ "$rc" -eq 0 ] || die "$t: vhs failed ($rc)"
done

# Optimise, strip metadata, check size and length: only what these tapes
# wrote (their Output and Screenshot lines), so rendering one tape never runs
# a GIF made earlier through the lossy pass a second time.
made=()
while IFS= read -r f; do
  [ -n "$f" ] && [ -e "$f" ] && made+=("$f")
done < <(for t in "${TAPES[@]}"; do
  LC_ALL=C awk -F '"' '($1 == "Output " || $1 == "Screenshot ") && $2 ~ /^docs\/img\/.*\.(gif|png)$/ { print $2 }' \
    "demo/tapes/$t.tape"
done | LC_ALL=C sort -u)
[ ${#made[@]} -gt 0 ] || die "the tapes wrote no image under docs/img"
fail=
for f in "${made[@]}"; do
  case $f in *.gif) ;; *) continue ;; esac
  gifsicle -O3 --lossy=40 -o "$OUT/opt.gif" "$f"
  mv "$OUT/opt.gif" "$f"
done
for f in "${made[@]}"; do
  exiftool -q -q -all= -overwrite_original "$f"
  size=$(wc -c <"$f" | tr -d ' ')
  if [ "$size" -gt 2097152 ]; then
    echo "demo/render.sh: $f is $size bytes (over 2 MB)" >&2
    fail=1
  fi
  case $f in
    *.gif)
      secs=$(gifsicle --info "$f" | LC_ALL=C awk '/delay/ { for (i = 1; i <= NF; i++) if ($i == "delay") { d = $(i + 1); sub(/s$/, "", d); s += d } } END { printf "%.1f", s }')
      printf '  %-24s %8s bytes  %5ss\n' "$f" "$size" "$secs"
      if LC_ALL=C awk -v s="$secs" 'BEGIN { exit !(s > 15) }'; then
        echo "demo/render.sh: $f runs ${secs}s (over 15 s)" >&2
        fail=1
      fi
      ;;
    *) printf '  %-24s %8s bytes\n' "$f" "$size" ;;
  esac
done
rm -rf "$OUT"
[ -z "$fail" ] || exit 1
echo "done: look at every frame before committing (gifsicle --explode, and each PNG at full size)"

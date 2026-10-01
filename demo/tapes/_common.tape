# Shared settings for every demo tape (Source'd first). demo/render.sh
# substitutes FontFamily with the first installed face that has every glyph.
# 1600 px at FontSize 13 with no letter spacing gives a 220-column client, so
# the inbox popup (90%) is 196 columns inside and shows whole titles; at the
# default spacing FontSize 15 gives 154, under render.sh's 156 floor.
Set Shell "bash"
Set Width 1600
Set Height 900
Set FontSize 13
Set LetterSpacing 0
Set FontFamily "DejaVu Sans Mono"
Set Theme "Catppuccin Mocha"
Set TypingSpeed 70ms
Set Padding 16
Set Framerate 15

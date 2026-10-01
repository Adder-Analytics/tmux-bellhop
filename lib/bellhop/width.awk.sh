# shellcheck shell=bash
# lib/bellhop/width.awk.sh: column widths for UTF-8 text in any awk.
#
# BH_AWK_WIDTH holds awk functions to prepend to a program run under LC_ALL=C:
# BSD awk counts bytes whatever the locale, so these count UTF-8 characters by
# hand (every byte that is not a continuation byte 0x80-0xBF starts one). Wide
# characters (CJK, emoji) count as one column; that is a known limitation.
#
#   ulen(s)     characters in s
#   cut(s, n)   s cut to n characters, the last one replaced by … when cut
#   pad(s, n)   s cut to n and padded with spaces to n characters, plus one space
#   min(a, b)   the smaller number
#
#   LC_ALL=C awk "$BH_AWK_WIDTH"'{ print pad($1, 10) }'

# shellcheck disable=SC2034 # used by the scripts that source this file
BH_AWK_WIDTH='
function ulen(s,   n) { n = length(s); return n - gsub(/[\200-\277]/, "", s) }
function cut(s, n,   i, k) {
  if (n <= 0) return ""
  if (ulen(s) <= n) return s
  for (i = 1; i <= length(s); i++)
    if (substr(s, i, 1) !~ /[\200-\277]/ && ++k == n) return substr(s, 1, i - 1) "…"
  return s
}
function pad(s, n) { s = cut(s, n); return s sprintf("%" (n - ulen(s) + 1) "s", "") }
function min(a, b) { return a < b ? a : b }
'

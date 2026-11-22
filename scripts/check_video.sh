#!/usr/bin/env bash
# HB-197 Part C: the demo video's size check, and the bitrate a recording of a given length
# must average to stay under the limit.
#
#   scripts/check_video.sh FILE              size, duration, resolution, overall bitrate (ffprobe);
#                                            exits 1 when FILE is over the limit, 0 when under
#   scripts/check_video.sh --budget MINUTES  the average bitrate a MINUTES-long video must stay under
#
# The limit is the operator's statement of GSA's rule (2026-11-17): a demo video of no more than
# 50 megabytes. No held GSA page states it (HB-197 RESULT). MB is read as 10^6 bytes, so 50 MB is
# 50,000,000 bytes and 400 megabits; that is the stricter reading (50 MiB is 52,428,800 bytes).
# VIDEO_LIMIT_MB overrides the limit for one run. Nothing is installed: without ffprobe the size is
# still checked and the script says what it could not read.
set -euo pipefail

LIMIT_MB="${VIDEO_LIMIT_MB:-50}"
LIMIT_BYTES=$((LIMIT_MB * 1000000))
LIMIT_MBIT=$((LIMIT_MB * 8))

usage() {
  echo "usage: $0 FILE | $0 --budget MINUTES" >&2
  exit 2
}

[ $# -ge 1 ] || usage

if [ "$1" = "--budget" ]; then
  [ $# -eq 2 ] || usage
  # awk does the division: bash has integers only
  awk -v mbit="$LIMIT_MBIT" -v min="$2" -v mb="$LIMIT_MB" 'BEGIN {
    if (min + 0 <= 0) { print "MINUTES must be above 0" > "/dev/stderr"; exit 2 }
    s = min * 60
    printf "%s MB is %d megabits; a %s-minute video (%d s) must average under %.2f Mbit/s, sound included\n", mb, mbit, min, s, mbit / s
  }'
  exit $?
fi

[ $# -eq 1 ] || usage
FILE="$1"
if [ ! -f "$FILE" ]; then
  echo "no such file: $FILE" >&2
  exit 2
fi

BYTES=$(wc -c <"$FILE" | tr -d ' ')
echo "file:       $FILE"
awk -v b="$BYTES" 'BEGIN { printf "size:       %d bytes (%.2f MB)\n", b, b / 1000000 }'

if command -v ffprobe >/dev/null 2>&1; then
  # A file ffprobe cannot read still has its size checked below: its failure is printed,
  # not allowed to end the script before the limit is tested (set -e).
  if DUR=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$FILE" 2>&1) &&
    RATE=$(ffprobe -v error -show_entries format=bit_rate -of default=nw=1:nk=1 "$FILE" 2>&1) &&
    RES=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$FILE" 2>&1); then
    awk -v d="$DUR" 'BEGIN { printf "duration:   %.1f s\n", d }'
    echo "resolution: ${RES:-no video stream}"
    awk -v r="$RATE" 'BEGIN { printf "bitrate:    %.2f Mbit/s overall\n", r / 1000000 }'
  else
    echo "ffprobe could not read the file: ${DUR}${RATE:-}${RES:-}"
  fi
else
  echo "ffprobe is not installed: duration, resolution and bitrate not read (install nothing for this check; the size is enough)"
fi

if [ "$BYTES" -gt "$LIMIT_BYTES" ]; then
  echo "OVER the ${LIMIT_MB} MB limit (${LIMIT_BYTES} bytes)"
  exit 1
fi
echo "under the ${LIMIT_MB} MB limit (${LIMIT_BYTES} bytes)"

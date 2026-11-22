#!/bin/sh
# HB-107 Part B: one nested rung-2 session (HB-98's form, as HB-105 Part D ran it), 600 s bound, polled kill.
# Started from the primary root (HB-98: Chrome connects there). The prompt is this directory's rung2_prompt.txt.
set -u
PROMPT=/Users/brock/GitHub/hazbrief-mcp/.claude/worktrees/unified-giggling-sutherland/docs/evidence/hb107/ports/rung2_prompt.txt
OUT=/tmp/hb107
mkdir -p "$OUT"
cd /Users/brock/GitHub/hazbrief-mcp || exit 1
LOG=$OUT/rung2.log
date -u +"START %Y-%m-%dT%H:%M:%SZ" > "$OUT/rung2.times"
claude -p --chrome --permission-mode bypassPermissions --output-format stream-json --verbose "$(cat "$PROMPT")" > "$LOG" 2>&1 &
PID=$!
n=0
while kill -0 $PID 2>/dev/null; do
  sleep 5
  n=$((n+5))
  if [ $n -ge 600 ]; then
    kill $PID
    echo "KILLED at ${n}s" >> "$OUT/rung2.times"
    break
  fi
done
wait $PID
rc=$?
date -u +"END %Y-%m-%dT%H:%M:%SZ" >> "$OUT/rung2.times"
echo "EXIT $rc" >> "$OUT/rung2.times"
cat "$OUT/rung2.times"

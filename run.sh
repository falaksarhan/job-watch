#!/bin/zsh
# Weekly job watch: scan the boards, save the digest, send only the NEW matches.
#
# Meant to be started by a scheduler (launchd on a Mac, cron elsewhere) at a fixed hour and
# then once an hour for the rest of the day. Only the first run of a day scans. The later runs
# exist to retry a notification that failed earlier (laptop asleep, messaging app not open)
# and do nothing when nothing is owed.
#
# Settings, as environment variables or edited here:
#   JOB_WATCH_OUT   folder for the saved digests              default: ~/job-watch-digests
#   NOTIFY_CMD      command that receives one text file as its only argument and exits 0
#                   when the message was delivered; leave empty to just save the digest
#   PART_SIZE       roles per message when a digest is split for a chat app   default: 12
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${JOB_WATCH_OUT:-$HOME/job-watch-digests}"
NOTIFY="${NOTIFY_CMD:-}"
PART="${PART_SIZE:-12}"
mkdir -p "$OUT"
day="$(date +%Y-%m-%d)"
digest="$OUT/$day.txt"
log="$HERE/log.txt"
pending="$HERE/pending.txt"     # holds the path of a digest whose notification is still owed
lastscan="$HERE/last-scan"      # holds the day of the last successful scan

# Split a digest into chat sized parts (header plus up to PART roles each) and send them.
# Returns 0 only when every part was delivered.
send_digest() {
  local d="$1" tmpd p ok=0
  [[ -n "$NOTIFY" ]] || return 0
  tmpd="$(mktemp -d)"
  awk -v RS= -v d="$tmpd" -v n="$PART" 'NR==1{hdr=$0; next} {i=int((NR-2)/n)+1; f=d"/part"i".txt"; if(!(i in seen)){seen[i]=1; print hdr" (part "i")\n" > f} print $0"\n" >> f}' "$d"
  for p in "$tmpd"/part*.txt; do
    [[ -f "$p" ]] || continue
    if ! ${=NOTIFY} "$p" >> "$log" 2>&1; then ok=1; break; fi
    sleep 4
  done
  rm -rf "$tmpd"
  return $ok
}

# 1) A notification is still owed from an earlier run? Retry it and stop.
if [[ -f "$pending" ]]; then
  owed="$(cat "$pending")"
  if [[ -f "$owed" ]]; then
    if send_digest "$owed"; then
      rm -f "$pending"
      echo "$(date) resent after retry: $owed" >> "$log"
    else
      echo "$(date) retry failed, still pending: $owed" >> "$log"
    fi
  else
    rm -f "$pending"
  fi
  exit 0
fi

# 2) Already scanned today? Then this is an hourly slot with nothing to do.
if [[ -f "$lastscan" && "$(cat "$lastscan")" == "$day" ]]; then
  exit 0
fi

# 3) First run of the day: scan.
python3 "$HERE/scan.py" > "$digest" 2>>"$log" || { echo "$(date) scan failed, will retry next hour" >> "$log"; rm -f "$digest"; exit 1; }
echo "$day" > "$lastscan"

# New matches? The header reads "Job watch DATE: N new match(es) ..."
n="$(head -n1 "$digest" | sed -E 's/.*: ([0-9]+) new match.*/\1/')"
if [[ "${n:-0}" -eq 0 ]]; then
  echo "$(date) no new matches, nothing sent" >> "$log"
  rm -f "$digest"
  exit 0
fi

if send_digest "$digest"; then
  echo "$(date) sent $n new matches, digest saved: $digest" >> "$log"
else
  echo "$digest" > "$pending"
  echo "$(date) notification failed for $n new matches, will retry every hour: $digest" >> "$log"
fi

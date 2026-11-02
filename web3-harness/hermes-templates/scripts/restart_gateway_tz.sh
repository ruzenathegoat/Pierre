#!/bin/bash
# One-shot: reload the gateway so cron schedules recompute in the new timezone,
# then record what the scheduler now thinks so the result can be verified later.
LOG=/home/ubuntu/.hermes/cache/scratch/tz_after_restart.log
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z %z') restarting hermes-gateway ==="
} >> "$LOG" 2>&1

/usr/bin/systemctl --user restart hermes-gateway.service >> "$LOG" 2>&1
RC=$?
echo "restart exit=$RC" >> "$LOG" 2>&1
sleep 10

{
  echo "--- after restart: $(date '+%Y-%m-%d %H:%M:%S %Z %z') ---"
  /usr/bin/systemctl --user is-active hermes-gateway.service
  python3 - <<'PY'
import json, os
p = os.path.expanduser('~/.hermes/cron/jobs.json')
try:
    jobs = json.load(open(p))['jobs']
    now = __import__('datetime').datetime.now().astimezone().isoformat()
    print('now:', now)
    for j in jobs:
        print(f"{j.get('id')} {j.get('name','')[:32]:34} next={j.get('next_run_at')}")
except Exception as e:
    print('jobs.json read failed:', e)
PY
} >> "$LOG" 2>&1

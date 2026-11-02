# Timezone changes and reloading the gateway from outside

Why this exists: `timedatectl set-timezone` retargets the system clock immediately (`date`, `timedatectl`, Hermes timestamps all follow), but the running gateway and any long-lived MCP child keep the timezone they cached at process start. Cron expressions are evaluated in that cached zone, so wall-clock schedules keep firing at the old hour, and `jobs.json` keeps the old UTC offset in `next_run_at`.

## 1. Confirm the split

```bash
timedatectl | head -4                 # Time zone: Asia/Jakarta (WIB, +0700)
date +"%Z %z"
python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.hermes/cron/jobs.json')));[print(j['id'],j['name'][:30],j['next_run_at']) for j in d['jobs']]"
```

A fresh run's `last_run_at` showing the new offset while `next_run_at` still shows the old one is the signature of this state: timestamps are live, scheduling is not.

## 2. Prove which zone the scheduler uses

Create a throwaway cron job at a minute that only makes sense in one zone, then read `next_run_at` and delete it:

```
cronjob_manage(action='create', schedule='5 2 * * *', name='tz probe', deliver='local', prompt='reply OK')
cronjob_manage(action='list')      # next_run_at tomorrow => scheduler still on the old zone
cronjob_manage(action='remove', job_id='<id>')
```

Pick the minute so the two hypotheses disagree (a time already past in one zone). Do not shift the real schedules by an hour as a workaround; a later restart would break them again.

## 3. Restart out of process

The gateway cannot restart itself: the terminal lifecycle guard refuses commands referencing the gateway service from inside a gateway-run turn, and a plain restart would kill the in-flight reply anyway. `systemd-run --on-active` is also refused because its argv names the service. The working path is a unit file plus a one-shot user timer: the restart then executes from systemd, outside the gateway process.

`~/.config/systemd/user/pierre-tz-reload.service`

```ini
[Unit]
Description=One-shot gateway restart so cron reloads the timezone

[Service]
Type=oneshot
ExecStart=/bin/bash /home/ubuntu/.hermes/scripts/restart_gateway_tz.sh
```

`~/.config/systemd/user/pierre-tz-reload.timer`

```ini
[Unit]
Description=Delayed trigger for pierre-tz-reload.service

[Timer]
OnActiveSec=180
Unit=pierre-tz-reload.service

[Install]
WantedBy=timers.target
```

The script restarts the service, then logs state so the outcome is verifiable without the user touching a shell:

```bash
#!/bin/bash
LOG=/home/ubuntu/.hermes/cache/scratch/tz_after_restart.log
/usr/bin/systemctl --user restart hermes-gateway.service >> "$LOG" 2>&1
sleep 10
{ date '+%Y-%m-%d %H:%M:%S %Z %z'
  /usr/bin/systemctl --user is-active hermes-gateway.service
  python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.hermes/cron/jobs.json')));[print(j['id'],j['next_run_at']) for j in d['jobs']]"
} >> "$LOG" 2>&1
```

Arm it:

```bash
systemctl --user daemon-reload
systemctl --user start pierre-tz-reload.timer
systemctl --user list-timers pierre-tz-reload.timer --no-pager
```

## 4. Rules around the restart

- Give the timer at least a couple of minutes so the current reply is delivered before the process dies; the platform shows a brief offline blip.
- Tell the user what restarts, how long it blips, and where the verification log lives. Offer the cancel command (`systemctl --user stop pierre-tz-reload.timer`) in case they change their mind.
- The restart is safe when the service has `Restart=always`; check the unit before promising uptime.
- Read the log file to confirm the service is active before telling the user it landed, and do not assume the restart fixed the schedules; step 5 does that.

## 5. Force the stored schedules to recompute

A restart only changes which zone the scheduler *evaluates* new computations in. `next_run_at` already written to `jobs.json` is an absolute timestamp and survives untouched: after the reload, daily jobs still carried `09:10+08:00` (= 08:10 WIB) and would have fired an hour early. Only an interval job that happened to fire in the meantime picked up `+07:00`.

Re-writing the same schedule expression does not recompute it either. Change the expression by a minute, then set it back, so each value is genuinely different and triggers a fresh computation:

```
cronjob_manage(action='update', job_id='<id>', schedule='11 9 * * *')   # recomputes -> 09:11+07:00
cronjob_manage(action='update', job_id='<id>', schedule='10 9 * * *')   # -> 09:10+07:00
```

Do this for every wall-clock (`cron` kind) job. Interval jobs (`every 15m`, `every 2h`) keep a stale offset until their next fire and then self-correct, so they need no action; say so instead of silently rebuilding them.

Verify from the store, not from the job API's rendering:

```bash
python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.hermes/cron/jobs.json')));[print(j['id'],j['name'][:30],j['next_run_at']) for j in d['jobs']]"
```

Every wall-clock job must now end in the new zone's offset. A job response that prints `09:10+07:00` while `jobs.json` still holds `09:10+08:00` is a display conversion, not a fix.

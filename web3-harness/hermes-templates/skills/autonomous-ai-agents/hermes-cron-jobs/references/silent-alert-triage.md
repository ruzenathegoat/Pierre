# Triaging a cron job that stopped alerting

Symptom: a watchdog/radar job is running every N minutes, the user asks "why did only one alert come in?" or "is this still working?".

Work in this order. Each step rules out one layer, so you do not "fix" a filter that was fine.

## 1. Was anything actually delivered?

The run history lives in SQLite, not in the job API rendering:

```bash
sqlite3 ~/.hermes/cron/executions.db \
  "select started_at,status,delivery_outcome,substr(error,1,80) from executions \
   where job_id='<id>' order by started_at desc limit 25"
```

- `delivery_outcome='suppressed'` + `status='completed'` = the script printed nothing. The job is healthy; the condition never fired or the dedupe swallowed it.
- `delivery_outcome='delivered'` + `status='failed'` = the text went out on the failure channel; read `error`.
- `select min(started_at), count(*)` for the same job tells you whether it has only ever run since a rewrite (a short history explains "only one message ever").
- **`suppressed` on every run while the state file's `alerts` keys keep advancing = the job posts itself through a webhook, and its stdout is empty by design.** Do not report "nothing was sent": those messages reached the channel under the webhook's own username, so they carry no `Cronjob Response:` header and leave no row in `executions`/`deliveries`. Confirm the destination without posting by GETting the webhook URL from the job's env file (`curl -s <url>`), which returns its `name`, `channel_id` and `guild_id`. This is also the usual explanation for "alerts stopped appearing" right after the script gained a webhook path.

## 2. Did the process produce stdout?

`~/.hermes/cron/output/<job_id>/<timestamp>.md` holds one file per run with a `**Status:**` line:

| Status line | Meaning |
| :--- | :--- |
| `silent (empty output)` | Ran fine, printed nothing. Filter or dedupe, never a crash. |
| `script failed` + stderr block | Real exception, with traceback. Fix the script. |
| message body below `---` | This is what was delivered. Diff its wording against the current script's f-strings. |

A message whose format does not match any string in the current script came from an **older version** of the script. Say that explicitly instead of hunting a bug in code that never produced it.

Assume nothing about the script from memory: read `ls -l` mtime and `grep -n '<filter markers>' <script>` before reasoning about its filters. Long-lived alert scripts get edited between sessions (embeds added, webhook path added, filters renamed), and diagnosing from the filter names you patched last time sends you hunting code that no longer exists.

## 3. Did the dedupe burn the alert?

Read the state file and compare `alerts` keys against `contracts`:

```python
import json, time
st = json.load(open(os.path.expanduser("~/.hermes/cache/<job>_state.json")))
for ca, v in st["contracts"].items():
    print(v.get("sym"), ca[:10], "first_seen", time.strftime("%H:%M", time.localtime(v["first_seen"])),
          "done", v.get("done"), "alert_keys", [k.split(":")[-1] for k in st["alerts"] if k.startswith(ca)])
```

Two failure shapes show up here:

- **A key exists that the user never saw.** A manual run (`python ~/.hermes/scripts/x.py`) wrote it; the cron tick that followed was suppressed for the whole rededupe window. This is the most common cause of "it alerted once then went quiet".
- **No key at all for a tracked entity** whose live numbers clearly qualify: the filter logic excludes it. Go to step 4.

## 4. Re-evaluate the entities against live data

Import the script as a module and reuse its own chain helpers, instead of rewriting RPC calls by hand:

```python
import sys; sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import agent_mint_radar as R          # or whatever the script is called
R.FREE_TOPIC = R.topic("FreeClaimed(address,bytes32)")   # module globals it expects
for ca in json.load(open(STATE))["contracts"]:
    print(ca, R.view_int(ca, ["sold()"]), R.view_int(ca, ["startedAt()"]))
```

Print one row per tracked entity with the exact fields every filter reads (age, remaining, velocity) plus whether its alert key exists. That table answers "is the filter wrong or is the world quiet" in a single glance, and it becomes the report you give the user.

`RADAR_NOSTATE=1`-style guard (below) must be set for this step: importing and calling helpers is safe, but if you also execute `main()` you will burn dedupe keys.

## 5. Check the discovery window

Event-scanning jobs (`eth_getLogs` over the last N blocks, API pagination, a directory crawl) only ever see inside that window. State it in the report: "a mint that opened more than 25 minutes ago and is not already tracked is invisible". Widening the window has a cost (RPC weight, runtime, rate limits) so offer it, do not silently change it.

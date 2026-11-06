---
name: hermes-cron-jobs
version: 0.1.0
author: hermes-curator
license: MIT
description: Use when creating or debugging Hermes cron jobs.
metadata:
  hermes:
    tags: [cron, scheduling, watchdog, delivery, timezone]
    related_skills: [hermes-channel-routing, evm-wallet-verification]
---

# Hermes Cron Jobs

Authoring and debugging scheduled work on this host: silent watchdogs, script-only jobs, delivery targets, and the timezone traps that make a job fire an hour off.

## When to Use

- The user asks to automate something recurring ("bikin cron buat X", "cek tiap pagi", "auto-rotate").
- A job fires at the wrong hour, goes silent, or spams the channel.
- A run reports `last_status: error` / `script failed` and you need to know whether it is a real failure.
- System timezone changed and schedules must be revalidated.

## Choosing the job shape

| Need | Shape |
| :--- | :--- |
| Deterministic check with no judgement (key/health/quota watchdog) | `no_agent: true` + `script` |
| Analysis, formatting, or tool use (PnL report, digest) | prompt job, optionally with `skills` |
| Post only when something changed | `monitor` script, or `no_agent` with empty stdout |
| Incremental work that must not repeat itself | `continuity: true` |

`script` paths resolve under `~/.hermes/scripts/` unless absolute. `.sh` runs via bash, anything else via Python.

## Cost and cadence

Every fire of a prompt job is a full agent session; a `no_agent` script is just a process that starts and exits. Do the arithmetic out loud when proposing a cadence: `every 2m` on a prompt job is 720 model sessions a day, and a user asking for seconds is asking for tens of thousands. A deterministic condition therefore defaults to `no_agent`, and the proposal quotes the measured cost of one pass (wall time, peak RSS from `/usr/bin/time -v`) instead of a guess.

- The schedule grammar bottoms out at minutes (durations, `every Nm`, 5-field cron). A checker that must run every few seconds is a resident loop (systemd `--user` service), not a job.
- **The configured interval is not the cadence the user sees.** The ticker drifts and skips: an `every 2m` job measured 153 runs across 7.7h, i.e. roughly every 3 minutes. When asked "how often does this run", read `select started_at from executions where job_id='<id>' order by started_at desc limit 10`, diff the stamps, and quote the measured figure with the configured one in the same sentence ("jadwal 2 menit, efektif ~3 menit"). `jobs.json` `schedule.display` and `next_run_at` are the intent, not the observation.
- A poll interval only has to be faster than the thing it is racing. Derive it from the event's own rate (how fast the condition changes) and say so, rather than minimising blindly.
- When the job's action is rate-limited by the provider (mint a key, register a hook, publish), the cadence must be **shorter than the quota window**, not tuned to the event. A once-a-day attempt that lands while quota is spent reports nothing and costs a full window of inaction; hourly retries with a silent 429 path take the first free slot automatically.

## Silent watchdog pattern (the one that goes wrong)

Goal: zero messages while healthy, one clear message when action is needed or blocked.

1. Print **nothing** when healthy. In `no_agent` mode empty stdout delivers nothing at all.
2. Print the message and **`exit 0`** when what you detected is a legitimate report (quota exhausted, renewal blocked, action needed). Non-zero exit in `no_agent` mode is classified as a script failure: the text still goes out but through the failure channel, so with `failure_deliver: 'local'` the user never sees it.
3. Reserve non-zero exit for genuine crashes, and keep `deliver`/`failure_deliver` on a channel the user reads.
4. Dedupe by date: write the alert date into a small state file and stay silent on later ticks the same day. State files hold fingerprints/expiry, never the secret (mode 600).
5. Verify with `cronjob_manage(action='run')` then read `last_status`; `last_error` carries the script's stdout, so it is also where a quiet run shows up. **On a one-shot job (`repeat: 1`) the manual run consumes the single repetition:** the job flips to `state: completed`, `enabled: false`, `next_run_at: null`, and the real fire never happens. Verify the script by running it directly from the shell, or re-create the job after the test, and re-read `next_run_at` in `cronjob_manage(action='list')` before promising the user a delivery time.
6. Give every state-deduping script an escape hatch before you test it: read a `RADAR_NOSTATE`-style env var in `save_state()` and return early, so a manual run can be exercised against live data without marking alerts as sent. Burned keys are silent and look exactly like "the job stopped working".

## Changing the alert conditions of a live job

Editing filters of a job that already has state is a deploy, not an edit: the state file outlives the code.

1. Dry-run the whole `main()` with the no-state guard (`RADAR_NOSTATE=1`-style) and read what it *would* print.
2. **Backfill dedupe keys for every entity already tracked.** A new alert type has no keys yet, so the first cron tick fires it for all N known entities at once. Write the new key for all of them before the next tick, then let only genuinely new entities trigger it.
3. Prove the new path end to end: delete exactly one entity's key and let the **real scheduler** deliver it (not a manual run), then read `~/.hermes/cron/output/<job_id>/<latest>.md`. A manual run proves the f-strings; only a scheduler delivery proves the pipeline.
4. Say in the report which existing entities are now muted by backfill, so a later "it never alerts" question is not a mystery.

## Alert conditions must cover the terminal edge

A condition written as a band (`remaining > 0 and remaining < 25%`) never fires for the entity that goes straight to 0, which is usually the most newsworthy one. Write alert gates as `remaining == 0 or remaining < threshold` and branch the headline, and check every filter for the same shape: `if x`, `if delta`, `if left` all skip the zero case by accident in Python.

## Triaging "why did only one alert come in?"

Never open with "the filter is too strict". Work the layers in order, because each one hides the next:

1. **Delivered?** `sqlite3 ~/.hermes/cron/executions.db "select started_at,status,delivery_outcome from executions where job_id='<id>' order by started_at desc limit 25"`. `completed` + `suppressed` means the script printed nothing, not that delivery broke. If the state file's `alerts` keys keep advancing while every run says `suppressed`, the script posts through a webhook itself and the channel did receive those messages: confirm the webhook's `name`/`channel_id`/`guild_id` with a GET on its URL, and never tell the user a webhook-posted alert never arrived.
2. **Printed?** `~/.hermes/cron/output/<job_id>/*.md` carries a `**Status:**` line per run: `silent (empty output)`, `script failed` with stderr, or the delivered body. If the message the user quotes does not match the current script's format strings, it came from an older script version, say so instead of debugging live code.
3. **Dedupe burned?** Compare the state file's `alerts` keys against `contracts`. A key with no message the user ever saw is the fingerprint of a manual run eating the rededupe window.
4. **Filter wrong or world quiet?** Import the script as a module and dump each tracked entity's live filter inputs in one table. That table is the answer and the report.

Commands, SQL and the module-import probe: `references/silent-alert-triage.md`.

## Timezone and schedule anchoring

The scheduler evaluates cron expressions in the **gateway process's** timezone, cached from when it started. Changing the host timezone (`timedatectl set-timezone ...`) updates `date` and Hermes timestamps immediately. Stored `next_run_at` values then keep the old offset and keep firing on the old wall clock, and **a gateway restart alone does not fix that**: the reload changes which zone new computations use, while the values already written to `jobs.json` stay absolute. After the restart, re-set each `cron`-kind job's schedule expression (bump it a minute, then restore it) to force a recompute. Interval jobs self-correct on their next fire.

- Read the store, not the API rendering: a job response showing `09:10+07:00` while `~/.hermes/cron/jobs.json` still holds `09:10+08:00` is a display conversion, not a fix.

- Confirm with a throwaway job at a discriminating minute (e.g. `5 2 * * *` created at 01:58): if `next_run_at` lands tomorrow, the scheduler is still on the old zone. Remove the probe job afterwards.
- Do not "fix" it by shifting expressions by an hour; that breaks again on the next restart.
- Restart the gateway out of process: a gateway-run turn cannot restart itself (lifecycle guard), and the user may not be at a shell. Schedule a one-shot systemd user timer whose service runs the restart from systemd, then bump-and-restore the schedule of every wall-clock job so `next_run_at` is recomputed. Recipe and verification: `references/timezone-and-gateway-reload.md`.
- Report the two facts separately when they disagree: "timestamps already WIB, cron still +08:00 until restart".

## Delivery targets

- `origin` = the chat/topic the job was created from; `local` = file only; bare platform name = that platform's home channel; `platform:chat_id` for an explicit target.
- Interactive recurring reports the user wants to reply to: `attach_to_session: true`.
- Long agent jobs that post themselves (webhook with a custom username) can use `deliver: local` and curl the webhook in the prompt; success is HTTP 204.
- Posting into a Discord channel by webhook: read the URL from the deployment's `.env` (`DISCORD_WEBHOOK_*`) and never print it; a plain GET on that URL (no body) returns `{name, channel_id, guild_id}`, which is the cheapest way to prove a job's webhook still points at the channel the user expects without posting a test message; POST with `curl` plus a normal `User-Agent`, because a Python `urllib` POST is refused by Cloudflare with `403 error code: 1010` even though the URL is valid. Resolve a channel id to its name from `~/.hermes/channel_directory.json` (`platforms.discord[].{id,name,guild}`) before telling the user where a post went, since the bot has no channel-listing API access. Recipe, embed shape and the "a tx executed outside your own pipeline never triggers its broadcast" rule: `references/discord-webhook-post.md`.
- Cron delivery prefixes every post with a `Cronjob Response: <name> (job_id: …)` header and a stop line. Fine for alerts; when the channel must read like a product feed, offer the channel-webhook variant and say the header comes from `deliver`, not from a bug.

## Pitfalls

- **Name what the watch watches before building it.** "Radar", "monitor", "screener" can mean *audit what I send you* or *find new things anywhere on the network*; those are different jobs with different noise levels and different delivery channels. State which one you are building in one line, or ask, before creating anything — a chain-wide scanner firing into the user's chat every two minutes is noise they never agreed to.
- **A silent job is not a broken job.** Empty stdout plus `last_status: ok` is the healthy case; check history before "fixing" it.
- **The inverse also holds: a silent `ok` run does not prove the side effect landed.** A watchdog that swallows a non-critical 429 exits 0 with no output, so a rotation job can look healthy for days while nothing rotates. Verify against the state artifact the script is supposed to write (fingerprint, `expires_at`, last-action timestamp): a state file holding only `updated_at` means the action never succeeded.
- **Probe scripts run inside the project need project-local binaries.** Use `./node_modules/.bin/tsx` and `./node_modules/.bin/tsc -p tsconfig.json`; `npx` can trip the lifecycle scan, and single-file `tsc` misses project aliases. ESM `.ts` probes need `fileURLToPath(import.meta.url)`, not `__dirname`.
- **Schedule expressions are wall clock, intervals are not.** `every 15m` / `every 2h` survive a timezone change untouched; `10 9 * * *` does not.
- **`next_run_at` is stored, not derived.** Updating a job with the same schedule value, or restarting the gateway, leaves the stored timestamp as-is; only a changed expression triggers a recompute. Verify by reading `jobs.json` and checking the offset on every wall-clock job.
- **Verification needs the real path.** A watchdog that decides health from an HTTP status is wrong when the API accepts any credential; run the probe the production tool runs and check its provenance field.
- **Check a counter's direction before narrating it.** `freeClaimed()` / `sold()` return what was *taken*, so `3,000 / 3,000` means zero left, not a full pool. Read the getter name, not the print label; getting the direction backwards flips the whole diagnosis and the report the user acts on.
- **A scanner only sees its own window.** Event scans over the last N blocks (or a paginated API page) cannot discover anything older than the window; when the user asks why an obvious candidate is missing, answer with the window size and its cost to widen, not with a filter tweak.
- **Free-tier quota windows are provider-side and usually rolling, not calendar-day.** Do not assume a minting job's counter clears at 00:00 UTC: a host that spent its allowance late in the previous UTC day still gets 429 hours past the boundary. Treat the reset as unknown until a probe proves it, and estimate the wait from the timestamp of the last successful mint (24h from there is the common shape) while saying it is an estimate.
- **A prompt job runs unattended, so every tool call in its prompt must clear an approval gate with no user present.** `execute_code` is refused outright in those sessions (`BLOCKED: execute_code runs arbitrary local Python … approvals.cron_mode`), which burns a turn of the job's context each time; write the job's prompt around the plain tools (terminal, read_file, write_file, webhook curl) or set `approvals.cron_mode` deliberately for the profile that runs it.
- **A job that writes (mints, pays, publishes) must re-verify its own preconditions at fire time, and its prompt must state the whole agreed plan.** The schedule says when to try, not that the state still holds: quota may not have rolled over, the balance may have been spent, and a simulation may revert. Put the checks in the prompt as a gate that ends the run with a report (read the quota, check the balance, simulate first, stop instead of signing), and spell out the full plan the user agreed to (how many actions, then stop), because a job with no chat context and only one step described will keep going on its own.

## Verification checklist before declaring a job done

1. `cronjob_manage(action='list')` shows the expected `schedule`, `deliver`, `script`.
2. One manual `action='run'` reports the expected status (silent vs message).
3. For a message path, force the condition once (blank the key/flag, restore afterwards) and confirm both text and exit code.
4. State files after the test contain no secret values, only hashes and dates.

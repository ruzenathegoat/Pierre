---
name: hermes-channel-routing
description: "Move Hermes home channel or cron delivery targets."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [hermes, gateway, home-channel, cron, delivery, discord]
---

# Hermes Channel Routing (home channel + cron delivery)

How to move the home channel or retarget scheduled deliveries without breaking the running gateway.

## When to Use

- The user says `/sethome` was run in the wrong channel, or asks where cron/notifications go.
- A scheduled job should deliver somewhere new, or the platform home channel must change.
- Cron output is landing in the old chat after a home-channel move (env mirror still stale).

## Where routing actually lives (read this before editing anything)

- `~/.hermes/config.yaml` -> `platforms.<platform>.home_channel` is the canonical record: chat_id, name,
  user_id, scope_id (the provenance Relay needs after a restart).
- `~/.hermes/.env` -> `<PLATFORM>_HOME_CHANNEL` (+ `_NAME`, `_THREAD_ID`) is the legacy mirror that
  `/sethome` also writes. **The env value wins on load**: `gateway/config_env._env_home_channel` replaces
  the whole `HomeChannel` object, dropping `user_id`/`scope_id` and defaulting the name to `"Home"`
  unless `<PLATFORM>_HOME_CHANNEL_NAME` is set. Update both or the YAML edit silently loses.
- `cron/scheduler_delivery._get_home_target_chat_id()` reads env first, then config, **at fire time**,
  so a home change needs no gateway restart to affect new cron deliveries. The in-process gateway
  config (`runner.config`) only refreshes on `/sethome` or restart, so shutdown notifications and
  `deliver: all` can lag until the next restart.

## Procedure

1. Resolve the target id for real. Multiple channels share a name (`#general` can exist in several
   categories). List the guild and pick by category/position, or confirm recent activity:
   `GET /guilds/<guild>/channels`, then `GET /channels/<id>/messages?limit=1` per candidate.
2. Run the setter, never a hand edit (`scripts/set_home_channel.py` in this skill does both stores):

   ```bash
   cd ~/.hermes/hermes-agent && ./venv/bin/python <skill>/scripts/set_home_channel.py discord <chat_id> "<name>"
   ```

   It calls `gateway.config.persist_home_channel(HomeChannel(...))` then
   `hermes_cli.config.save_env_value()` for `<PLATFORM>_HOME_CHANNEL` and `_THREAD_ID`.
3. Verify resolution, not just the file: import `cron.scheduler_delivery._get_home_target_chat_id`
   with the hermes venv python and assert the new id comes back. It takes the platform name:

   ```bash
   cd ~/.hermes/hermes-agent && ./venv/bin/python -c \
     "from cron.scheduler_delivery import _get_home_target_chat_id as f; print(f('discord'))"
   ```

   Calling it with no argument raises `TypeError: missing 1 required positional argument`.
4. Verify the bot can actually post there: `POST /channels/<id>/messages` then `DELETE` the test
   message. Read access does not imply `SEND_MESSAGES`. `scripts/post_check.py` in this skill does
   the round trip; run it rather than hand-writing the request.
5. Say which notifications the user will actually see move, and when. Read
   "What a home-channel move actually routes" below before reporting success.

## What a home-channel move actually routes

There is no "notification channel" setting: `PlatformConfig` exposes only a boolean
`gateway_restart_notification` next to `home_channel`. So "send the restart/status alerts to channel X
instead of here" means move the home channel to X, or silence them with that boolean. What follows the
home channel:

- Gateway shutdown / restart / back-online notices (`gateway/run_shutdown.py::_notify_active_sessions_of_shutdown`,
  `gateway/run_notifications.py::_send_restart_notification`).
- Cron jobs whose `deliver` is `home` / `all`; jobs carrying an explicit `platform:chat_id` or `origin` do not move.
- Cron `failure_deliver` only when it was written as `home`; it usually names a channel explicitly.

What does NOT move: per-session notices, sent to the chat the session runs in. An in-chat `/restart`
skips the home-channel broadcast entirely, so the requester still gets the notice in their own chat.
Grep `~/.hermes/cron/jobs.json` for explicit delivery targets before saying "everything now goes to X".

## Pitfalls

- `save_env_value` strips non-ASCII and warns it is a key problem. A channel name with accents becomes
  mangled ASCII. Use a plain name (`#general`) or omit `_NAME` and let it default.
- `hermes config set platforms.<p>.home_channel.chat_id ...` updates YAML only; the env var keeps
  overriding it. Change both or the move looks applied but resolves to the old chat.
- Two `home_channel` records can disagree after a partial edit. Treat the resolver output as truth, and
  say which store you touched when reporting.
- Creating a cron job with `deliver=origin` binds the chat the job was created from, not the home
  channel. Re-target with an explicit `platform:chat_id` when the destination differs.
- Before claiming a channel move, check the id is not a thread id. Threads are valid targets but
  `home_channel.thread_id` must stay empty unless pinning the home to that thread.
- The shutdown notice for the NEXT restart can still land in the old chat: the stopping process sends
  it from its in-memory `runner.config`, which refreshes only on `/sethome` or a restart. The files are
  truth for the process that starts afterwards, so promise "from the next restart on", not "instantly".
- Nothing persists config on shutdown (only `/sethome` calls `persist_home_channel`), so a file edit is
  not reverted by the old process exiting  -  no need to race the restart.
- To prove delivery without a test post, grep for the notice itself:
  `grep "Sent shutdown notification to home channel" ~/.hermes/logs/gateway.log`. A line ending in
  `<platform>:<chat_id>` is real delivery evidence; read access alone is not.
- Discord's message-create endpoint can answer with an empty body, so `json.loads(response.read())`
  raises `JSONDecodeError` on a *successful* post. Tolerate an empty body or verify by listing the
  channel's recent messages.

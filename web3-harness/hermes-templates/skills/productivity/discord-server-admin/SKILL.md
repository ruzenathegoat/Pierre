---
name: discord-server-admin
description: Create/audit Discord channels, perms, and verify gates.
version: 1.0.0
author: hermes-curator
license: MIT
metadata:
  hermes:
    tags: [discord, admin, rest-api, cron, permissions]
    related_skills: [hermes-agent]
---

# Discord server admin via bot REST API

## When to Use

- User asks to create, rename, or organize Discord channels/categories, or wants "a home channel for you".
- User asks to update a channel's **description/topic** ("update deskripsi channel-nya") — that is `PATCH /channels/<id>` with `{"topic":"..."}`, see step 3b.
- Cron or notification output must land in a specific Discord channel (`discord:<channel_id>`).
- The bot returns 403 / "Missing Access" when posting, and you need to tell role perms, channel overwrites, and app-level channel access apart.
- User asks for a **verification gate** for new members ("require verify", "member baru harus verify dulu"), or for locking channels behind a `Verified` role — see section 7 and `references/member-verification.md`.

Not for gateway config or Discord plugin setup — that is `hermes-agent`.

Hermes has no Discord admin tool, but the gateway's bot token is on disk and the REST API is reachable with `curl`. Building a channel, wiring cron delivery, and diagnosing "cannot post" all go through the same token.

## 1. Get the token without printing it

```bash
set -a; source ~/.hermes/.env; set +a   # DISCORD_BOT_TOKEN lives here
echo "${DISCORD_BOT_TOKEN:0:12}... len=${#DISCORD_BOT_TOKEN}"   # sanity only
```

The first 12 chars are base64 of the bot user id — decode it (`MTU2...` → app id) to confirm the token belongs to the bot you think it does before writing anything. Never echo the full token, never put it in chat, never paste it into a message body.

Always send `-H "User-Agent: DiscordBot (https://github.com/NousResearch/hermes, 1.0)"` — Discord may reject bare `curl/x.y` outright.

## 2. Discover before creating

```bash
UA="DiscordBot (https://github.com/NousResearch/hermes, 1.0)"
curl -s -H "Authorization: Bot $DISCORD_BOT_TOKEN" -H "User-Agent: $UA" https://discord.com/api/v10/users/@me
curl -s -H "Authorization: Bot $DISCORD_BOT_TOKEN" -H "User-Agent: $UA" https://discord.com/api/v10/users/@me/guilds
curl -s -H "Authorization: Bot $DISCORD_BOT_TOKEN" -H "User-Agent: $UA" https://discord.com/api/v10/guilds/<guild_id>/channels
```

- `type` 0 = text, 2 = voice, 4 = **category**, 5 = announcement, 11/12 = thread. A name the user gives as a "server" is often a category inside the guild — check `parent_id` against the category ids before assuming a second guild exists.
- Check bits in python, not by eye: `MANAGE_CHANNELS=1<<4`, `MANAGE_GUILD=1<<5`, `VIEW_CHANNEL=1<<10`, `SEND_MESSAGES=1<<11`, `READ_MESSAGE_HISTORY=1<<16`, `MANAGE_ROLES=1<<28`.
- `permissions` from `/users/@me/guilds` **over-reports**: it can list `MANAGE_ROLES` / `MANAGE_CHANNELS` while the same bot gets `403 {"code":50013}` on `POST /guilds/<id>/roles`. Read the bot's own role bits from `/guilds/<id>/roles` (the role whose name equals the bot name, `managed: true`) and treat that as the real ceiling. Before promising any write, fire the cheapest real write (create the role you actually need, `POST /guilds/<id>/roles` with `permissions:"0"`) — a `50013` there is the answer, and a success is a step you needed anyway.
- The bot's own member object: `GET /guilds/<id>/members/@me` is **404/400** (no such route), and `GET /users/@me/guilds/<gid>/member` answers `403 {"code":20001,"message":"Bots cannot use this endpoint"}`. Neither is available to a bot token, so take the bot's permissions from the managed role in `/guilds/<id>/roles` and ignore member-route 403s when reasoning about permissions.

## 3. Create channels under the right category

```bash
curl -s -X POST -H "Authorization: Bot $DISCORD_BOT_TOKEN" -H "User-Agent: $UA" \
  -H "Content-Type: application/json" \
  -d '{"name":"cron-results","type":0,"parent_id":"<category_id>","topic":"..."}' \
  https://discord.com/api/v10/guilds/<guild_id>/channels
```

Pick the token/name yourself and create it — this is renameable and the user asked for a channel, not a naming consultation. Then re-list the category and confirm both ids exist in the response. Creation success is not the deliverable; see step 4.

## 3b. Edit a channel topic ("deskripsi channel")

A Discord "description" is the channel `topic`. PATCH it, then read it back:

```bash
# resolve the real channel first — a thread id is NOT the channel id
curl -s -H "Authorization: Bot $DISCORD_BOT_TOKEN" -H "User-Agent: $UA" \
  https://discord.com/api/v10/channels/<thread_or_channel_id> \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print({k:d.get(k) for k in ('id','name','type','parent_id','topic')})"
```

- When you are replying *inside a thread*, the id in your context is the thread (`type` 11/12) and PATCHing its topic is not what the user wants. Walk `parent_id` to the text channel and PATCH that one. Confirm `name` matches what the user called the channel before writing.
- Threads have no useful topic; a 200 on the thread id would be a silent no-op the user cannot see.

Write the JSON body with python, never inline in the shell — emoji and em-dashes in a mixed Indonesian/English topic get mangled by shell quoting:

```bash
python3 -c 'import json,sys; print(json.dumps({"topic": sys.argv[1]}))' "$TOPIC_TEXT" > /tmp/topic.json
curl -s -w '\nHTTP %{http_code}\n' -X PATCH -H "Authorization: Bot $DISCORD_BOT_TOKEN" -H "User-Agent: $UA" \
  -H "Content-Type: application/json" -d @/tmp/topic.json \
  https://discord.com/api/v10/channels/<channel_id>
```

Topic max length is 1024 chars; over that the call 400s. Then verify with `GET /channels/<id>` printing `repr(d['topic'])` — a 200 PATCH only means the request was accepted, and quoting damage shows up as surrogate escapes in the stored value. Quote the final topic text back to the user in the reply.

Keep the topic SHORT — one line, comma-separated fields, no full sentences and no rationale ("alerts only — full detail per fill: CA, chain, token, launchpad, entry-exit, tx hash, socials"). A two-sentence topic reads as "kepanjangan"; short is the default, expand only when asked. Write it in the language the user names (English when they say "versi english") and never mix two languages in one topic.

Topic edits are rate-limited per resource: a second `PATCH /channels/<id>` within a few minutes returns `429 {"retry_after": N}`, where N can run into several hundred seconds. Do not retry in a loop — read `retry_after`, wait it out once (`sleep <N+5>` then the PATCH, backgrounded), and say the delay is Discord's cooldown with the edit queued, not the agent stalling.

## 4. Verify by actually posting — creation success means nothing

`POST /guilds/{id}/channels` only needs guild-level `MANAGE_CHANNELS`, so it succeeds even when the bot has **zero** access to the new channel. Immediately try a real message:

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST -H "Authorization: Bot $DISCORD_BOT_TOKEN" -H "User-Agent: $UA" \
  -H "Content-Type: application/json" -d '{"content":"channel active"}' \
  https://discord.com/api/v10/channels/<channel_id>/messages
```

`403 {"code":50001,"message":"Missing Access"}` = not delivered. Only report the channel as usable after a 200 with a message id.

## 5. Diagnose 50001 in this order

1. `GET /channels/<id>` on the new channel, on a known-good channel, and on the thread you are talking in. If only the current thread returns 200 and everything else 403s, stop — no per-channel overwrite will fix it.
2. Guild-level role math (`/guilds/<id>/roles` for `@everyone` and for the bot's own managed role). If `@everyone` already has VIEW+SEND, role permissions are not the problem.
3. Channel `permission_overwrites`. Empty overwrites + guild allows + still 403 = app-level channel access restriction.
4. App-level restriction is set in Discord's **Server Settings → Integrations → (the app) → Manage/Channels**, not in the Developer Portal. Tell the user exactly that, and say plainly that a dev-portal edit did not and cannot change it. `PATCH /channels/<id>/permissions/<role_id>` with a full allow mask also returns 50001 under this restriction — do not spend calls on it.

Report the split responsibility in one shot: what was created (with ids), what is blocked, what single UI action unblocks it, and what you will do the moment it clears.

## 6. Wire cron output to a channel

Delivery target format is `discord:<channel_id>` (channel id, not name). Set it only after step 4 passed for that specific id, otherwise the job runs fine and every report silently fails. Ask what the job should report and on what schedule at the same time as the channel work — one round trip, not two.

Cheapest id lookup, before spending a REST call: `~/.hermes/channel_directory.json` already lists every known channel and thread as `{id, name, guild, type}` (threads carry the `parent:thread` id you address). Read it with python and match on `name`; fall back to the REST `/guilds/<id>/channels` call only when the channel is newer than the directory.

Verify delivery with `hermes send --to discord:<channel_id> "..."` (prints `sent`, exit 0). It reuses the gateway's platform credentials, needs no LLM and no running gateway, and is the fastest proof that an id is addressable — cheaper than firing the real job.

### 6b. Route failures to a separate alert channel

When the user says an ops channel is "for errors only, from every cronjob", do not build a forwarder — every job has a per-job `failure_deliver` (same grammar as `deliver`) that sends **failure and interruption notices** there instead of the job's normal channel. Set it on each job with `cronjob_manage(action='update', job_id=..., failure_deliver='discord:<alert_channel_id>')`; `deliver` stays untouched, so normal reports keep landing where they belong and errors land in the alert channel only.

- `cronjob_manage(action='list')` does **not** print `failure_deliver`. Verify it persisted in `~/.hermes/cron/jobs.json` (`j['failure_deliver']`) before reporting success.
- Scope it honestly: `failure_deliver` covers engine-level failures — exceptions, timeouts, unreachable model, `blocked_config`, and a run that puts `[CRON_FAILURE]` alone on its first line. A run that *succeeds* while its report says "tool error: …" still goes to the normal channel. If the user wants those too, offer a `no_agent` watchdog job instead (script prints only on anomaly; empty stdout = silent tick, non-zero exit = its own alert), and say which of the two gaps you are closing.
- Resolve the alert channel to a real text-channel id even when the conversation is inside a thread — a thread id delivers to the thread, not the channel the user named.
- Set the override on **every** job in scope, not just the one under discussion, and state the resulting split as a short per-job list (normal → channel X, failure → alert channel).

## 7. Member verification gate

Three architectures exist. Say which one you are building before touching anything, because two of them need the human:

| Want | Mechanism | Who does it |
|---|---|---|
| Click-through rules only, no bot | Community feature + rules channel + **Membership Screening** (pending members cannot send until they accept) | Owner enables Community in UI; `PATCH /guilds/<id>` cannot set `features` |
| Real verify role, button/reaction gate | a verification bot assigns `Verified`; `@everyone` denied `VIEW_CHANNEL` everywhere else | Bot owner configures; Hermes can build the role/channel/permission shell |
| Captcha / anti-raid / kick-if-unverified, third party | Wick, Double Counter, Captcha.bot (free tiers: Double Counter ships invisible captcha + alt/VPN detection, Captcha.bot free = web captcha, 1 role, ads) | human, in that bot's dashboard |
| Captcha / anti-raid / kick, fully owned | a **separate** bot app we write and host (`discord.py` + Pillow, systemd --user) | Hermes builds and runs it; owner only creates the app and sends the token — recipe in `references/self-hosted-verify-bot.md` |

Hard limits that decide the answer:

- **The Hermes gateway cannot handle interactions, but a separate bot process can.** Reactions, buttons and modals need a client that receives `INTERACTION_CREATE`; the gateway only sends messages. Offer the self-hosted bot (`references/self-hosted-verify-bot.md`) instead of claiming the click handler is impossible — but never on the Hermes token: one token is one gateway session, so a second client on it contends with Hermes' own connection and can drop it. Require a dedicated app.
- Role create, `PATCH /guilds/<id>/roles/<rid>`, channel permission overwrites, and `POST /guilds/<id>/channels` all need the bot's **own role** to carry `MANAGE_ROLES` (and `MANAGE_CHANNELS`, `MANAGE_ROLES=1<<28`). Check that bit first (section 2), then attempt the role create. If it 50013s, stop and ask for the toggle: **Server Settings → Roles → (bot role) → Manage Roles + Manage Channels**. That is the fastest single unblock; guessing at more REST calls wastes the turn.
- Probe the two write classes **separately**: `POST /guilds/<id>/roles` and `POST /channels/<id>/messages` can both succeed while `PATCH /channels/<id>` with `permission_overwrites` still returns `50013`. Never infer "I can set channel permissions" from a successful role create or a delivered message — fire the overwrite PATCH early, on the category you are about to lock, before promising the gate.
- **Never deny `@everyone` `VIEW_CHANNEL` on a category before the bot's own role has an allow in the same payload.** A channel overwrite beats the bot's role permission, so a bot that cannot VIEW the category also cannot `GET`, `PATCH`, or even `DELETE` it or its children — every call returns `50001 Missing Access` and only a human with Administrator can undo it. Include `{"id":"<bot role id>","type":0,"allow":"<VIEW|READ|MANAGE_CHANNELS|MANAGE_ROLES>"}` in the same `permission_overwrites` array, or better, pass the whole overwrite set in the `POST /guilds/<id>/channels` create body so there is no window at all.
- `@everyone` must not keep `MANAGE_ROLES` / `MENTION_EVERYONE` / `MODERATE_MEMBERS` on a server getting a gate — flag it in the same message, since the owner is already in Server Settings → Roles.

Ordering, so the server is never locked for everyone mid-setup:

1. Create the `Verified` role (no permissions) **below** the verification bot's role; that bot can only assign roles lower than its own highest. Managed bot roles frequently all sit at the same raw position, and a tie can order the verification bot *under* `Verified` — fix the order explicitly instead of trusting creation order. For a bot we host or drive ourselves, create a **dedicated non-managed role** (e.g. `Gatekeeper`) carrying exactly the bits it needs (`VIEW|SEND|MANAGE_MESSAGES|EMBED|ATTACH|READ|MANAGE_ROLES|KICK`), assign it with `PUT /guilds/<id>/members/<bot_user_id>/roles/<role_id>`, and leave the auto-created managed role unused where it landed: a managed role's permissions come from the invite and it can never be deleted, so the dedicated role is the only one you can reason about or fix later. Prove the hierarchy with a real assignment instead of reading numbers: `PUT` then `DELETE` the `Verified` role on the bot's own user id — `204`/`204` means both `MANAGE_ROLES` and "above `Verified`" are satisfied. `PATCH /guilds/<id>/roles` takes a **JSON array** of `{"id":...,"position":...}` (a dict answers `400 LIST_TYPE_CONVERT`), and the positions must be unique, so reshuffle the whole ladder in one call: owner/staff highest, verification bot next, then the Hermes bot, `Verified` lowest. Read `/guilds/<id>/roles` back and print `position`/`name` to confirm.
2. Create `#verify` (+ `#rules`) **with their full `permission_overwrites` in the create payload**: `@everyone` allowed `VIEW|READ|ADD_REACTIONS` and denied `SEND_MESSAGES` on `#verify` (they must see and react, not talk), and on `#rules` allowed `VIEW|READ` with `SEND` denied. Add the bot's own role as an allow entry in both.
3. Post the verify message. For a third-party bot wiring (Carl/Dyno style) post it as the Hermes bot and add the reaction, so the message id exists to hand over. For a **self-hosted gate bot the panel must be posted by that bot's own token** with the component in the body (`{"type":2,"style":3,"label":"...","custom_id":"vrf:start"}`) — component interactions are routed to the app that created the message, so a panel authored by Hermes delivers every click to Hermes, which cannot answer it. Same rule for the embed: send it via REST with the gate token, no gateway needed.
4. Human wires the reaction to the role in the third-party bot.
5. Only after that, deny `@everyone` `VIEW_CHANNEL` on the existing categories and allow it for `Verified` (category level, not per channel) — in one PATCH per category that also carries the bot role's allow, per the lockout rule above. If that PATCH keeps 50013ing, ask for **Administrator on the bot role temporarily**, finish the layout, add the explicit per-channel allows, then tell the user to turn Administrator back off.
6. Warn that existing members also have to click verify once — they do not have the new role.

Per-bot recipes (Carl-bot invite, `rr verify` / `reactionrole aiov` syntax, dashboard path, what each free captcha bot actually includes) are in `references/member-verification.md`. When the owner wants the gate owned rather than rented, build it: `references/self-hosted-verify-bot.md` has the app setup, captcha renderer, panel/modal shape, config knobs and systemd unit.

## 8. Prefer an existing channel webhook when the message must look clean

Cron delivery (`deliver: discord:<id>`) prefixes every post with `Cronjob Response: <name> / (job_id: ...) / To stop or manage this job...`. When the channel should look like a product feed:

1. `GET /channels/<id>/webhooks` — look for a webhook already bound to that channel (it may already exist with the right name/avatar). Create one only if absent.
2. Store the full URL in a 0600 file (e.g. `~/.hermes/secrets/<channel>_webhook.env`), never in the cron prompt or chat.
3. Set the job `deliver: local`, have the prompt POST the payload itself (`{"username": "...", "content": "..."}` → expect HTTP 204), and set `failure_deliver: discord:<id>` so failures still surface.
4. Verify by reading the channel back and checking `webhook_id` on the message, not just the 204.

Webhook execute without `?wait=true` returns **204 with an empty body** — no message id, so you cannot clean up by webhook message id afterwards; delete via `DELETE /channels/<id>/messages/<msg_id>` after listing the channel. Add `?wait=true` when you need the id.

Webhook tokens are channel-scoped credentials: `~/.hermes/.env` is not the place for them, and they must never be echoed.

## Pitfalls

- Do not promise Discord actions Hermes cannot take (pin, role management, member list, channel creation through the gateway). The REST path above is the only way, and it needs the bot's permissions — the gateway's read access to the current thread is not evidence of broader access.
- When a write returns `50013 Missing Permissions`, that is a missing role bit, not a hierarchy or app-access problem (that is `50001`). Lead the reply with the exact toggle and menu path instead of retrying variants of the same call. But check the bit precisely before naming it: `VIEW_CHANNEL=1<<10`, `SEND_MESSAGES=1<<11`, `MENTION_EVERYONE=1<<17`, `MANAGE_CHANNELS=1<<4`, `MANAGE_ROLES=1<<28`, `MODERATE_MEMBERS=1<<40`. Hand-written label maps drift after bit 6 (they skip the unused `STREAM`/`SEND_TTS` slots) — a wrong map makes you tell the owner to remove a permission the role never had, so decode from bit 0 up with the official table and quote the raw `permissions` integer in your own notes.
- Sharper probe than trying a variant: `PATCH /channels/<id>` with `{}` (no fields) returns 200 when the bot holds `MANAGE_CHANNELS`, while the same call carrying `permission_overwrites` returns `50013` — that pair isolates the missing bit as `MANAGE_ROLES` in one extra call, with no state change.
- `PATCH /channels/<id>` overwrites and `DELETE /channels/<id>` returning `50001` on a channel the bot created moments ago means the bot has lost VIEW on it (a category-level `@everyone` deny), not that the token is broken. Stop retrying and hand the human one unblock: Administrator on the bot role, or an explicit allow entry for the bot role on that category.
- Third-party bots ignore commands from other bots, so any `@Carl-bot ...` / slash-command step must be a human action in the Discord client; hand over the channel id and message id so it is one paste, not a scavenger hunt.
- A bot invited **after** the channels were locked inherits every `@everyone` channel deny. Before blaming the token, loop `GET /guilds/<id>/channels` and append `{"id":"<gate role id>","type":0,"allow":"<VIEW|READ|SEND|EMBED|ATTACH|MANAGE_MESSAGES>","deny":"0"}` to each channel's existing overwrite list (`PATCH /channels/<id>` with the full merged array, reusing the current entries). Guild-level `SEND_MESSAGES` is not enough: the channel-level `@everyone` deny wins and the panel POST answers `50013`.
- Proving slash commands registered: `GET /guilds/<id>/commands` answers `404 {"code":0}` for bot tokens even when the commands exist. Read `GET /applications/<app_id>/guilds/<guild_id>/commands` instead and check the command names in that array.
- A verification bot is only useful if its role outranks `Verified`; newly invited bots land at the bottom tied with every other managed role. Fix the ladder before testing, otherwise `add_roles` returns 403 and the member is stuck unverified while you debug the wrong thing.
- Category order: `PATCH /channels/<category_id> {"position": N}` only sticks when N is unique across categories — Discord tolerates ties and then orders by id, so "move it to the top" needs the whole ladder renumbered in order (0,1,2,3…), then a `GET /guilds/<id>/channels` filtered to `type==4` printed with positions to confirm.
- `PUT /channels/<id>/messages/<mid>/reactions/<emoji>/@me` answers **204 with an empty body**: an empty response is success, not failure. Confirm by reading the message back and checking `reactions` (`[('✅', 1)]`).
- A category id and a guild id look identical; a wrong one creates a channel in the wrong server or 404s. Resolve by name → id → `parent_id` before posting.
- Editing `~/.hermes/.env` or the bot's role is not part of "create a channel" — do not touch either; ask the user to change server settings instead.
- Report to a non-technical owner: name the artifact (channel name + id), the blocker, and the exact menu path. Skip the permission-bit math in the reply even though you used it to diagnose.
- A `429` on a topic edit is a cooldown, not a failure: the stored topic keeps its old value until a later PATCH succeeds, so wait it out or state that the new text is queued — never report it live without a fresh `GET` showing the new string.
- Before promising "alerts from other servers here", check how many guilds are actually connected (`/users/@me/guilds`, or the distinct `guild` values in `channel_directory.json`). One guild + channels is the common case; a server the user names may be unconnected, and cron jobs there cannot report until it is.

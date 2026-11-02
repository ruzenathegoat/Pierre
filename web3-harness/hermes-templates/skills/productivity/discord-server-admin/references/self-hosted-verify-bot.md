# Self-hosted captcha verification bot

Use when the owner does not want a third-party verify bot (privacy, ads, "kurang aman") and accepts one extra bot app so Hermes can actually run the gate. This is the only architecture where the click/typing side is fully under our control, because the gate bot receives its own interactions over its own gateway connection.

## Why a separate app, never the Hermes token

One bot token drives one gateway connection per shard. Running a second client on the Hermes token makes the two processes contend for the same session and can drop Hermes' own Discord connection. You must have a **dedicated application** (its own token, its own role). Say this out loud before asking for anything, or the owner will hand you the Pierre token.

Hermes cannot create the app either: application creation is behind the owner's Discord login. Your part is everything after `Reset Token`.

## What the owner does (exact, one round trip)

1. https://discord.com/developers/applications → New Application.
2. Tab **Bot** → Add Bot.
3. **Privileged Gateway Intents → SERVER MEMBERS INTENT = on.** Without it `on_member_join` never fires and the timeout-kick sweep has nothing to sweep.
4. Reset Token → Copy → send it to you.
5. Invite the app, swapping in its Application ID:
   `https://discord.com/oauth2/authorize?client_id=<APP_ID>&scope=bot+applications.commands&permissions=2416045122`
   (`2416045122` = View Channels, Send Messages, Manage Messages, Embed Links, Attach Files, Read Message History, Manage Roles, Kick Members, Add Reactions, Use Application Commands.)

Token handling: write it to `<botdir>/.env` with `0600` immediately, never echo it, and tell the owner you will delete their token message from the channel right after reading it. Actually delete it: `GET /channels/<id>/messages?limit=50`, match the token's first segment (base64 of the app id), `DELETE /channels/<id>/messages/<mid>`, then re-list and confirm zero matches. Offer a token rotation once the bot is confirmed live.

## Bring-up order

1. Owner creates the app, enables **Server Members Intent**, sends the token, and **invites the app** — in that order. Intent-on is provable from your side: the client reaches READY with `intents.members` set, while a missing intent closes the socket with 4014 at IDENTIFY.
2. Write `.env` (0600), `systemctl --user daemon-reload`, `enable --now`.
3. `GET /users/@me/guilds` with the gate token: `[]` means the invite did not go through. Do not read that as a permission bug and do not start toggling role bits.
4. Only after the bot is in the guild: reorder the ladder, post the panel **as the gate bot**, delete the old reaction panel, then test.

## Reading the log

`StandardOutput=append:` yields nothing for the first ~60s of a bare-systemd start, which looks exactly like a hang. Two things make it diagnosable: a `say()` helper that appends to `bot.log` with `buffering=1` (first line of `main()` writes `[bot] starting`), and `ss -tnp | grep pid=<ExecMainPID>` for an established `:443` session. Only when both say nothing happened is DNS or intents worth suspecting.

## Runtime layout that works on this host

```bash
cd ~ && mkdir -p verifybot && cd verifybot
~/.hermes/bin/uv venv --python 3.12 .venv
~/.hermes/bin/uv pip install --python .venv/bin/python discord.py pillow
```

`discord.py 2.7.x` + `Pillow` is enough. No pip module on this box; `uv` is at `~/.hermes/bin/uv`.

Files: `bot.py`, `config.json`, `.env` (0600), `verify.db` (sqlite), `bot.log`.

`config.json` knobs to make explicit to the owner, because each is a policy decision, not a default:

```json
{"guild_id":0,"verified_role_id":0,"verify_channel_id":0,"log_channel_id":0,
 "kick_after_minutes":15,"min_account_age_days":7,"max_joins_per_minute":8,
 "captcha_length":5,"max_attempts":3}
```

## Bot shape

- `intents = discord.Intents.default()` with `members = True` and `moderation = True` (timeout).
- Persistent panel: `discord.ui.View(timeout=None)` with a `Button(custom_id="vrf:start")`, registered in `setup_hook` via `self.add_view(PanelView())` so it survives restarts. Without `add_view` the button dies on every deploy and members see "interaction failed".
- Second step: `start_verification` sends an **ephemeral** message with the captcha as `discord.File(..., filename="captcha.png")` plus `embed.set_image(url="attachment://captcha.png")`, and a second button that opens a `discord.ui.Modal` for the code. Modals cannot display images, so image-then-modal is the only order that works.
- Captcha render: Pillow, 260x96, 5 chars from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no I/O/0/1), per-glyph rotation ±24°, noise dots and 7 lines, `DejaVuSans-Bold.ttf`. Generate to `io.BytesIO` and hand Discord the buffer. Verify legibility yourself with vision before shipping the image to the owner.
- Wrong code → new captcha, counter in an in-memory `sessions[user_id]` dict; at max attempts, native `member.timeout(timedelta(minutes=5))` instead of kicking.
- Success → `member.add_roles(role, reason=...)`, delete the pending row, log to the log channel.
- `on_member_join`: account-age kick (`min_account_age_days`), raid heuristic (joins/60s over `max_joins_per_minute` → alert only, never auto-lock), DM instructions, insert into `pending`.
- A `while not self.is_closed()` sweep task every 60s kicks `pending` rows older than `kick_after_minutes` and skips anyone already holding `Verified`.
- Slash commands `/verifypanel` (posts the panel) and `/verifystats`, both gated on `manage_guild=True`.

## Service

`~/.config/systemd/user/verifybot.service` — user services persist here (`Linger=yes`), no sudo needed:

```ini
[Unit]
Description=verify bot
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory=/home/ubuntu/verifybot
EnvironmentFile=/home/ubuntu/verifybot/.env
ExecStart=/home/ubuntu/verifybot/.venv/bin/python /home/ubuntu/verifybot/bot.py
Restart=always
RestartSec=5
StandardOutput=append:/home/ubuntu/verifybot/bot.log
StandardError=append:/home/ubuntu/verifybot/bot.log
[Install]
WantedBy=default.target
```

`systemctl --user daemon-reload`, then `enable --now`. Do not enable before `.env` holds a token: `Restart=always` turns a missing token into an infinite crash loop and a log full of tracebacks. `raise SystemExit("TOKEN belum di-set")` in `main()` keeps that failure readable.

## After the bot joins

The new bot's managed role lands at the lowest position, usually tied with `Verified`, and it can neither be deleted nor meaningfully reconfigured (its permissions come from the invite). Do not fight it: create a dedicated role for the bot instead ("buat role khusus bot-nya aja" is the owner-friendly default), e.g. `Gatekeeper` with `VIEW|SEND|MANAGE_MESSAGES|EMBED|ATTACH|READ|MANAGE_ROLES|KICK`, put it **above** `Verified` by renumbering the whole ladder in one array PATCH (see the SKILL.md ordering rules), then `PUT /guilds/<id>/members/<bot_user_id>/roles/<gate_role_id>`.

Prove the arrangement instead of reading positions: `PUT` then `DELETE` `Verified` on the bot's own user id, expecting `204` twice. That one pair covers `MANAGE_ROLES`, the hierarchy and the assignment route.

Before posting anything, grant the gate role an explicit allow on **every** channel (`GET /guilds/<id>/channels`, merge into each `permission_overwrites`, `PATCH`). Channels locked before the bot existed deny `@everyone`, that deny beats guild-level `SEND_MESSAGES`, and the panel POST answers `50013` until the bot role is in each overwrite set.

Only then post the panel (as the gate bot, over REST or `/verifypanel`) and delete the old reaction-role message so there is exactly one verify path.

## Proving it at the end

- Commands: `GET /applications/<app_id>/guilds/<guild_id>/commands` — `/guilds/<id>/commands` 404s for bot tokens even when the commands exist.
- Log pipe: POST a throwaway embed to the configured `log_channel_id` with the gate token, expect `200`, then delete it. An empty log channel is the correct state before the first join, so test the pipe instead of asserting it works.
- Panel: `GET /channels/<verify_channel_id>/messages/<id>`, check `author` is the gate bot and `components` is non-empty.
- Then hand the last click to the owner's alt account; the agent cannot exercise `member.add_roles` end to end without a real unverified member.

## Verification before reporting done

Local: import the module, render a captcha and look at it, `init_db()` twice (idempotent). Live: bot shows in `GET /guilds/<id>/roles` as a managed role, panel message exists in `#verify`, one test account sees only `START HERE` before clicking and all channels after. State plainly which of those you actually ran; "code is ready, waiting on token" is an honest status.

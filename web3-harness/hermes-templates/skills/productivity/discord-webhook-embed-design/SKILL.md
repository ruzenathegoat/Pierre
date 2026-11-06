---
name: discord-webhook-embed-design
description: Use when restyling Pierre Discord webhook alerts as cards.
---

# Discord webhook embed design (Pierre / Ruzena)

## Standing preferences (apply to every alert)
- Zero emoji anywhere. Minimalist, clean, luxury. Author is just `RŮŽE HOUSE`; strip redundant header labels (signal name already in title, internal names like "Radar Snapshot"). Ask which text he means if a removal request is ambiguous.
- Final direction: native Discord embeds, NO large rendered images. He tried (a) all-text fields where every field had equal weight (hard to scan), then (b) PNG hero cards, then said embeds need not use images and should be cleaner, more minimalist and interactive. Current house style = native embed + link buttons.
- Structure that reads well: title = the thing (linked to explorer); description = at most 2 short lines with the one key number in bold (e.g. `**369** of 500 free shares left  ·  26% claimed`); at most two rows of 3 inline fields holding short backticked values; long/copyable values (full contract) as one non-inline field; native `timestamp` instead of a time string in the footer; footer short (`Pierre Execution Desk  ·  <context>`).
- Interactivity = link buttons (see Components). Real action buttons (Claim, Sell) need a bot-sent message; offer, don't assume. Jobs stay report-only.
- A redesign changes presentation only, never filter/dedupe/state logic.
- He iterates in small visual steps (remove a label, move an icon): make small edits and send a real test post after each.
- BscScan icon requested as the embed `thumbnail` (not author icon); that small thumbnail is the only image kept on the radar.

## Components on plain webhooks (verified live)
- Append `?with_components=true` and send `components:[{type:1,components:[{type:2,style:5,label,url}]}]`. Link buttons (style 5) work on non-application webhooks next to normal embeds; interactive buttons are ignored. 5 buttons per row, 5 rows.
- Components V2 (`flags: 32768`, `type 17` container, `10` text, `14` separator, `9` section) also posts fine, but then `content`/`embeds`/files are forbidden. It is the message.style "new layouts" look; offer it if he wants card-like layouts without images.
- One message per alert when each alert needs its own buttons (buttons attach to the whole message, not one embed). Sleep ~0.7s between posts (webhook rate limit).
- If Discord answers 400 with buttons, resend without them so the alert is never lost.

## Kit (already on the VPS, reuse it)
- `~/.hermes/scripts/pierre_ui.py`: `post(url, username, embeds, wait, buttons, files)` via curl (multipart when attachments); embeds may carry private keys `_buttons` [(label,url)] and `_card` (PNG, legacy). `make_embed`, `link_rows`, `color_int(tone)`; PNG renderers `render_dashboard/render_rows` remain but are unused.
- `~/.hermes/scripts/pierre_post.py --webhook-env <file in ~/.hermes/secrets> --username ... --spec spec.json [--dry-run]`: LLM cron jobs write a JSON spec `{title, description, tone, footer, fields[], buttons[]}`; prints `posted <code>`, never the URL. Old card-style specs are flattened to fields.
- Senders already on the new style: `agent_mint_radar.py` (own embed + BscScan thumbnail from `~/.hermes/assets/bscscan.png`), `pierre_digest_gate.py`, `opensea_key_watch.py`, `order_alert.py`; LLM cron prompts for Open Positions, PnL, daily/weekly recap use pierre_post.
- Webhook env files in `~/.hermes/secrets/`: `positions_webhook.env` (#positions, key POSITIONS_WEBHOOK_URL), `positions_webhook_pnl.env`, `_pierre.env`, `_preview.env`, `_radar.env` (key WEBHOOK_URL).
- Map a channel id to its sender: `~/.hermes/channel_directory.json` gives the name; `jobs.json` `failure_deliver`/`deliver` and the webhook env file tell which job posts there.

## Procedure
1. Find the sender: `hermes cron list` or `~/.hermes/cron/jobs.json`, then script or prompt. Deterministic `no_agent` jobs: edit the script. LLM jobs: rewrite the prompt with `hermes cron edit <id> --prompt "$(cat file)"` so it fills a pierre_post spec instead of hand-building curl payloads. Back up scripts (`cp x x.bak-<ts>`) and old prompts first.
2. Run the sender (`--test-webhook`, `--send-status`, `hermes cron run <id>`) or post a clearly labelled sample; confirm HTTP 200/204 and, for LLM jobs, inspect the spec file the run wrote.
3. Keep a fallback path: never drop an alert because of a decoration (buttons, thumbnail) failing.
4. Never post fake data into live channels. For order-execution alerts use `order_alert.py --dry-run`.
5. Tell him which test posts to delete.

## Pitfalls
- Python urllib to discord.com can hit Cloudflare 1010; use curl (UA `Mozilla/5.0`). Attachments: `--form-string payload_json=...` plus `-F files[i]=@path`, referenced as `attachment://name.png`.
- BscScan 403s hotlinked images and its brand zip; a Google favicon fetch gave the real icon, saved locally and attached.
- Block-character text bars render badly in Discord; use a number instead.
- Cron `hermes cron run` only reports "succeeded"; delivery proof is the `posted <code>` in `~/.hermes/cron/output/<id>/`.
- The TypeScript harness (`web3-harness/src/webhook.ts`) posts its own order embeds separately from `order_alert.py`; restyle both if the order look must change.

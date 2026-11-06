# Posting to a Discord channel by webhook (script or job)

Use when a script, cron job or one-off turn must put a message into a specific channel, or when the user asks why something did not appear in a channel that is fed by webhooks.

## Resolve the channel before claiming anything

The agent has no Discord API access (no history search, no channel listing, no member list). The gateway's own cache is the lookup:

```python
import json
d = json.load(open('/home/ubuntu/.hermes/channel_directory.json'))
for c in d['platforms']['discord']:
    if isinstance(c, dict) and c.get('id'):
        print(c['id'], '|', c.get('name'), '|', c.get('type'), '|', c.get('guild'))
```

`type` is `channel`, `group` (a category-style entry whose `name` is `"<guild> / #<channel>"`) or `thread` (id rendered as `<parent>:<thread>`). So a bare id handed over by the user resolves to a name, and a name to an id, without guessing. Do not tell the user "I cannot see channels" when this file answers it; say you can resolve ids and names but cannot read history or members.

## Post it with curl, not urllib

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST "$WEBHOOK_URL" \
  -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
  -d @payload.json
```

- `204` is the delivered response; there is no body. Read it as success and say so.
- A Python `urllib.request` POST to the same URL fails with `403 error code: 1010` (Cloudflare, TLS/user-agent fingerprint). The webhook is fine; the client is what is blocked.
- Keep the URL in a file or an env var and never echo it; a webhook URL is a capability, and one pasted into chat is burned.
- Payload: `{"username": "<display name>", "embeds": [<embed>]}`.

## The pipeline that is bypassed (why a channel looks empty)

This deployment's webhook channels are fed by its own code: `~/.hermes/web3-harness/src/webhook.ts` (`sendDiscordChannelEmbed`, `broadcastToDiscord`) called from `src/mcp-server.ts` after a staged/signed execution, a BAW agentic trade or an autonomous sell. Consequences to state instead of debugging a phantom bug:

- A transaction executed outside that path (a `baw contract-call` run straight from the CLI, an SDK call from a probe script) lands on chain and posts nothing anywhere. The receipt has to be posted by hand afterwards, in the same shape, so the channel stays a usable log.
- Routing the pipeline uses: `MINT`/`BUY` → `#order-execution` + `#positions` (POSITION_OPENED); `SELL`/`AUTO_SELL`/`EMERGENCY_SELL` → `#order-execution` + `#positions` (POSITION_CLOSED) + `#pnl` (realized). Mirror that when posting manually.
- Webhook env keys: `DISCORD_WEBHOOK_ORDER_EXECUTION` (also the fallback target `DISCORD_TRADE_WEBHOOK_URL`), `DISCORD_WEBHOOK_POSITIONS`, `DISCORD_WEBHOOK_PNL`, read from `~/.hermes/web3-harness/.env`.

## Embed shape `#order-execution` expects

```python
embed = {
  "author": {"name": f"RŮŽE HOUSE  ·  ORDER {action}"},   # action = MINT / BUY / SELL
  "title": asset_name, "url": explorer_tx_url,
  "color": {"BUY": 0x1e1e23, "MINT": 0xc79f53, "CLAIM": 0x10b981,
            "AUTO_SELL": 0xc79f53, "EMERGENCY_SELL": 0xdc3545}[action],
  "fields": [
    {"name": "ACTION",   "value": f"`{action}`",              "inline": True},
    {"name": "NETWORK",  "value": f"`{chain.upper()}`",       "inline": True},
    {"name": "VALUE",    "value": f"`{value_native:.4f} {sym}`", "inline": True},
    {"name": "CONTRACT", "value": f"`{contract}`  ·  Token `{token_id}`"},
    {"name": "SETTLEMENT", "value": f"`{trigger_source}`  ·  [View on Explorer]({explorer_tx_url})"},
  ],
  "footer": {"text": "Pierre Execution Desk  ·  Order Execution"},
  "timestamp": "<ISO-8601 UTC of the tx, not of the post>",
}
```

Username is `Pierre  |  Execution` (two spaces, matching the code). Extra fields are fine when the trade is not a plain swap (position, gate identity, agent id) as long as the five standard ones stay, because the user reads this channel as a feed. Quote the tx timestamp, not the wall clock of the post: a receipt posted an hour after the fact must not look like an order that just fired.

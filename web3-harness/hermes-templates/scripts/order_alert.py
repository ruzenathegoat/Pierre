#!/usr/bin/env python3
"""Order execution alert poster for Discord (#order-execution).

Every order that Pierre executes must announce itself here, whatever tool did the
work: harness MCP tools, a direct `baw` CLI call, a viem script, or a cron job.

Usage:
  order_alert.py --action MINT --chain BSC --asset "Agentic Coin (AGC)" \
      --value "0.0100 BNB" --contract 0x6288… --tx 0x… \
      --source BAW_AGENTIC_WALLET_AI --note "5 share = 1,400,000 AGC" \
      --tx-url https://bscscan.com/tx/0x… [--also positions,pnl] [--dry-run]

Exit codes: 0 delivered (or dry-run), 1 delivery failed, 2 bad arguments.
An order that does not appear in #order-execution is an unlogged order, so a
failed post exits non-zero and is visible to cron.
"""
import argparse
import json
import os
import subprocess
import sys

ENV_PATH = os.path.expanduser("~/.hermes/web3-harness/.env")

# Mirrors ACTION_COLORS in ~/.hermes/web3-harness/src/webhook.ts. Keep in sync.
COLORS = {
    "BUY": 0x1E1E23,            # Obsidian Slate
    "MINT": 0xC79F53,           # Champagne Gold
    "CLAIM": 0x10B981,          # Emerald
    "AUTO_SELL": 0xC79F53,
    "EMERGENCY_SELL": 0xDC3545,
    "SELL": 0xC79F53,
    "TRANSFER": 0x3B82F6,       # Signal Blue
    "SWAP": 0x8B5CF6,           # Violet
    "APPROVE": 0x64748B,        # Slate
    "LP_ADD": 0x14B8A6,         # Teal
    "LP_REMOVE": 0xE11D48,      # Rose
    "CONTRACT_CALL": 0x64748B,
}

EXPLORERS = {
    "BSC": "https://bscscan.com/tx/",
    "BNB": "https://bscscan.com/tx/",
    "ETH": "https://etherscan.io/tx/",
    "ETHEREUM": "https://etherscan.io/tx/",
    "BASE": "https://basescan.org/tx/",
    "POLYGON": "https://polygonscan.com/tx/",
    "ARBITRUM": "https://arbiscan.io/tx/",
}

# webhook env key per delivery channel
CHANNELS = {
    "order-execution": ("DISCORD_WEBHOOK_ORDER_EXECUTION", "DISCORD_TRADE_WEBHOOK_URL"),
    "positions": ("DISCORD_WEBHOOK_POSITIONS", None),
    "pnl": ("DISCORD_WEBHOOK_PNL", None),
}

USERNAMES = {
    "order-execution": "Pierre  |  Execution",
    "positions": "Pierre  |  Positions",
    "pnl": "Pierre  |  PnL",
}


def load_env():
    env = {}
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k, v in os.environ.items():
        if k.startswith("DISCORD_"):
            env[k] = v
    return env


def resolve_webhook(env, channel):
    for key in CHANNELS[channel]:
        if key and env.get(key):
            return env[key]
    return None


def build_embed(a):
    """Clean native embed: headline, a few inline facts, contract, explorer buttons."""
    chain = a.chain.upper()
    base = EXPLORERS.get(chain)
    url = a.tx_url or (f"{base}{a.tx}" if base and a.tx else None)
    head = f"**{a.action.upper().replace('_', ' ')}**"
    if a.value:
        head += f"  {a.value}"
    head += f"  \u00b7  {chain}"
    extra = []
    fields = []
    for note in a.note or []:
        if "=" in note:
            k, v = note.split("=", 1)
            fields.append({"name": k.strip().title(), "value": v.strip(), "inline": True})
        else:
            extra.append(note)
    if a.source:
        fields.append({"name": "Source", "value": f"`{a.source}`", "inline": True})
    if a.tx:
        fields.append({"name": "Tx", "value": f"`{a.tx[:8]}\u2026{a.tx[-6:]}`" if len(a.tx) > 18 else f"`{a.tx}`",
                       "inline": True})
    if a.contract:
        token = f"  \u00b7  Token `{a.token_id}`" if a.token_id else ""
        fields.append({"name": "Contract", "value": f"`{a.contract}`{token}", "inline": False})
    embed = {
        "author": {"name": "R\u016e\u017dE HOUSE"},
        "title": a.asset,
        "description": "\n".join([head] + extra),
        "color": COLORS.get(a.action.upper(), 0x1E1E23),
        "fields": fields[:25],
        "footer": {"text": "Pierre Execution Desk"},
    }
    buttons = []
    if url:
        embed["url"] = url
        buttons.append(("View transaction", url))
    if a.contract and base:
        buttons.append(("Contract", base.replace("/tx/", "/address/") + a.contract))
    if buttons:
        embed["_buttons"] = buttons
    if a.timestamp:
        embed["timestamp"] = a.timestamp
    else:
        import datetime as _dt
        embed["timestamp"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    return embed


def post(url, payload, wait=False):
    """Deliver via pierre_ui.post (curl, multipart when a card is attached).

    Always asks Discord for the created message (?wait=true), so a message id
    proves the order was announced. Returns (delivered, http_code, message_id).
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pierre_ui as ui
    return ui.post(url, payload["username"], payload["embeds"], wait=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--action", help="MINT/BUY/SELL/SWAP/TRANSFER/CLAIM/APPROVE/LP_ADD/LP_REMOVE/CONTRACT_CALL")
    p.add_argument("--asset")
    p.add_argument("--chain", default="BSC")
    p.add_argument("--value")
    p.add_argument("--contract")
    p.add_argument("--token-id")
    p.add_argument("--tx")
    p.add_argument("--tx-url")
    p.add_argument("--source", default="PIERRE_EXECUTION")
    p.add_argument("--note", action="append", help="'LABEL=value' (repeatable) or free text")
    p.add_argument("--inline-notes", action="store_true")
    p.add_argument("--timestamp")
    p.add_argument("--also", default="", help="extra channels: positions,pnl")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--check", action="store_true", help="print webhook resolution only, post nothing")
    p.add_argument("--wait", action="store_true",
                   help="ask Discord to return the created message (gives a message id as proof)")
    a = p.parse_args()

    if a.check:
        env = load_env()
        for ch in CHANNELS:
            url = resolve_webhook(env, ch)
            tail = (url.split("/webhooks/")[1].split("/")[0][:6] + "…") if url else None
            print(f"{ch:16s} {'configured ' + tail if url else 'NOT configured'}")
        return 0

    targets = ["order-execution"] + [c.strip() for c in a.also.split(",") if c.strip()]
    if not a.action or not a.asset:
        print("--action and --asset are required (unless --check)", file=sys.stderr)
        return 2
    bad = [c for c in targets if c not in CHANNELS]
    if bad:
        print(f"unknown channel(s): {bad}", file=sys.stderr)
        return 2

    embed = build_embed(a)
    env = load_env()
    if a.dry_run:
        print(json.dumps({"targets": targets, "embed": {k: (f"<png {len(v)} bytes>" if k == "_card" else v) for k, v in embed.items()}}, indent=2, ensure_ascii=False))
        return 0

    failed = []
    for channel in targets:
        url = resolve_webhook(env, channel)
        if not url:
            failed.append(f"{channel}: no webhook configured")
            continue
        ok, code, msg_id = post(url, {"username": USERNAMES[channel], "embeds": [embed]}, wait=a.wait)
        shown = f" (message id {msg_id})" if msg_id else ""
        print(f"{channel}: HTTP {code}{shown} {'delivered' if ok else 'FAILED'}")
        if not ok:
            failed.append(f"{channel}: HTTP {code}")
    if failed:
        print("delivery failed -> " + "; ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

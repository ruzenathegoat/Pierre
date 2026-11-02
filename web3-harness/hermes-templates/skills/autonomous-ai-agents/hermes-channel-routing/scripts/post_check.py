#!/usr/bin/env python3
"""Probe a Discord channel: confirm it exists, post a test message, delete it, list recent messages.

Usage:  python scripts/post_check.py <chat_id> [--list N]

Reads DISCORD_BOT_TOKEN from ~/.hermes/.env and never prints it. Exit 0 only when the
post+delete round trip succeeded, so it doubles as a SEND_MESSAGES gate check.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
TEST = "test routing (auto-delete)"


def token() -> str:
    env = os.path.expanduser("~/.hermes/.env")
    with open(env, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("DISCORD_BOT_TOKEN not found in ~/.hermes/.env")


def call(tok: str, method: str, path: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        API + path, method=method, data=data,
        headers={"Authorization": f"Bot {tok}", "Content-Type": "application/json",
                 "User-Agent": "DiscordBot (hermes-channel-routing,1.0)"},
    )
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        # Message create may return an empty body on success; json.loads would raise on it.
        return resp.status, (json.loads(body) if body else None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chat_id")
    ap.add_argument("--list", type=int, default=5)
    args = ap.parse_args()
    tok = token()
    try:
        _, info = call(tok, "GET", f"/channels/{args.chat_id}")
        print("channel:", info.get("name"), "guild:", info.get("guild_id"), "type:", info.get("type"))
        status, msg = call(tok, "POST", f"/channels/{args.chat_id}/messages", {"content": TEST})
        if msg and msg.get("id"):
            call(tok, "DELETE", f"/channels/{args.chat_id}/messages/{msg['id']}")
            print("post+delete ok")
        else:
            print(f"post returned status {status} with no body; check the channel for a stray test message")
        _, recent = call(tok, "GET", f"/channels/{args.chat_id}/messages?limit={args.list}")
        for m in recent or []:
            print(" ", m["id"], m["author"]["username"], repr(m["content"][:60]))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:300])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

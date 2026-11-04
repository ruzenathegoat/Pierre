#!/usr/bin/env python3
"""OpenSea API v2 key watchdog + auto-rotation for the Pierre web3 harness.

Silent while healthy (cron no_agent job delivers nothing when stdout is empty).
When a rotation, rate-limit, or connection warning occurs (or when invoked with
--send-status), delivers a Minimalist, Clean, Luxury Rich Embed (Zero-Emoji)
directly to the Discord Webhook.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

ENV_PATH = os.path.expanduser("~/.hermes/web3-harness/.env")
STATE_PATH = os.path.expanduser("~/.hermes/web3-harness/.opensea-key-state.json")
PIERRE_WEBHOOK_ENV = os.path.expanduser("~/.hermes/secrets/positions_webhook_pierre.env")
PREVIEW_WEBHOOK_ENV = os.path.expanduser("~/.hermes/secrets/positions_webhook_preview.env")
TEST_URL = "https://api.opensea.io/api/v2/collections?limit=1"
NEW_KEY_URL = "https://api.opensea.io/api/v2/auth/keys"
ROTATE_BEFORE = timedelta(hours=48)
TIMEOUT = 25


OPENSEA_ICON_URL = "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/ethereum/info/logo.png"


def read_webhook_url() -> str:
    for path, keys in [
        (PIERRE_WEBHOOK_ENV, ("WEBHOOK_URL",)),
        (PREVIEW_WEBHOOK_ENV, ("WEBHOOK_URL", "DISCORD_WEBHOOK_PREVIEW_TOKEN")),
        (ENV_PATH, ("DISCORD_WEBHOOK_PREVIEW_TOKEN", "DISCORD_WEBHOOK_POSITIONS")),
    ]:
        if not os.path.exists(path):
            continue
        try:
            content = open(path, encoding="utf-8").read()
            for k in keys:
                m = re.search(rf"^{k}=(.*)$", content, re.M)
                if m:
                    val = m.group(1).strip().strip("'\"")
                    if val.startswith("https://discord.com/api/webhooks/"):
                        return val
        except OSError:
            pass
    return ""


def post_watchdog_embed(
    title: str,
    status_tag: str,
    description: str,
    fields: list[dict],
    color: int = 0xD4AF37,
) -> int:
    url = read_webhook_url()
    if not url:
        return 0
    wib = timezone(timedelta(hours=7))
    ts_wib = datetime.now(wib).strftime("%Y-%m-%d %H:%M WIB")
    payload = {
        "username": "Pierre  |  System Watchdog",
        "embeds": [
            {
                "author": {
                    "name": f"RŮŽE HOUSE  ·  OPENSEA WATCHDOG  ·  {status_tag}",
                    "icon_url": OPENSEA_ICON_URL,
                },
                "title": title,
                "url": "https://opensea.io/settings/developer",
                "thumbnail": {"url": OPENSEA_ICON_URL},
                "description": description,
                "color": color,
                "fields": fields,
                "footer": {
                    "text": f"Pierre Execution Desk  ·  API Key Watchdog  ·  {ts_wib}",
                    "icon_url": OPENSEA_ICON_URL,
                },
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Pierre-Watchdog/1.0")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


def http(url: str, key: str | None = None, method: str = "GET") -> tuple[int, dict | str]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "hermes-pierre/1.0 (web3-harness; +https://opensea.io)")
    if key:
        req.add_header("X-API-KEY", key)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def read_env_key(path: str = ENV_PATH) -> str:
    if not os.path.exists(path):
        return ""
    m = re.search(r"^OPENSEA_API_KEY=(.*)$", open(path, encoding="utf-8").read(), re.M)
    return (m.group(1).strip().strip("'\"") if m else "")


def write_env_key(key: str, path: str = ENV_PATH) -> None:
    content = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if re.search(r"^OPENSEA_API_KEY=.*$", content, re.M):
        content = re.sub(r"^OPENSEA_API_KEY=.*$", f"OPENSEA_API_KEY={key}", content, flags=re.M)
    else:
        content = content.rstrip("\n") + f"\nOPENSEA_API_KEY={key}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def state_read() -> dict:
    try:
        return json.load(open(STATE_PATH, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def state_write(**kw) -> None:
    st = state_read()
    st.update(kw)
    st["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)
        os.chmod(STATE_PATH, 0o600)
    except OSError:
        pass


def parse_expiry(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def probe_harness() -> str:
    """End-to-end check through the same code path the tools use."""
    tsx = os.path.expanduser("~/.hermes/web3-harness/node_modules/.bin/tsx")
    probe = os.path.expanduser("~/.hermes/web3-harness/scripts/opensea_probe.ts")
    if not (os.path.exists(tsx) and os.path.exists(probe)):
        return "error"
    try:
        out = subprocess.run([tsx, probe], capture_output=True, text=True, timeout=90,
                             cwd=os.path.expanduser("~/.hermes/web3-harness"))
    except Exception:  # noqa: BLE001
        return "error"
    txt = (out.stdout or "").strip().splitlines()
    last = txt[-1].strip() if txt else ""
    return last if last in ("opensea-v2", "fallback") else "error"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true", help="print state, never rotate or write")
    ap.add_argument("--send-status", action="store_true", help="post current status embed to Discord webhook")
    args = ap.parse_args()

    key = read_env_key()
    fp = fingerprint(key) if key else ""
    st = state_read()
    expires = parse_expiry(st.get("expires_at")) if st.get("fingerprint") == fp else None
    now = datetime.now(timezone.utc)

    if args.check_only:
        print(json.dumps({
            "has_key": bool(key),
            "key_len": len(key),
            "fingerprint": fp,
            "tracked_expires_at": st.get("expires_at") if expires else None,
            "hours_left": round((expires - now).total_seconds() / 3600, 1) if expires else None,
            "harness_source": probe_harness(),
        }, indent=2))
        return 0

    critical, why = False, ""
    status = 0
    body: dict | str = ""
    if not key:
        critical, why = True, "Missing OPENSEA_API_KEY in .env"
    else:
        status, body = http(TEST_URL, key)
        if status in (401, 403):
            critical, why = True, f"API Rejected Key (HTTP {status})"
        elif status == 429:
            critical, why = True, "API Rate Limit Exceeded (HTTP 429)"
        elif status == 0:
            if st.get("alerted_date") != date.today().isoformat():
                state_write(alerted_date=date.today().isoformat())
                msg = f"**SYSTEM WATCHDOG  ·  OPENSEA FEED**\nStatus: `Connection Check Failed` ({str(body)[:120]})  ·  Action: `No Change`"
                detail_block = (
                    f"Error Detail   :  {str(body)[:140]}\n"
                    f"Action Taken   :  No Rotation (Retrying Next Tick)"
                )
                post_watchdog_embed(
                    "OpenSea v2 Feed Connection Warning",
                    "TRANSIENT WARNING",
                    "> Transient network or Cloudflare error encountered while probing OpenSea API v2.",
                    [
                        {"name": "FEED STATUS", "value": "`CONNECTION FAILED`", "inline": True},
                        {"name": "KEY FINGERPRINT", "value": f"`{fp or 'n/a'}`", "inline": True},
                        {"name": "HARNESS MODE", "value": "`Hot-Reload (.env)`", "inline": True},
                        {"name": "DIAGNOSTIC LOG", "value": f"```yaml\n{detail_block}\n```", "inline": False},
                    ],
                    0xF59E0B,
                )
                print(msg)
            return 0

    if args.send_status:
        hrs = f"{round((expires - now).total_seconds() / 3600, 1)}h" if expires else "Active (HTTP 200)"
        exp_str = st.get("expires_at") if expires else "Auto-Managed (6d Window)"
        detail_block = (
            f"Tracked Expiry :  {exp_str}\n"
            f"Config Path    :  ~/.hermes/web3-harness/.env (Hot-Reload)"
        )
        post_watchdog_embed(
            "OpenSea API v2 Key Telemetry",
            "ACTIVE",
            "> OpenSea API v2 orderbook & Seaport fulfillment feed is authenticated and healthy.",
            [
                {"name": "FEED STATUS", "value": f"`HTTP {status} HEALTHY`", "inline": True},
                {"name": "KEY FINGERPRINT", "value": f"`{fp}`", "inline": True},
                {"name": "WINDOW REMAINING", "value": f"`{hrs}`", "inline": True},
                {"name": "KEY TELEMETRY", "value": f"```yaml\n{detail_block}\n```", "inline": False},
            ],
            0x10B981,
        )
        return 0

    expires_ok = bool(expires) and (expires - now) >= ROTATE_BEFORE
    if not critical and expires_ok:
        return 0  # healthy and expiry tracked: silent, no mint attempt

    if not why:
        why = "Untracked Key Expiry" if not expires else "Approaching 48h Expiry Window"

    nstatus, nbody = http(NEW_KEY_URL, method="POST")
    if nstatus == 200 and isinstance(nbody, dict):
        new_key = nbody.get("api_key") or nbody.get("key") or ""
        if not new_key:
            return 0
        write_env_key(new_key)
        new_exp = nbody.get("expires_at") or (now + timedelta(days=7)).isoformat()
        new_fp = fingerprint(new_key)
        state_write(fingerprint=new_fp, expires_at=new_exp, alerted_date=None,
                    rotated_at=now.isoformat())
        rot_block = (
            f"Rotation Cause :  {why}\n"
            f"New Expiry     :  {new_exp}\n"
            f"Reload Status  :  Hot-Reload Active (.env)"
        )
        post_watchdog_embed(
            "OpenSea API v2 Key Auto-Rotated",
            "KEY ROTATED",
            "> Provisioned a fresh 7-day free-tier OpenSea API v2 key and hot-reloaded `.env`.",
            [
                {"name": "ROTATION STATUS", "value": "`AUTO-ROTATED`", "inline": True},
                {"name": "NEW FINGERPRINT", "value": f"`{new_fp}`", "inline": True},
                {"name": "VALIDITY WINDOW", "value": "`7 Days`", "inline": True},
                {"name": "ROTATION LEDGER", "value": f"```yaml\n{rot_block}\n```", "inline": False},
            ],
            0x10B981,
        )
        print(f"**SYSTEM WATCHDOG  ·  OPENSEA KEY ROTATED**\nReason: `{why}`  ·  New Expiry: `{new_exp}`  ·  Reload: `Hot-Reload Active (.env)`")
        return 0

    # If the existing key works fine (HTTP 200) and we only tried rotating because
    # expires_at was untracked, baseline its expiry for 6 days so we don't hammer
    # POST /api/v2/auth/keys every hour.
    if not critical and key and status == 200 and not expires:
        assumed_exp = (now + timedelta(days=6)).isoformat()
        state_write(fingerprint=fp, expires_at=assumed_exp)
        return 0

    if not critical:
        return 0  # still usable, retry quietly next tick

    today = date.today().isoformat()
    if st.get("alerted_date") == today:
        return 0
    state_write(alerted_date=today)
    err_block = (
        f"Failure Reason :  {why}\n"
        f"Provision HTTP :  HTTP {nstatus}\n"
        f"Remediation    :  Update OPENSEA_API_KEY in ~/.hermes/web3-harness/.env"
    )
    post_watchdog_embed(
        "OpenSea API v2 Rotation Required",
        "ACTION REQUIRED",
        "> Auto-provisioning a new OpenSea API key was rate-limited or blocked. Manual key update required.",
        [
            {"name": "FEED STATUS", "value": "`ACTION REQUIRED`", "inline": True},
            {"name": "PROVISION HTTP", "value": f"`HTTP {nstatus}`", "inline": True},
            {"name": "KEY FINGERPRINT", "value": f"`{fp or 'n/a'}`", "inline": True},
            {"name": "DIAGNOSTIC & REMEDIATION", "value": f"```yaml\n{err_block}\n```", "inline": False},
        ],
        0xEF4444,
    )
    print(f"**SYSTEM WATCHDOG  ·  OPENSEA ROTATION ERROR**\nReason: `{why}`  ·  HTTP `{nstatus}`  ·  `{str(nbody)[:180]}`")
    return 0


if __name__ == "__main__":
    sys.exit(main())

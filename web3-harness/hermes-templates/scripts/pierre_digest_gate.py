#!/usr/bin/env python3
"""Deterministic 15-minute Portfolio & Mint Digest for Pierre (Zero-LLM / no_agent).

Reads OPEN positions from /home/ubuntu/.hermes/web3-harness/trades.db, enriches
each position with live DexScreener orderbook data or on-chain BSC pre-launch
mint metrics, and posts a Minimalist, Clean, Luxury Rich Embed (Zero-Emoji)
directly to the #preview-token Discord Webhook.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request

DB = os.path.expanduser("~/.hermes/web3-harness/trades.db")
PREVIEW_WEBHOOK_ENV = os.path.expanduser("~/.hermes/secrets/positions_webhook_preview.env")
HARNESS_ENV = os.path.expanduser("~/.hermes/web3-harness/.env")
RPCS = ["https://rpc-bsc.48.club", "https://bsc-dataseed.binance.org"]

WALLET_I = "0xbad577476432726c45267e2b57602dd4594a936c"
WALLET_II = "0x74624463e902c11ab37c0034eb216a2b4466269f"
BNBBABY_TOKEN = "0xd0079025a9bb66a7a1de991de2e4326faba35729"
BNBBABY_MINT = "0xbb7ed59ca41ea03cf20084a8c9de94244b7b2637"

_KECCAK_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_KECCAK_ROT = [
    [0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56], [27, 20, 39, 8, 14],
]
_MASK64 = 0xFFFFFFFFFFFFFFFF


def _rol64(x: int, n: int) -> int:
    return ((x << n) | (x >> (64 - n))) & _MASK64


def keccak256_hex(msg: bytes) -> str:
    """Pure-Python Ethereum Keccak-256 (0x01 padding, zero external dependencies)."""
    rate = 136
    buf = bytearray(msg)
    buf.append(0x01)
    while len(buf) % rate != 0:
        buf.append(0x00)
    buf[-1] ^= 0x80
    st = [[0] * 5 for _ in range(5)]
    for off in range(0, len(buf), rate):
        for i in range(rate // 8):
            st[i % 5][i // 5] ^= int.from_bytes(buf[off + i * 8:off + (i + 1) * 8], "little")
        for rc in _KECCAK_RC:
            c = [st[x][0] ^ st[x][1] ^ st[x][2] ^ st[x][3] ^ st[x][4] for x in range(5)]
            d = [c[(x - 1) % 5] ^ _rol64(c[(x + 1) % 5], 1) for x in range(5)]
            for x in range(5):
                for y in range(5):
                    st[x][y] ^= d[x]
            b = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    b[y][(2 * x + 3 * y) % 5] = _rol64(st[x][y], _KECCAK_ROT[x][y])
            for x in range(5):
                for y in range(5):
                    st[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y] & _MASK64)
            st[0][0] ^= rc
    return b"".join(st[i % 5][i // 5].to_bytes(8, "little") for i in range(4)).hex()


def read_webhook_url() -> str:
    for path, keys in [
        (PREVIEW_WEBHOOK_ENV, ("WEBHOOK_URL", "DISCORD_WEBHOOK_PREVIEW_TOKEN")),
        (HARNESS_ENV, ("DISCORD_WEBHOOK_PREVIEW_TOKEN", "DISCORD_WEBHOOK_POSITIONS")),
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


def post_webhook(url: str, payload: dict) -> int:
    if not url:
        return 0
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Pierre-Execution-Desk/1.0")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


def rpc_call(to: str, data: str) -> str | None:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    })
    for u in RPCS:
        try:
            out = subprocess.run(
                ["curl", "-s", "-m", "12", "-X", "POST", u,
                 "-H", "User-Agent: Mozilla/5.0",
                 "-H", "Content-Type: application/json", "-d", payload],
                capture_output=True, text=True, timeout=15
            ).stdout
            res = json.loads(out).get("result")
            if res and res != "0x":
                return str(res)
        except Exception:
            continue
    return None


def keccak_sel(sig: str) -> str:
    return "0x" + keccak256_hex(sig.encode("utf-8"))[:8]


def read_uint(to: str, sigs: list[str]) -> int | None:
    for s in sigs:
        sel = keccak_sel(s)
        if len(sel) < 10:
            continue
        r = rpc_call(to, sel)
        if r:
            try:
                return int(r, 16)
            except ValueError:
                pass
    return None


def fetch_dexscreener(contract_address: str) -> dict | None:
    url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
            pairs = data.get("pairs") or []
            return pairs[0] if pairs else None
    except Exception:
        return None


BSC_LOGO_URL = "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/binance/info/logo.png"
BASE_LOGO_URL = "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/base/info/logo.png"
ETH_LOGO_URL = "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/ethereum/info/logo.png"


def get_chain_logo_url(chain: str) -> str:
    norm = chain.strip().lower()
    if norm == "base":
        return BASE_LOGO_URL
    if norm in ("bsc", "bnb"):
        return BSC_LOGO_URL
    return ETH_LOGO_URL


def build_position_field(row: dict) -> dict:
    pos_id = row.get("id", "?")
    chain = str(row["chain"] or "bsc").upper()
    native_sym = "BNB" if chain == "BSC" else "ETH"
    ca = str(row["contract_address"] or "").lower()
    name = str(row["asset_name"] or "Unknown Asset")
    entry = float(row["entry_price_eth"] or 0.0)
    hwm = float(row["high_water_mark_eth"] or entry)
    wallet_tag = "Wallet II (Agentic .ai)" if row["token_id"] == "BAW_MPC" else "Wallet I (Viem EOA)"
    dex_slug = "bsc" if chain == "BSC" else chain.lower()
    dex_url = f"https://dexscreener.com/{dex_slug}/{ca}"
    scan_url = f"https://bscscan.com/address/{ca}" if chain == "BSC" else f"https://basescan.org/address/{ca}"
    links = f"[DexScreener ↗]({dex_url})  •  [Explorer ↗]({scan_url})"

    pair = fetch_dexscreener(ca)
    if pair:
        price_native = float(pair.get("priceNative") or 0.0)
        price_usd = float(pair.get("priceUsd") or 0.0)
        liq_usd = float((pair.get("liquidity") or {}).get("usd") or 0.0)
        txns_h1 = (pair.get("txns") or {}).get("h1") or {}
        buys = int(txns_h1.get("buys") or 0)
        sells = int(txns_h1.get("sells") or 0)
        vel = "ACCELERATING" if buys > sells * 1.35 else ("DECELERATING" if sells > buys * 1.35 else "STABLE")
        roi_pct = ((price_native - entry) / entry * 100.0) if (entry > 0 and price_native > 0) else 0.0
        drop_pct = ((hwm - price_native) / hwm * 100.0) if (hwm > 0 and price_native > 0) else 0.0
        stance = "SELL CANDIDATE" if (roi_pct >= 30 and drop_pct >= 5) else ("WATCH" if drop_pct >= 5 else "HOLD")
        stance_icon = "🟢" if stance == "HOLD" else ("🟡" if stance == "WATCH" else "🚨")
        roi_sign = "+" if roi_pct >= 0 else ""
        block = (
            f"Wallet         :  {wallet_tag}\n"
            f"Entry / Mark   :  {entry:g} {native_sym}  ->  ${price_usd:g} ({roi_sign}{roi_pct:.1f}% ROI)\n"
            f"Liquidity / 1h :  ${liq_usd:,.0f}  |  {buys} Buy / {sells} Sell ({vel})\n"
            f"Contract       :  {ca}"
        )
        return {
            "name": f"{stance_icon} #{pos_id}  ·  {name}  [{chain}]  —  {stance}",
            "value": f"```yaml\n{block}\n```\n> 🔗 {links}",
            "inline": False,
        }

    # Pre-launch / Fair-Mint on-chain inspection when DexScreener pair is not yet live
    target_mint = BNBBABY_MINT if ca == BNBBABY_TOKEN else ca
    sold = read_uint(target_mint, ["sold()", "paidShares()", "sharesMinted()"])
    max_paid = read_uint(target_mint, ["MAX_SHARES()", "MAX_PAID_SHARES()", "maxShares()"])
    free_claimed = read_uint(target_mint, ["freeClaimed()", "freeMinted()"])
    max_free = read_uint(target_mint, ["MAX_FREE_SHARES()", "FREE_SHARES()"])
    launched = read_uint(target_mint, ["launched()", "poolOpen()"])

    if sold is not None or free_claimed is not None:
        paid_str = f"{sold:,}/{max_paid:,}" if (sold is not None and max_paid) else (f"{sold:,}" if sold is not None else "n/a")
        free_str = f"{free_claimed:,}/{max_free:,}" if (free_claimed is not None and max_free) else "n/a"
        stage_str = "Pool Open" if launched else "Pre-Launch Minting"
        block = (
            f"Wallet         :  {wallet_tag}\n"
            f"Cost Basis     :  {entry:g} {native_sym}  |  Stage: {stage_str}\n"
            f"Pool Progress  :  Paid {paid_str}  |  Free {free_str}\n"
            f"Contract       :  {ca}"
        )
        return {
            "name": f"🟢 #{pos_id}  ·  {name}  [{chain}]  —  HOLD ({stage_str.upper()})",
            "value": f"```yaml\n{block}\n```\n> 🔗 {links}",
            "inline": False,
        }

    block = (
        f"Wallet         :  {wallet_tag}\n"
        f"Cost / HWM     :  {entry:g} {native_sym}  |  HWM {hwm:g} {native_sym}\n"
        f"Stage          :  Awaiting DEX Graduation / Indexing\n"
        f"Contract       :  {ca}"
    )
    return {
        "name": f"🛡️ #{pos_id}  ·  {name}  [{chain}]  —  HOLD (MONITORED)",
        "value": f"```yaml\n{block}\n```\n> 🔗 {links}",
        "inline": False,
    }


def main() -> int:
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except Exception:
        return 0

    try:
        rows = con.execute(
            "SELECT id, chain, asset_type, asset_name, contract_address, token_id, "
            "entry_price_eth, high_water_mark_eth, last_alerted_at, updated_at "
            "FROM positions WHERE status = 'OPEN' ORDER BY id"
        ).fetchall()
    except Exception:
        return 0
    finally:
        con.close()

    if not rows:
        return 0

    cols = [
        "id", "chain", "asset_type", "asset_name", "contract_address", "token_id",
        "entry_price_eth", "high_water_mark_eth", "last_alerted_at", "updated_at",
    ]
    positions = [dict(zip(cols, r)) for r in rows]
    baw_count = sum(1 for p in positions if p.get("token_id") == "BAW_MPC")
    eoa_count = len(positions) - baw_count

    primary_chain = str(positions[0]["chain"] or "bsc")
    chain_logo = get_chain_logo_url(primary_chain)

    header_fields = [
        {"name": "💼 ACTIVE POSITIONS", "value": f"`{len(positions)} Open`", "inline": True},
        {"name": "💳 WALLET SPLIT", "value": f"`{eoa_count} EOA  ·  {baw_count} BAW`", "inline": True},
        {"name": "⏱️ CADENCE", "value": "`20s HWM  ·  15m Digest`", "inline": True},
    ]
    pos_fields = [build_position_field(p) for p in positions[:8]]

    wib = datetime.timezone(datetime.timedelta(hours=7))
    ts_wib = datetime.datetime.now(wib).strftime("%Y-%m-%d %H:%M WIB")

    payload = {
        "username": "Pierre  |  Advisory",
        "embeds": [
            {
                "author": {
                    "name": "RŮŽE HOUSE  ·  PORTFOLIO ADVISORY",
                    "icon_url": chain_logo,
                },
                "title": "🔭 Position Risk & Orderbook Digest",
                "thumbnail": {"url": chain_logo},
                "description": f"> Live orderbook depth and on-chain telemetry for **{len(positions)}** open position(s).",
                "color": 0xD4AF37,
                "fields": header_fields + pos_fields,
                "footer": {
                    "text": f"Pierre Execution Desk  ·  15m Advisory Digest  ·  {ts_wib}",
                    "icon_url": chain_logo,
                },
            }
        ],
    }

    webhook_url = read_webhook_url()
    code = post_webhook(webhook_url, payload)
    if "--verbose" in sys.argv:
        print(f"posted {code} ({len(positions)} positions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

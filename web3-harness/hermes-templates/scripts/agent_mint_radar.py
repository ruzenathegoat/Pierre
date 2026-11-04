#!/usr/bin/env python3
"""Radar for identity-gated agent mints on BSC, tuned for FREE MINT hunting.

Silent by design when no filter trips: prints NOTHING unless a tracked mint
trips Filter D (New Contract), Filter A (New Free Pool), Filter B (Free Pool
Low/Depleted), or Filter C (High Paid Velocity).

When a filter trips:
  1. Sends a Minimalist, Clean, Luxury Rich Embed (Zero-Emoji) directly to the
     Discord Webhook (#agent-mint-radar).
  2. Falls back to stdout plain-text summary if webhook is unavailable.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

STATE = os.path.expanduser("~/.hermes/cache/agent_mint_radar_state.json")
RADAR_WEBHOOK_ENV = os.path.expanduser("~/.hermes/secrets/positions_webhook_radar.env")
HARNESS_ENV = os.path.expanduser("~/.hermes/web3-harness/.env")

RPCS = ["https://rpc-bsc.48.club", "https://bsc-dataseed.binance.org"]
SCAN_BLOCKS = int(os.environ.get("RADAR_SCAN_BLOCKS", "2000"))   # ~25 min of BSC
FRESH_S = int(os.environ.get("RADAR_FRESH_S", "5400"))           # filter A mint age
LOW_LEFT = int(os.environ.get("RADAR_LOW_LEFT", "25"))           # filter B threshold
FREE_WINDOW_S = 6 * 3600
PAID_DELTA = int(os.environ.get("RADAR_PAID_DELTA", "1000"))
PAID_WINDOW_S = 3600
MAX_CANDIDATES = int(os.environ.get("RADAR_MAX_CANDIDATES", "14"))
PAID_REDEDUPE_S = 3 * 3600
FRESH_REDEDUPE_S = 6 * 3600

# Both Dual-Wallet addresses checked for .ai Agent ID / Gate NFT eligibility:
# 1. Wallet II (Binance Agentic Wallet .ai MPC)
# 2. Wallet I  (Viem EOA Self-Custody)
WALLET_LABELS = {
    "0x74624463e902c11ab37c0034eb216a2b4466269f": "Wallet II (Agentic .ai)",
    "0xbad577476432726c45267e2b57602dd4594a936c": "Wallet I  (Viem EOA)   ",
}

WALLETS = [w.strip().lower() for w in os.environ.get(
    "RADAR_WALLETS",
    "0x74624463e902c11ab37c0034eb216a2b4466269f,0xbad577476432726c45267e2b57602dd4594a936c",
).split(",") if w.strip()]

FREE_TOPIC = ""
MINT_TOPIC = ""

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
        (RADAR_WEBHOOK_ENV, ("WEBHOOK_URL", "DISCORD_WEBHOOK_MINT_RADAR")),
        (HARNESS_ENV, ("DISCORD_WEBHOOK_MINT_RADAR",)),
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
    req.add_header("User-Agent", "Pierre-Mint-Radar/1.0")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


def topic(sig: str) -> str:
    return "0x" + keccak256_hex(sig.encode("utf-8"))


def rpc(method: str, params: list, url: str | None = None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    for u in ([url] if url else RPCS):
        out = subprocess.run(["curl", "-s", "-m", "20", "-X", "POST", u,
                              "-H", "User-Agent: Mozilla/5.0",
                              "-H", "Content-Type: application/json", "-d", body],
                             capture_output=True, text=True).stdout
        try:
            r = json.loads(out)
        except Exception:
            continue
        if "error" in r:
            continue
        return r.get("result")
    return None


def sel(sig: str) -> str:
    return topic(sig)[2:10]


def pad(a: str) -> str:
    return a.lower().replace("0x", "").rjust(64, "0")


def call(to: str, data: str) -> str | None:
    r = rpc("eth_call", [{"to": to, "data": data}, "latest"])
    return None if r in (None, "0x") else str(r)


def view(to: str, sig: str, *args: str) -> str | None:
    return call(to, "0x" + sel(sig) + "".join(pad(a) for a in args))


def view_int(to: str, names: list[str]) -> int | None:
    for sig in names:
        r = view(to, sig)
        if r is not None:
            try:
                return int(r, 16)
            except ValueError:
                pass
    return None


def addr_view(to: str, names: list[str]) -> str | None:
    for sig in names:
        r = view(to, sig)
        if r is not None:
            return "0x" + r[-40:]
    return None


def qdecimals(ca: str) -> int:
    """Decimals of the payment token, so price() prints in human units."""
    q = addr_view(ca, ["quote()", "fist()", "paymentToken()"])
    if not q:
        return 18
    return view_int(q, ["decimals()"]) or 18


def sym_of(to: str) -> str:
    r = view(to, "symbol()")
    if r is None:
        return "?"
    b = bytes.fromhex(r[2:])
    off = int.from_bytes(b[:32], "big")
    ln = int.from_bytes(b[off:off + 32], "big")
    return b[off + 32:off + 32 + ln].decode(errors="replace")[:20]


def eligibility(ca: str, wallets: list[str]) -> list[str]:
    """Can each tracked wallet actually call claimFree() on this contract?"""
    gate = addr_view(ca, ["identity()", "gate()", "registry()", "agentIdRegistry()"])
    lines: list[str] = []
    for w in wallets:
        label = WALLET_LABELS.get(w.lower(), f"{w[:6]}...{w[-4:]}").ljust(23)
        ok: bool | None = None
        kind = "Agent ID"
        for sig in ("hasAgentId(address)", "hasIdentity(address)"):
            r = view(ca, sig, w)
            if r is not None:
                ok = int(r, 16) != 0
                break
        if ok is None and gate:
            r = view(gate, "identityOf(address)", w)
            if r is not None:
                ok = int(r, 16) != 0
        if ok is None:
            r = view(ca, "freeAvailable(address)", w)
            if r is not None:
                ok = int(r, 16) != 0
        if ok is None and gate:
            kind = "Gate NFT"
            r = call(gate, "0x" + sel("balanceOf(address)") + pad(w))
            ok = bool(r and int(r, 16) > 0)
        if ok is not None:
            status_str = "ELIGIBLE    " if ok else "NOT ELIGIBLE"
            lines.append(f"{label} :  {status_str} ({kind})")
        else:
            lines.append(f"{label} :  UNVERIFIED")
    return lines


def load_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"contracts": {}, "alerts": {}}


NOSTATE = os.environ.get("RADAR_NOSTATE") == "1" or "--test-webhook" in sys.argv


def save_state(st: dict) -> None:
    if NOSTATE:
        return
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, STATE)


def scan_new_events(latest: int) -> set[str]:
    found: set[str] = set()
    lo = latest - SCAN_BLOCKS
    step, b = 1500, lo
    while b <= latest:
        e = min(b + step - 1, latest)
        for tp in (FREE_TOPIC, MINT_TOPIC):
            for lg in (rpc("eth_getLogs", [{"fromBlock": hex(b), "toBlock": hex(e),
                                            "topics": [tp]}]) or []):
                found.add(lg["address"].lower())
        b = e + 1
    return found


def shares_minted_since(ca: str, blocks_back: int) -> int:
    blk = rpc("eth_blockNumber", [])
    if not blk:
        return 0
    latest = int(str(blk), 16)
    lo = latest - blocks_back
    total, b, step = 0, lo, 1500
    while b <= latest:
        e = min(b + step - 1, latest)
        r = rpc("eth_getLogs", [{"address": ca, "fromBlock": hex(b),
                                 "toBlock": hex(e), "topics": [MINT_TOPIC]}])
        if r is None:
            step = max(300, step // 2)
            continue
        for lg in r:
            total += int(lg["data"][2:66], 16)
        b = e + 1
    return total


def build_embed(
    signal_label: str,
    sym: str,
    ca: str,
    free_kpi: str,
    paid_txt: str,
    price_txt: str,
    age_txt: str,
    telemetry_line: str,
    elig_lines: list[str],
    color: int,
) -> dict:
    wib = datetime.timezone(datetime.timedelta(hours=7))
    ts_wib = datetime.datetime.now(wib).strftime("%Y-%m-%d %H:%M WIB")
    explorer_url = f"https://bscscan.com/address/{ca}"
    telemetry_block = (
        f"Pool Flow      :  {telemetry_line}\n"
        f"Contract       :  {ca}"
    )
    elig_block = "\n".join(elig_lines)
    return {
        "author": {"name": f"RŮŽE HOUSE  ·  AGENT MINT RADAR  ·  {signal_label}"},
        "title": f"{sym}  ·  BSC Identity-Gated Mint",
        "url": explorer_url,
        "description": f"> On-chain `.ai` Agent ID mint radar alert for **{sym}** on **BNB Smart Chain**  ·  [View Contract on BscScan]({explorer_url})",
        "color": color,
        "fields": [
            {"name": "FREE POOL", "value": f"`{free_kpi}`", "inline": True},
            {"name": "PAID POOL", "value": f"`{paid_txt}`", "inline": True},
            {"name": "PRICE & AGE", "value": f"`{price_txt} BNB`  ·  `{age_txt}`", "inline": True},
            {"name": "POOL TELEMETRY & CONTRACT", "value": f"```yaml\n{telemetry_block}\n```", "inline": False},
            {"name": "DUAL-WALLET ELIGIBILITY", "value": f"```yaml\n{elig_block}\n```", "inline": False},
        ],
        "footer": {"text": f"Pierre Execution Desk  ·  BSC Mint Radar  ·  {ts_wib}"},
    }


def main() -> int:
    global FREE_TOPIC, MINT_TOPIC
    FREE_TOPIC = topic("FreeClaimed(address,bytes32)")
    MINT_TOPIC = topic("Minted(address,bytes32,uint256,bytes32)")
    test_mode = "--test-webhook" in sys.argv

    blk = rpc("eth_blockNumber", [])
    if not blk:
        return 0
    latest = int(str(blk), 16)
    st = load_state()
    tracked = st.setdefault("contracts", {})
    alerts = st.setdefault("alerts", {})
    now = int(time.time())

    seen = set(tracked.keys()) if test_mode else scan_new_events(latest)
    for ca in list(tracked):
        if not tracked[ca].get("done"):
            seen.add(ca)
    candidates = [c for c in seen if not tracked.get(c, {}).get("done")][:MAX_CANDIDATES]

    messages: list[str] = []
    embeds: list[dict] = []
    for ca in candidates:
        is_new_contract = ca not in tracked
        t = tracked.setdefault(ca, {"first_seen": now, "hist": [], "free_hist": []})
        t.setdefault("hist", [])
        t.setdefault("free_hist", [])
        if not t.get("sym"):
            t["sym"] = sym_of(ca)

        max_paid = view_int(ca, ["MAX_SHARES()", "MAX_PAID_SHARES()", "PAID_SHARES()"])
        max_free = view_int(ca, ["MAX_FREE_SHARES()", "FREE_SHARES()", "freeShares()"])
        sold = view_int(ca, ["sold()", "paidShares()", "totalPaid()"])
        free = view_int(ca, ["freeClaimed()", "freeMinted()"])
        started = view_int(ca, ["startedAt()", "startTime()", "mintStart()"])
        launched = view_int(ca, ["launched()", "poolOpen()"])
        if max_paid is None and max_free is None:
            continue                       # not this class of contract
        sold = sold or 0
        if launched:
            t["done"] = True
            continue
        if max_free is None or free is None:
            max_free, free = 0, 0

        price = view_int(ca, ["price()", "PRICE()"])
        if price and "qdec" not in t:
            t["qdec"] = qdecimals(ca)
        price_txt = f"{price / 10 ** t.get('qdec', 18):g}" if price else "?"
        paid_txt = f"{sold:,}/{max_paid:,}" if max_paid else f"{sold:,}/?"

        start_ts = started if started else t["first_seen"]
        age = max(0, now - start_ts)
        left = max(0, max_free - free)
        left_pct = (left / max_free * 100) if max_free else 0

        t["hist"].append([now, sold])
        t["hist"] = [h for h in t["hist"] if h[0] >= now - PAID_WINDOW_S * 3][-80:]
        t["free_hist"].append([now, free])
        t["free_hist"] = [h for h in t["free_hist"] if h[0] >= now - 3600][-60:]

        rate: float | None = None
        if len(t["free_hist"]) >= 2 and t["free_hist"][0][1] != free:
            span = max(60, t["free_hist"][-1][0] - t["free_hist"][0][0])
            rate = (free - t["free_hist"][0][1]) / span * 3600.0
        if not rate and free and age > 300:
            rate = free / age * 3600.0
        eta = (left / rate * 60) if (rate and rate > 0 and left) else None
        if eta is not None and eta > 1440:
            eta = None

        free_kpi = f"{free:,}/{max_free:,} ({100 * free / max_free:.0f}%)" if max_free else "None"
        telemetry_line = f"{left:,} free remaining" if max_free else "No free pool"
        if eta is not None and rate is not None:
            telemetry_line += f"  |  Velocity {rate:,.0f}/h (ETA ~{eta:.0f}m)"
        elif rate:
            telemetry_line += f"  |  Velocity {rate:,.0f}/h"

        common = (f"Free Pool: `{free:,} / {max_free:,}` ({100 * free / max_free:.0f}% claimed  ·  `{left:,}` left)"
                  if max_free else "Free Pool: `None`")
        if eta is not None and rate is not None:
            common += f"  ·  Velocity: `{rate:,.0f}/h` (ETA `~{eta:.0f}m`)"
        elif rate:
            common += f"  ·  Velocity: `{rate:,.0f}/h`"

        # ---- filter D: brand-new contract discovered on BSC (or --test-webhook)
        keyD = f"{ca}:seen"
        if (test_mode and len(embeds) < 2) or (is_new_contract and now - alerts.get(keyD, 0) > 86400):
            if not test_mode:
                alerts[keyD] = now
            elig_lines = eligibility(ca, WALLETS)
            sig_label = "RADAR SNAPSHOT" if test_mode else "NEW CONTRACT"
            messages.append(
                f"**MINT RADAR  ·  {sig_label}  ·  {t['sym']}**\n"
                f"Contract: `{ca}`  ·  [BscScan](<https://bscscan.com/address/{ca}>)\n"
                f"{common}\n"
                f"Paid Pool: `{paid_txt}`  ·  Price: `{price_txt}`  ·  Age: `{age / 60:.0f}m`\n"
                + "\n".join(f"Eligibility: {line}" for line in elig_lines)
            )
            embeds.append(build_embed(
                sig_label, t["sym"], ca, free_kpi, paid_txt, price_txt,
                f"{age / 60:.0f}m", telemetry_line, elig_lines, 0xD4AF37 if left == 0 else 0x10B981
            ))
            if test_mode and len(embeds) >= 2:
                break

        # ---- filter A: fresh mint, free room still available (the actionable one)
        keyA = f"{ca}:fresh"
        if left and age <= FRESH_S and left_pct >= LOW_LEFT and now - alerts.get(keyA, 0) > FRESH_REDEDUPE_S:
            alerts[keyA] = now
            elig_lines = eligibility(ca, WALLETS)
            messages.append(
                f"**MINT RADAR  ·  NEW FREE POOL  ·  {t['sym']}**\n"
                f"Contract: `{ca}`  ·  [BscScan](<https://bscscan.com/address/{ca}>)\n"
                f"{common}\n"
                f"Paid Pool: `{paid_txt}`  ·  Price: `{price_txt}`  ·  Age: `{age / 60:.0f}m`\n"
                + "\n".join(f"Eligibility: {line}" for line in elig_lines)
            )
            embeds.append(build_embed(
                "NEW FREE POOL", t["sym"], ca, free_kpi, paid_txt, price_txt,
                f"{age / 60:.0f}m", telemetry_line, elig_lines, 0x10B981
            ))
            continue

        # ---- filter B: free pool about to run out (or just ran out)
        keyB = f"{ca}:low"
        if (max_free and age <= FREE_WINDOW_S
                and (left == 0 or left_pct < LOW_LEFT)
                and now - alerts.get(keyB, 0) > FREE_WINDOW_S):
            alerts[keyB] = now
            elig_lines = eligibility(ca, WALLETS)
            sig_b = "FREE POOL DEPLETED" if left == 0 else f"FREE POOL LOW ({left_pct:.0f}% LEFT)"
            messages.append(
                f"**MINT RADAR  ·  {sig_b}  ·  {t['sym']}**\n"
                f"Contract: `{ca}`  ·  [BscScan](<https://bscscan.com/address/{ca}>)\n"
                f"{common}  ·  Age: `{age / 3600:.1f}h`\n"
                + "\n".join(f"Eligibility: {line}" for line in elig_lines)
            )
            embeds.append(build_embed(
                sig_b, t["sym"], ca, free_kpi, paid_txt, price_txt,
                f"{age / 3600:.1f}h", telemetry_line, elig_lines, 0x64748B if left == 0 else 0xF59E0B
            ))

        # ---- filter C: paid velocity (sellout closes the free lane)
        old = [h for h in t["hist"] if h[0] <= now - PAID_WINDOW_S]
        if old:
            base = old[-1][1]
        elif len(t["hist"]) <= 1:
            base = max(0, sold - shares_minted_since(ca, int(PAID_WINDOW_S / 0.75)))
        else:
            base = t["hist"][0][1]
        delta = sold - base
        keyC = f"{ca}:paid"
        if delta >= PAID_DELTA and now - alerts.get(keyC, 0) > PAID_REDEDUPE_S:
            alerts[keyC] = now
            elig_lines = eligibility(ca, WALLETS)
            messages.append(
                f"**MINT RADAR  ·  HIGH PAID VELOCITY  ·  {t['sym']}**\n"
                f"Contract: `{ca}`  ·  [BscScan](<https://bscscan.com/address/{ca}>)\n"
                f"Paid Delta: `+{delta:,}` in `{PAID_WINDOW_S // 60}m` (Total `{paid_txt}`)\n"
                f"{common}"
            )
            embeds.append(build_embed(
                f"HIGH PAID VELOCITY (+{delta:,}/1H)", t["sym"], ca, free_kpi, paid_txt, price_txt,
                f"{age / 60:.0f}m", f"Paid Surge +{delta:,}/1h  |  {telemetry_line}", elig_lines, 0xD4AF37
            ))

    if len(alerts) > 4000:
        st["alerts"] = {k: v for k, v in alerts.items() if now - v < 30 * 86400}
    save_state(st)

    wh_code = 0
    if embeds:
        webhook_url = read_webhook_url()
        wh_code = post_webhook(webhook_url, {
            "username": "Pierre  |  Mint Radar",
            "embeds": embeds[:6],
        })

    if messages and (wh_code not in (200, 204) or "--verbose" in sys.argv):
        print("\n\n".join(messages[:6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

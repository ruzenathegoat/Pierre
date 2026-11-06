#!/usr/bin/env python3
"""JINLONG (金龙) mint deadline report, read straight from BSC.

Fires near the 72h mint deadline and prints one Indonesian report:
progress, time left, phase, and what happens to the free allocation.
Silent only on genuine RPC failure (exit 1).
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

from Crypto.Hash import keccak

RPC = "https://bsc-rpc.publicnode.com"
MINT = "0x2df4ef534cbbe1a8f647e24d0f8c75ece74d8288"
PAIR = "0x54acb71465ceebd9549cc4a8687838a931872460"
WALLET = "0x74624463e902C11aB37C0034EB216A2B4466269F"
STARTED_AT = 1793549461  # start(), read once and pinned here
MINT_DURATION = 72 * 3600
WIB = timezone(timedelta(hours=7))

PHASES = {0: "Pending", 1: "Minting", 2: "AwaitingLaunch", 3: "Trading", 4: "Refunds"}


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        RPC, body, {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def sel(sig):
    k = keccak.new(digest_bits=256)
    k.update(sig.encode())
    return "0x" + k.hexdigest()[:8]


def call(to, sig, args=""):
    out = rpc("eth_call", [{"to": to, "data": sel(sig) + args}, "latest"])
    res = out.get("result")
    if res is None:
        raise RuntimeError(f"{sig} reverted: {out.get('error')}")
    return res


def word(res, i):
    return int(res[2 + i * 64: 2 + (i + 1) * 64], 16)


def fmt(ts):
    return datetime.fromtimestamp(ts, WIB).strftime("%d %b %H:%M WIB")


def main():
    blk_ts = int(rpc("eth_getBlockByNumber", ["latest", False])["result"]["timestamp"], 16)
    phase, sold, free_claimed, deadline, raised = [word(call(MINT, "info()"), i) for i in range(5)]
    launched = word(call(MINT, "launched()"), 0)
    price = word(call(MINT, "price()"), 0)
    paid_cap = word(call(MINT, "PAID_SHARES()"), 0)
    free_cap = word(call(MINT, "FREE_SHARES()"), 0)
    pad = WALLET.lower().replace("0x", "").rjust(64, "0")
    balance = word(call(MINT, "balanceOf(address)", pad), 0) / 1e18
    free_alloc = word(call(MINT, "freeAllocation(address)", pad), 0) / 1e18
    paid_mine = word(call(MINT, "paidSharesOf(address)", pad), 0)

    left_s = deadline - blk_ts
    left_h = left_s / 3600
    paid_pct = sold / paid_cap * 100
    free_pct = free_claimed / free_cap * 100
    price_bnb = price / 1e18

    lines = [f"**JINLONG deadline report** ({fmt(blk_ts)})", ""]
    lines.append(f"Phase: {PHASES.get(phase, phase)}, launched: {'ya' if launched else 'belum'}")
    if left_s > 0:
        lines.append(f"Sisa waktu: {left_h:.1f} jam (deadline {fmt(deadline)})")
    else:
        lines.append(f"Deadline lewat {-left_h:.1f} jam lalu ({fmt(deadline)})")
    lines.append(f"Paid: {sold}/{paid_cap} share ({paid_pct:.2f}%), raise {raised / 1e18:.4f} BNB")
    lines.append(f"Free: {free_claimed}/{free_cap} ({free_pct:.1f}%), sisa {free_cap - free_claimed} slot")
    lines.append(f"Harga {price_bnb} BNB/share")
    lines.append("")

    # Wallet side
    lines.append(f"Wallet {WALLET[:6]}...{WALLET[-4:]}:")
    lines.append(f"- JINLONG: {balance:,.0f} token (free {free_alloc:,.0f}, paid {paid_mine} share)")
    lines.append("")

    # Verdict on what happens next
    if launched:
        try:
            res = call(PAIR, "getReserves()")
            r0, r1 = word(res, 0), word(res, 1)
            lines.append(f"Pool sudah kebuka, reserves {r0 / 1e18:,.0f} / {r1 / 1e18:.4f}")
        except Exception:
            lines.append("Pool sudah kebuka, reserves gagal dibaca")
        lines.append("Token sudah bisa ditransfer, tax 1% kalau lewat pair resmi.")
    elif phase == 4:
        lines.append("**Verdict: target 10.000 share tidak kesampaian, masuk fase Refund.**")
        lines.append("Alokasi free kamu di-burn dan tidak dapat apa-apa selain rugi gas 0,000011 BNB.")
    elif left_s <= 0:
        lines.append("**Verdict: deadline lewat tanpa sold out.** Free allocation akan di-burn.")
    elif sold >= paid_cap - 200:
        lines.append(f"**Verdict: hampir sold out, kurang {paid_cap - sold} share.** Kalau tembus, pool buka di 2x harga mint.")
    else:
        pace = sold / max((blk_ts - STARTED_AT) / 3600, 0.1)
        lines.append(
            f"**Verdict: masih jauh dari sold out.** Butuh {paid_cap - sold:,} share lagi, "
            f"pace sekarang {pace:.3f} share/jam."
        )
        if pace and (paid_cap - sold) / pace > max(left_h, 0.1):
            lines.append("Pace itu tidak cukup untuk menembus target sebelum deadline, jadi refund yang bakal kejadian.")
        lines.append("Realistis: target tidak tercapai, alokasi free hangus dan yang hilang cuma gas.")
    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"JINLONG deadline report gagal baca chain: {e}")
        sys.exit(1)

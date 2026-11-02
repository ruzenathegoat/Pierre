#!/usr/bin/env python3
"""Radar for identity-gated agent mints on BSC, tuned for FREE MINT hunting.

Silent by design: prints NOTHING unless a tracked mint trips a filter. Empty
stdout + exit 0 is the healthy case, so this never spams the channel.

Why the filters look like this (measured on the FAGENT mint, 1 Nov 2026):
its 4,444 free shares were 50% gone at 2.34h and 100% gone at 2.85h after
`startedAt()`, while the paid pool took 8.14h to sell out. An alert that fires
at "90% claimed" leaves ~12 minutes to act, so the useful signal is a mint that
has just OPENED with free room left.

Filter A  mint opened inside FRESH_S and free pool still has >= LOW_LEFT% left
Filter B  free pool dropped under LOW_LEFT% left (heads-up, with ETA to empty)
Filter C  paid shares grew >= PAID_DELTA inside the last 60 minutes
          (a paid sellout closes the free lane immediately)

Every alert carries a per-wallet eligibility line, because this class of mint
gates claimFree() behind an identity (hasAgentId / identityOf / gate NFT). An
alert nobody can act on is noise.
"""
import json
import os
import subprocess
import sys
import time

try:
    from Crypto.Hash import keccak
except ImportError:
    sys.exit(0)          # silent: a cron crash here must not page anyone

STATE = os.path.expanduser("~/.hermes/cache/agent_mint_radar_state.json")

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

# Wallets whose eligibility is reported in every alert.
# Override with RADAR_WALLETS="0xabc...,0xdef..." once the agentic wallet is added.
WALLETS = [w.strip().lower() for w in os.environ.get(
    "RADAR_WALLETS",
    "0xbad577476432726c45267e2b57602dd4594a936c",   # self-custody (web3-harness)
).split(",") if w.strip()]

FREE_TOPIC = None
MINT_TOPIC = None


def topic(sig):
    k = keccak.new(digest_bits=256)
    k.update(sig.encode())
    return "0x" + k.hexdigest()


def rpc(method, params, url=None):
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


def sel(sig):
    return topic(sig)[2:10]


def pad(a):
    return a.lower().replace("0x", "").rjust(64, "0")


def call(to, data):
    r = rpc("eth_call", [{"to": to, "data": data}, "latest"])
    return None if r in (None, "0x") else r


def view(to, sig, *args):
    return call(to, "0x" + sel(sig) + "".join(pad(a) for a in args))


def view_int(to, names):
    for sig in names:
        r = view(to, sig)
        if r is not None:
            try:
                return int(r, 16)
            except ValueError:
                pass
    return None


def addr_view(to, names):
    for sig in names:
        r = view(to, sig)
        if r is not None:
            return "0x" + r[-40:]
    return None


def qdecimals(ca):
    """Decimals of the payment token, so price() prints in human units."""
    q = addr_view(ca, ["quote()", "fist()", "paymentToken()"])
    if not q:
        return 18
    return view_int(q, ["decimals()"]) or 18


def sym_of(to):
    r = view(to, "symbol()")
    if r is None:
        return "?"
    b = bytes.fromhex(r[2:])
    off = int.from_bytes(b[:32], "big")
    ln = int.from_bytes(b[off:off + 32], "big")
    return b[off + 32:off + 32 + ln].decode(errors="replace")[:20]


def eligibility(ca, wallets):
    """Can each tracked wallet actually call claimFree() on this contract?"""
    gate = addr_view(ca, ["identity()", "gate()", "registry()", "agentIdRegistry()"])
    lines = []
    for w in wallets:
        ok, kind = None, "Agent ID"
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
            kind = "gate NFT"
            r = call(gate, "0x" + sel("balanceOf(address)") + pad(w))
            ok = bool(r and int(r, 16) > 0)
        lines.append(f"{'ELIGIBLE' if ok else 'TIDAK eligible'} ({kind}) `{w}`"
                     if ok is not None else f"eligibilitas tidak kebaca `{w}`")
    return lines


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {"contracts": {}, "alerts": {}}


NOSTATE = os.environ.get("RADAR_NOSTATE") == "1"   # manual test mode: never burn dedupe keys


def save_state(st):
    if NOSTATE:
        return
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, STATE)


def scan_new_events(latest):
    found = set()
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


def shares_minted_since(ca, blocks_back):
    latest = int(rpc("eth_blockNumber", []), 16)
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


def main():
    global FREE_TOPIC, MINT_TOPIC
    FREE_TOPIC = topic("FreeClaimed(address,bytes32)")
    MINT_TOPIC = topic("Minted(address,bytes32,uint256,bytes32)")

    latest = int(rpc("eth_blockNumber", []), 16)
    st = load_state()
    tracked = st.setdefault("contracts", {})
    alerts = st.setdefault("alerts", {})
    now = int(time.time())

    seen = scan_new_events(latest)
    for ca in list(tracked):
        if not tracked[ca].get("done"):
            seen.add(ca)
    candidates = [c for c in seen if not tracked.get(c, {}).get("done")][:MAX_CANDIDATES]

    messages = []
    for ca in candidates:
        t = tracked.setdefault(ca, {"first_seen": now, "hist": [], "free_hist": []})
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
        age = now - start_ts
        left = max(0, max_free - free)
        left_pct = (left / max_free * 100) if max_free else 0

        t["hist"].append([now, sold])
        t["hist"] = [h for h in t["hist"] if h[0] >= now - PAID_WINDOW_S * 3][-80:]
        t["free_hist"].append([now, free])
        t["free_hist"] = [h for h in t["free_hist"] if h[0] >= now - 3600][-60:]

        # free-claim rate from observed ticks, else from the mint's own age
        rate = None
        if len(t["free_hist"]) >= 2 and t["free_hist"][0][1] != free:
            span = max(60, t["free_hist"][-1][0] - t["free_hist"][0][0])
            rate = (free - t["free_hist"][0][1]) / span * 3600.0
        if not rate and free and age > 300:
            rate = free / age * 3600.0
        eta = (left / rate * 60) if (rate and rate > 0 and left) else None
        if eta is not None and eta > 1440:
            eta = None       # too slow to be a deadline; the rate line already tells the story

        common = (f"Free Pool: `{free:,} / {max_free:,}` ({100 * free / max_free:.0f}% claimed  ·  `{left:,}` left)"
                  if max_free else "Free Pool: `None`")
        if eta is not None:
            common += f"  ·  Velocity: `{rate:,.0f}/h` (ETA `~{eta:.0f}m`)"
        elif rate:
            common += f"  ·  Velocity: `{rate:,.0f}/h`"

        # ---- filter A: fresh mint, free room still available (the actionable one)
        keyA = f"{ca}:fresh"
        if left and age <= FRESH_S and left_pct >= LOW_LEFT and now - alerts.get(keyA, 0) > FRESH_REDEDUPE_S:
            alerts[keyA] = now
            messages.append(
                f"**MINT RADAR  ·  NEW FREE POOL  ·  {t['sym']}**\n"
                f"Contract: `{ca}`  ·  [BscScan](<https://bscscan.com/address/{ca}>)\n"
                f"{common}\n"
                f"Paid Pool: `{paid_txt}`  ·  Price: `{price_txt}`  ·  Age: `{age / 60:.0f}m`\n"
                + "\n".join(f"Eligibility: {line}" for line in eligibility(ca, WALLETS))
            )
            continue

        # ---- filter B: free pool about to run out (or just ran out)
        keyB = f"{ca}:low"
        if (max_free and age <= FREE_WINDOW_S
                and (left == 0 or left_pct < LOW_LEFT)
                and now - alerts.get(keyB, 0) > FREE_WINDOW_S):
            alerts[keyB] = now
            head = (f"**MINT RADAR  ·  FREE POOL DEPLETED  ·  {t['sym']}**" if left == 0
                    else f"**MINT RADAR  ·  FREE POOL LOW ({left_pct:.0f}% LEFT)  ·  {t['sym']}**")
            messages.append(
                f"{head}\n"
                f"Contract: `{ca}`  ·  [BscScan](<https://bscscan.com/address/{ca}>)\n"
                f"{common}  ·  Age: `{age / 3600:.1f}h`\n"
                + "\n".join(f"Eligibility: {line}" for line in eligibility(ca, WALLETS))
            )

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
            messages.append(
                f"**MINT RADAR  ·  HIGH PAID VELOCITY  ·  {t['sym']}**\n"
                f"Contract: `{ca}`  ·  [BscScan](<https://bscscan.com/address/{ca}>)\n"
                f"Paid Delta: `+{delta:,}` in `{PAID_WINDOW_S // 60}m` (Total `{paid_txt}`)\n"
                f"{common}"
            )

    if len(alerts) > 4000:
        st["alerts"] = {k: v for k, v in alerts.items() if now - v < 30 * 86400}
    save_state(st)

    if messages:
        print("\n\n".join(messages[:6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

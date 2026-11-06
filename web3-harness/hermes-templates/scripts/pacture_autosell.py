#!/usr/bin/env python3
"""PACTURE exit bot: waits for the mint to sell out, then trails the PancakeSwap V2 pool
and sells the held allocation from the BAW agentic wallet.

Model (see the design agreed with the user):
  - log-price diffusion  d(logS) = mu dt + sigma dW
  - sigma from the realised variance of our own executable-out series
  - mu from net quote inflow / quote reserve (the only un-fakeable demand number)
  - trailing delta = clamp(k * sigma_horizon, delta_min, delta_max)
  - hard overrides: regime flip (mu<0 for 3 windows), depth guard (quote reserve below a
    fraction of the opening level), time cap after pool open

Everything is written to a log + state file. Every real action posts to #order-execution
through order_alert.py. Nothing here signs anything until a trigger actually fires.

  python3 ~/.hermes/scripts/pacture_autosell.py [--dry-run] [--instant-if-mult 0]
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time

# ---- chain config -----------------------------------------------------------
RPC = os.environ.get("PACTURE_RPC", "https://rpc-bsc.48.club")
MINT = "0x95AF9fe16fE5c1741b5E3F1b3b045a8c2470eca9"
TOKEN = "0x10b80088fDAf9363d83671BE66b64f231f9e92f6"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
USDT = "0x55d398326f99059ff775485246999027b3197955"
FACTORY = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
ZERO = "0x0000000000000000000000000000000000000000"
WALLET = "0x74624463e902C11aB37C0034EB216A2B4466269F"
AMOUNT = 40_000_000 * 10**18           # 40M PACTURE held
POOL_FEE = 0.9975                      # PancakeSwap V2 0.25%
DECIMALS = 10**18

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.expanduser("~/.hermes/cache/pacture_autosell.log")
STATE = os.path.expanduser("~/.hermes/cache/pacture_autosell_state.json")
ALERT = os.path.join(HERE, "order_alert.py")
CALldata = os.path.join(HERE, "pacture_swap_calldata.mjs")


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def alert(action, asset, value="", contract="", tx="", source="PACTURE_AUTOSELL", notes=(), also=""):
    cmd = [sys.executable, ALERT, "--action", action, "--chain", "BSC", "--asset", asset,
           "--source", source]
    if value:
        cmd += ["--value", value]
    if contract:
        cmd += ["--contract", contract]
    if tx:
        cmd += ["--tx", tx]
    for n in notes:
        cmd += ["--note", n]
    if also:
        cmd += ["--also", also]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        log(f"alert {action}: rc={p.returncode} {p.stdout.strip()[:200]}")
    except Exception as e:
        log(f"alert {action} FAILED: {e}")


def keccak_sel(sig):
    from Crypto.Hash import keccak
    k = keccak.new(digest_bits=256)
    k.update(sig.encode())
    return "0x" + k.hexdigest()[:8]


def topic(sig):
    from Crypto.Hash import keccak
    k = keccak.new(digest_bits=256)
    k.update(sig.encode())
    return "0x" + k.hexdigest()


def rpc(method, params, tries=4, timeout=15):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    for _ in range(tries):
        out = subprocess.run(["curl", "-s", "--max-time", str(timeout), "-X", "POST", RPC,
                              "-H", "Content-Type: application/json",
                              "-H", "User-Agent: Mozilla/5.0", "--data", body],
                             capture_output=True, text=True).stdout
        try:
            r = json.loads(out)
            if "result" in r:
                return r["result"]
        except Exception:
            pass
        time.sleep(0.6)
    return None


def call(to, data):
    return rpc("eth_call", [{"to": to, "data": data}, "latest"])


def word(res):
    return int(res, 16) if res and res != "0x" else None


def pad(addr):
    return addr.lower().replace("0x", "").rjust(64, "0")


# ---- views ------------------------------------------------------------------
SEL = {n: keccak_sel(n) for n in [
    "soldOut()", "sharesMinted()", "paidShares()", "MAX_SHARES()", "MAX_PAID()",
    "balanceOf(address)", "getPair(address,address)", "getReserves()", "token0()",
    "getAmountsOut(uint256,address[])", "paidBy(address)", "refund()",
]}


def sold_out():
    return word(call(MINT, SEL["soldOut()"])) == 1


def find_pair():
    for quote in (WBNB, USDT):
        r = call(FACTORY, SEL["getPair(address,address)"] + pad(TOKEN) + pad(quote))
        if r and r != "0x":
            a = "0x" + r[-40:]
            if a != ZERO:
                return a.lower(), quote
    return None, None


def reserves(pair, tok_is0=None):
    """Returns (rTok, rQuote). Pass tok_is0 to skip the token0() call (it cannot change)."""
    r = call(pair, SEL["getReserves()"])
    if not r or r == "0x":
        return None
    b = r[2:]
    r0 = int(b[0:64], 16)
    r1 = int(b[64:128], 16)
    if tok_is0 is None:
        t0 = call(pair, SEL["token0()"])
        tok_is0 = ("0x" + t0[-40:]).lower() == TOKEN.lower() if t0 else True
        rTok, rQuote = (r0, r1) if tok_is0 else (r1, r0)
        return rTok, rQuote, tok_is0
    rTok, rQuote = (r0, r1) if tok_is0 else (r1, r0)
    return rTok, rQuote


def our_out(rTok, rQuote, amount=AMOUNT):
    if not rTok or not rQuote:
        return 0.0
    dx = amount * POOL_FEE
    return rQuote * dx / (rTok + dx)


WBNB_USDT_PAIR = "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"
_bnb_px = {"t": 0.0, "v": 0.0}


def bnb_usdt():
    """Live BNB/USDT price from the PancakeSwap WBNB/USDT pair (cached 30s)."""
    if time.time() - _bnb_px["t"] < 30 and _bnb_px["v"]:
        return _bnb_px["v"]
    r = call(WBNB_USDT_PAIR, SEL["getReserves()"])
    if not r or r == "0x":
        return _bnb_px["v"] or 0.0
    b = r[2:]
    r0 = int(b[0:64], 16)
    r1 = int(b[64:128], 16)
    t0 = call(WBNB_USDT_PAIR, SEL["token0()"])
    u_is0 = ("0x" + t0[-40:]).lower() == USDT.lower() if t0 else True
    rU, rB = (r0, r1) if u_is0 else (r1, r0)
    px = (rU / rB) if rB else 0.0
    _bnb_px.update({"t": time.time(), "v": px})
    return px


def swaps_since(pair, from_block, to_block):
    return rpc("eth_getLogs", [{"address": pair,
                                "topics": [topic("Swap(address,uint256,uint256,uint256,uint256,address)")],
                                "fromBlock": hex(from_block), "toBlock": hex(to_block)}]) or []


def decode_swap(log_row, tok_is0):
    """return (quote_in, quote_out) normalised so >0 quote_in means a BUY of PACTURE."""
    d = log_row["data"][2:]
    a0in = int(d[0:64], 16); a1in = int(d[64:128], 16)
    a0out = int(d[128:192], 16); a1out = int(d[192:256], 16)
    if tok_is0:
        tok_in, tok_out = a0in, a0out
        q_in, q_out = a1in, a1out
    else:
        tok_in, tok_out = a1in, a1out
        q_in, q_out = a0in, a0out
    return q_in, q_out


# ---- execution --------------------------------------------------------------
def baw_preview_execute(input_data, value_wei, label):
    prev = subprocess.run(["baw", "contract-call", "preview", "--binanceChainId", "56",
                           "--from", WALLET, "--to", MINT if label == "refund" else ROUTER,
                           "--value", str(value_wei), "--inputData", input_data, "--json"],
                          capture_output=True, text=True, timeout=120)
    try:
        pj = json.loads(prev.stdout)
    except Exception:
        log(f"{label}: preview unparsable: {prev.stdout[:300]} {prev.stderr[:200]}")
        return None
    if not pj.get("success"):
        log(f"{label}: preview failed: {json.dumps(pj)[:400]}")
        return None
    rid = pj["data"]["requestId"]
    log(f"{label}: preview ok requestId={rid}")
    ex = subprocess.run(["baw", "contract-call", "execute", "--requestId", rid, "--json"],
                        capture_output=True, text=True, timeout=180)
    try:
        ej = json.loads(ex.stdout)
    except Exception:
        log(f"{label}: execute unparsable: {ex.stdout[:300]}")
        return None
    if ej.get("success") and ej["data"].get("status") == "BROADCASTED":
        tx = ej["data"]["txHash"]
        log(f"{label}: BROADCASTED {tx}")
        return tx
    log(f"{label}: execute failed: {json.dumps(ej)[:400]}")
    return None


def wait_receipt(tx, timeout=90):
    for _ in range(int(timeout / 3)):
        r = rpc("eth_getTransactionReceipt", [tx])
        if r:
            return r
        time.sleep(3)
    return None


def sell(quote_is_bnb):
    """approve(exact) then swap, both from the agentic wallet. Returns (ok, proceeds_note)."""
    amt = AMOUNT / DECIMALS
    g = subprocess.run(["node", CALldata, "--wallet", WALLET, "--amount", str(int(amt)),
                        "--slippage-bps", "400"], capture_output=True, text=True, timeout=90)
    try:
        cd = json.loads(g.stdout)
    except Exception:
        log(f"sell: calldata builder failed: {g.stdout[:200]} {g.stderr[:300]}")
        alert("AUTO_SELL", "PACTURE exit failed · calldata builder", contract=ROUTER,
              notes=[f"stderr={g.stderr.strip()[:180]}"])
        return False, ""
    log(f"sell: quote per {cd['amountIn']} PACTURE -> {cd['quotedOut']} {cd['quoteToken']} (min {cd['minOut']})")
    tx1 = baw_preview_execute(cd["approveData"], 0, "approve")
    if not tx1:
        alert("AUTO_SELL", "PACTURE exit BLOCKED at approve", contract=ROUTER, notes=["preview/execute refused"])
        return False, ""
    rc = wait_receipt(tx1)
    if not rc or rc.get("status") != "0x1":
        log(f"sell: approve not confirmed ({tx1})")
        alert("AUTO_SELL", "PACTURE exit failed at approve", contract=ROUTER, tx=tx1)
        return False, ""
    alert("APPROVE", f"PACTURE approve {cd['amountIn']} PACTURE -> router", value="0 BNB",
          contract=ROUTER, tx=tx1, notes=[f"minOut={cd['minOut']} {cd['quoteToken']}"])
    tx2 = baw_preview_execute(cd["swapData"], 0, "swap")
    if not tx2:
        alert("AUTO_SELL", "PACTURE exit BLOCKED at swap", contract=ROUTER, notes=[f"approve={tx1}"])
        return False, ""
    rc2 = wait_receipt(tx2)
    if not rc2 or rc2.get("status") != "0x1":
        log(f"sell: swap not confirmed ({tx2})")
        alert("AUTO_SELL", "PACTURE swap reverted", contract=ROUTER, tx=tx2)
        return False, ""
    fee = int(rc2["gasUsed"], 16) * int(rc2["effectiveGasPrice"], 16) / DECIMALS
    unit = "BNB" if quote_is_bnb else "USDT"
    alert("AUTO_SELL", f"PACTURE exit · {cd['amountIn']} PACTURE sold", value=f"~{cd['quotedOut']} {unit}",
          contract=ROUTER, tx=tx2, source="PACTURE_AUTOSELL", also="positions,pnl",
          notes=[f"minOut={cd['minOut']} {unit}", f"gas={fee:.6f} BNB", f"approve={tx1}"])
    log(f"sell: DONE swap={tx2} gas={fee:.6f} BNB")
    return True, f"{cd['quotedOut']} {unit}"


# ---- main -------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="monitor and alert, never sign")
    ap.add_argument("--poll", type=float, default=3.0)
    ap.add_argument("--k", type=float, default=1.5)
    ap.add_argument("--delta-min", type=float, default=0.08)
    ap.add_argument("--delta-max", type=float, default=0.35)
    ap.add_argument("--time-cap", type=float, default=1200.0, help="seconds after pool open")
    ap.add_argument("--depth-guard", type=float, default=0.5, help="exit if quote reserve < x * opening")
    ap.add_argument("--window", type=int, default=20, help="polls per flow window (~1 min)")
    ap.add_argument("--regime-runs", type=int, default=3)
    ap.add_argument("--max-wait", type=float, default=48 * 3600)
    ap.add_argument("--instant-if-mult", type=float, default=0.0,
                    help="sell at open if out >= mult x mint cost (0 = off)")
    ap.add_argument("--be-floor-usd", type=float, default=2.36,
                    help="never sell below this executable exit value in USD "
                         "(break-even floor, 2.36 = the ~1962 USDT pool-quote level; 0 = off)")
    ap.add_argument("--be-floor-usdt", dest="be_floor_usd", type=float,
                    help=argparse.SUPPRESS)  # legacy alias
    args = ap.parse_args()

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log(f"start wallet={WALLET} amount={AMOUNT // DECIMALS} poll={args.poll}s dry_run={args.dry_run}")

    # Phase A: wait for sold-out + pool
    t0 = time.time()
    pair = quote = None
    while time.time() - t0 < args.max_wait:
        if sold_out():
            pair, quote = find_pair()
            if pair:
                break
        time.sleep(20)
    if not pair:
        log("timed out waiting for sold-out + pool")
        alert("CONTRACT_CALL", "PACTURE autosell · no pool appeared", source="PACTURE_AUTOSELL",
              notes=["mint never sold out, or treasury never seeded a pair"])
        return 1
    log(f"sold out; pool {pair} quote={'WBNB' if quote == WBNB else 'USDT'}")

    got = reserves(pair)
    if not got:
        log("no reserves yet"); return 1
    rTok0, rQuote0, tok_is0 = got
    open_out = our_out(rTok0, rQuote0)
    unit = "BNB" if quote == WBNB else "USDT"
    log(f"opening reserves token={rTok0 / DECIMALS:,.0f} quote={rQuote0 / DECIMALS:,.4f} "
        f"-> our exit {open_out / DECIMALS:.4f} {unit}")
    alert("CONTRACT_CALL", "PACTURE pool opened · trailing exit armed",
          contract=pair, source="PACTURE_AUTOSELL",
          notes=[f"pool={rTok0 / DECIMALS:,.0f} PACTURE / {rQuote0 / DECIMALS:,.2f} {unit}",
                 f"our 40M exit at open ~{open_out / DECIMALS:.4f} {unit}",
                 f"rules: trail k={args.k} dmin={args.delta_min} dmax={args.delta_max} cap={args.time_cap:.0f}s"])

    # instant-at-open option
    mint_cost_usdt = 2.0
    if args.instant_if_mult > 0:
        # answer whether the opening print already clears the multiple
        px = None
        if quote == WBNB:
            rr = call("0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae", SEL["getReserves()"])
            if rr and rr != "0x":
                b = rr[2:]
                rU = int(b[0:64], 16) / DECIMALS
                rB = int(b[64:128], 16) / DECIMALS
                px = rU / rB if rB else None
        open_usdt = (open_out / DECIMALS) * px if (quote == WBNB and px) else open_out / DECIMALS
        if open_usdt >= mint_cost_usdt * args.instant_if_mult:
            log(f"instant rule hit: open worth {open_usdt:.2f} USDT >= {args.instant_if_mult}x cost")
            if args.dry_run:
                log("dry-run: would sell at open"); return 0
            ok, note = sell(quote == WBNB)
            return 0 if ok else 1

    last_block = int(rpc("eth_blockNumber", []), 16)
    opening_quote = rQuote0
    hwm = open_out
    outs = []
    flows = []
    neg_run = 0
    t_open = time.time()
    blocked_alerted = False
    blocked_since = 0.0
    last_block_alert = 0.0
    state = {"pair": pair, "hwm": hwm, "opens": []}

    while True:
        time.sleep(args.poll)
        r = reserves(pair, tok_is0)
        if not r:
            continue
        rTok, rQuote = r
        out = our_out(rTok, rQuote)
        outs.append(out)
        if out > hwm:
            hwm = out

        blk = int(rpc("eth_blockNumber", []), 16)
        q_in = q_out = 0
        try:
            for lg in swaps_since(pair, last_block + 1, blk):
                qi, qo = decode_swap(lg, tok_is0)
                q_in += qi
                q_out += qo
        except Exception as e:
            log(f"swap scan error: {e}")
        last_block = blk
        flows.append((q_in - q_out) / DECIMALS)

        elapsed = time.time() - t_open
        # trailing delta from realised vol of our out series
        delta = args.delta_min
        if len(outs) > 30:
            rets = [math.log(outs[i] / outs[i - 1]) for i in range(1, len(outs)) if outs[i - 1] > 0]
            if len(rets) > 5:
                mean = sum(rets) / len(rets)
                var = sum((x - mean) ** 2 for x in rets) / max(1, len(rets) - 1)
                sigma = math.sqrt(var)
                horizon = math.sqrt(max(1, args.window))
                delta = min(args.delta_max, max(args.delta_min, args.k * sigma * horizon))

        # flow window / regime
        mu = None
        if len(flows) >= args.window and rQuote > 0:
            net = sum(flows[-args.window:])
            mu = net / (rQuote / DECIMALS)
            if mu < 0:
                neg_run += 1
            else:
                neg_run = 0

        state.update({"hwm": hwm, "last_out": out, "delta": delta, "mu": mu,
                      "elapsed": elapsed, "quote_reserve": rQuote / DECIMALS, "opens": state["opens"][-200:]})

        trigger = None
        if out <= hwm * (1 - delta):
            trigger = f"trailing stop (out {out / DECIMALS:.4f} <= hwm {hwm / DECIMALS:.4f} * (1-{delta:.3f}))"
        elif neg_run >= args.regime_runs:
            trigger = f"regime flip (net quote outflow {args.regime_runs} windows, mu={mu:.4f})"
        elif rQuote < opening_quote * args.depth_guard:
            trigger = f"depth guard (quote reserve {rQuote / DECIMALS:.2f} < {args.depth_guard:.0%} of open)"
        elif elapsed >= args.time_cap:
            trigger = f"time cap ({args.time_cap:.0f}s after open)"

        if trigger:
            out_usdt = (out / DECIMALS) * (bnb_usdt() if quote == WBNB else 1.0)
            # break-even floor: never realise a loss, hold and re-arm instead
            if args.be_floor_usd > 0 and out_usdt < args.be_floor_usd:
                now = time.time()
                if now - last_block_alert > (600 if blocked_alerted else 1800):
                    last_block_alert = now
                    log(f"BLOCKED by floor: {trigger} | exit ${out_usdt:.2f} < floor ${args.be_floor_usd:.2f} "
                        f"| out={out / DECIMALS:.6f} {unit} qres={rQuote / DECIMALS:,.2f}")
                    alert("CONTRACT_CALL", "PACTURE exit HELD · below break-even floor",
                          source="PACTURE_AUTOSELL",
                          notes=[f"trigger={trigger[:90]}",
                                 f"exit now ${out_usdt:.2f} < floor ${args.be_floor_usd:.2f}",
                                 f"pool quote reserve {rQuote / DECIMALS:,.2f} {unit}",
                                 "bot holds and keeps trailing; no loss realised"])
                blocked_alerted = True
                blocked_since = blocked_since or now
            else:
                log(f"TRIGGER: {trigger} | out={out / DECIMALS:.6f} {unit} (~${out_usdt:.2f}) "
                    f"hwm={hwm / DECIMALS:.6f} (${(hwm / DECIMALS) * (bnb_usdt() if quote == WBNB else 1.0):.2f})")
                with open(STATE, "w") as fh:
                    json.dump(state, fh, indent=2)
                if args.dry_run:
                    log("dry-run: would sell now"); return 0
                ok, note = sell(quote == WBNB)
                return 0 if ok else 1

        if int(elapsed) % 60 < args.poll:
            log(f"t+{elapsed:5.0f}s out={out / DECIMALS:.4f} {unit} hwm={hwm / DECIMALS:.4f} "
                f"delta={delta:.3f} mu={mu if mu is None else round(mu, 4)} qres={rQuote / DECIMALS:,.2f}")


if __name__ == "__main__":
    sys.exit(main())

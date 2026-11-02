#!/usr/bin/env python3
"""Fair-mint / presale screener for BSC (and any EVM with a given RPC).

Two modes:

  # 1. Audit one project from its mint page or its token address
  python3 mint_screener.py audit --url https://fagent.online/mint
  python3 mint_screener.py audit --ca 0x0c876f2F7c44cdE660Ab77BD2022537a305E0220

  # 2. Discover live mints without any site (event-signature watch)
  python3 mint_screener.py discover --blocks 30000

`audit` prints: verified-source flags, live ledger vs page, payment token price,
LP depth and who holds it, the tax-adjusted exit curve, and real participant /
volume concentration from the Minted / FreeClaimed / Swap logs.

`discover` scans recent blocks for the launch event signatures this class of
contract emits (Started, Minted, FreeClaimed, Launched), so new projects are
found on chain before any aggregator lists them.

Only stdlib + pycryptodome.  No API keys.
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections import Counter

try:
    from Crypto.Hash import keccak
except ImportError:
    sys.exit("pip install pycryptodome")

# ---------------------------------------------------------------- primitives
RPCS = [
    "https://rpc-bsc.48.club",
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
]
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
V2_FACTORY = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
USDT = "0x55d398326f99059fF775485246999027B3197955"
DEAD = "0x000000000000000000000000000000000000dead"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def rpc(method, params, url=None):
    for u in ([url] if url else RPCS):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        try:
            out = subprocess.run(["curl", "-s", "-m", "30", "-X", "POST", u,
                                  "-H", "User-Agent: Mozilla/5.0",
                                  "-H", "Content-Type: application/json",
                                  "-d", body], capture_output=True, text=True).stdout
            r = json.loads(out)
        except Exception:
            continue
        if "error" in r:
            continue
        return r.get("result")
    return None


def rpc_strict(method, params, url=None):
    """Like rpc() but reports the node error instead of silently returning None."""
    for u in ([url] if url else RPCS):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        try:
            out = subprocess.run(["curl", "-s", "-m", "30", "-X", "POST", u,
                                  "-H", "User-Agent: Mozilla/5.0",
                                  "-H", "Content-Type: application/json",
                                  "-d", body], capture_output=True, text=True).stdout
            return json.loads(out)
        except Exception:
            continue
    return {"error": {"message": "all rpcs failed"}}


def sel(sig):
    k = keccak.new(digest_bits=256)
    k.update(sig.encode())
    return k.hexdigest()[:8]


def topic(sig):
    k = keccak.new(digest_bits=256)
    k.update(sig.encode())
    return "0x" + k.hexdigest()


def pad(a):
    return a.lower().replace("0x", "").rjust(64, "0")


def _call(to, data):
    r = rpc("eth_call", [{"to": to, "data": data}, "latest"])
    return None if r in (None, "0x") else r


def num(to, sig, *args):
    d = "0x" + sel(sig) + "".join(pad(a) for a in args)
    r = _call(to, d)
    return None if r is None else int(r, 16)


def strv(to, sig):
    r = _call(to, "0x" + sel(sig))
    if r is None:
        return None
    b = bytes.fromhex(r[2:])
    off = int.from_bytes(b[:32], "big")
    ln = int.from_bytes(b[off:off + 32], "big")
    return b[off + 32:off + 32 + ln].decode(errors="replace")


def addrv(to, sig):
    r = _call(to, "0x" + sel(sig))
    if r is None:
        return None
    return "0x" + r[-40:]


def balance_of(token, who):
    r = _call(token, "0x" + sel("balanceOf(address)") + pad(who))
    return None if r is None else int(r, 16)


# Public BSC nodes cap eth_getLogs hard and, worse, some return an empty result for a
# range they simply do not serve (observed on publicnode: a block that has a log returns
# []). So every tier is validated against the contract's own counters before it is
# trusted: sum(Minted shares) must equal sold(), and len(FreeClaimed) must equal
# freeClaimed(). A tier that disagrees is discarded, not printed.
LOG_TIERS = [("https://rpc-bsc.48.club", 4000),
             ("https://bsc-rpc.publicnode.com", 40000),
             ("https://bsc-dataseed.binance.org", 1000)]


def _scan(addr, topics, lo, hi, url, chunk):
    out, b = [], lo
    while b <= hi:
        e = min(b + chunk - 1, hi)
        r = rpc_strict("eth_getLogs", [{"address": addr, "fromBlock": hex(b),
                                        "toBlock": hex(e), "topics": topics}], url)
        if "error" in r:
            return None, r["error"].get("message", "error")
        out += r.get("result", [])
        b = e + 1
    return out, None


def logs_between(addr, topics, lo, hi, url=None, chunk=None):
    """Chunked eth_getLogs with node fallback and explicit failure reporting."""
    tiers = [(url, chunk or 1000)] if url else LOG_TIERS
    last = "no endpoint worked"
    for u, c in tiers:
        res, err = _scan(addr, topics, lo, hi, u, chunk or c)
        if res is not None:
            return res, 0
        last = err
    return [], 1


def collect_validated(ca, lo, hi, sold=None, free=None, pair=None):
    """Scan Minted/FreeClaimed/Swap and only accept a tier that reconciles with chain state."""
    TM = topic("Minted(address,bytes32,uint256,bytes32)")
    TF = topic("FreeClaimed(address,bytes32)")
    TS = topic("Swap(address,uint256,uint256,uint256,uint256,address)")
    for u, ch in LOG_TIERS:
        m, e1 = _scan(ca, [TM], lo, hi, u, ch)
        fc, e2 = _scan(ca, [TF], lo, hi, u, ch)
        if m is None or fc is None:
            print(f"          {u}: {e1 or e2}")
            continue
        paid = sum(word(x["data"], 0) for x in m)
        rec = f"          {u}: Minted {len(m)} = {paid} shares"
        ok = True
        if sold is not None:
            rec += f" (chain sold {sold})"
            ok = ok and paid == sold
        rec += f"  |  FreeClaimed {len(fc)}"
        if free is not None:
            rec += f" (chain freeClaimed {free})"
            ok = ok and len(fc) == free
        print(rec + ("" if ok else "  <- MISMATCH, tier discarded"))
        if ok:
            sw = []
            if pair:
                sw, e3 = _scan(pair, [TS], lo, hi, u, ch)
                sw = sw or []
            return m, fc, sw, u
    return [], [], [], None


def word(data, i):
    return int(data[2 + 64 * i:2 + 64 * (i + 1)], 16)


def ts(sec):
    return dt.datetime.fromtimestamp(sec).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- page scrape
def scrape_page(url):
    """Rendered-free scrape: raw HTML is enough for CA, API paths and agent files."""
    out = subprocess.run(["curl", "-sL", "-m", "30", "-H", "User-Agent: Mozilla/5.0", url],
                         capture_output=True, text=True).stdout
    info = {"ca": None, "apis": [], "contracts": [], "txt": ""}
    info["text"] = re.sub(r"<[^>]+>", " ", out)
    cas = re.findall(r"0x[a-fA-F0-9]{40}", out)
    seen = []
    for c in cas:
        if c.lower() not in [s.lower() for s in seen] and c.lower() != DEAD:
            seen.append(c)
    if seen:
        info["ca"] = seen[0]
    info["contracts"] = seen
    info["apis"] = sorted(set(re.findall(r"['\"`](/api/[a-zA-Z0-9_/\-]+)", out)))
    base = url.rstrip("/").rsplit("/", 1)[0]
    for probe in ["/agent-brief.txt", "/llms.txt", "/mcp.json", "/abi.json"]:
        t = subprocess.run(["curl", "-sL", "-m", "15", base + probe],
                           capture_output=True, text=True).stdout
        if t and not t.lstrip().startswith("<!DOCTYPE") and not t.lstrip().startswith("<html"):
            info["agent_files"] = info.get("agent_files", {})
            info["agent_files"][probe] = t[:4000]
    return info


# ---------------------------------------------------------------- source scan
def sourcify(chain, addr):
    url = f"https://sourcify.dev/server/v2/contract/{chain}/{addr}?fields=sources,abi"
    raw = subprocess.run(["curl", "-sL", "-m", "40", url],
                         capture_output=True, text=True).stdout
    try:
        d = json.loads(raw, strict=False)
    except Exception:
        return None
    if "sources" not in d:
        return None
    return d


def source_flags(d, addr):
    """Pull the constants that decide the economics, and the admin surface."""
    srcs = d["sources"]
    # project files first (node_modules excluded), then everything, so the constants
    # of the sale contract win over OZ library boilerplate.
    proj = {k: v for k, v in srcs.items() if "node_modules" not in k}
    main = "\n".join(v.get("content", "") for v in (proj or srcs).values())
    own = [k for k in proj if not any(x in k.lower() for x in ("erc20.sol", "ierc", "context.sol"))]
    flags_files = own or list(proj)
    flags = {"files": [f.split("/")[-1] for f in flags_files][:8]}
    for name in ["MAX_SHARES", "MAX_FREE_SHARES", "TOTAL_SHARES", "MAX_SUPPLY",
                 "TOKENS_PER_SHARE", "POOL_TOKENS", "PRICE", "MAX_BUY"]:
        m = re.search(name + r"\s*=\s*([^;]+);", main)
        if m:
            flags[name] = m.group(1).strip()
    flags["tax_bps"] = re.findall(r"amount\s*\*\s*(\d+)\s*/\s*10_?000", main)
    flags["owner_funcs"] = re.findall(r"function\s+(\w+)\s*\([^)]*\)[^{;]*onlyOwner", main)
    flags["has_withdraw"] = bool(re.search(r"function\s+\w*(withdraw|rescue|sweep)", main, re.I))
    flags["has_upgrade"] = bool(re.search(r"\b(upgradeTo|UUPS|Initializable|Proxy)\b", main))
    flags["has_pause"] = "setPaused" in main or "paused" in main
    flags["mint_funcs"] = re.findall(r"function\s+(mint\w*|claimFree|forge)\s*\(", main)
    flags["lp_to_dead"] = "DEAD" in main and "pool.mint(DEAD)" in main
    flags["line_count"] = len(main.splitlines())
    return flags, main


# ---------------------------------------------------------------- economics
def stable_prices():
    """BNB and quote-token USD prices straight from PCS stable pairs."""
    bnb = None
    p = rpc("eth_call", [{"to": V2_FACTORY, "data": "0x" + sel("getPair(address,address)")
                          + pad(WBNB) + pad(USDT)}, "latest"])
    if p and int(p, 16):
        pair = "0x" + p[-40:]
        t0 = int(_call(pair, "0x" + sel("token0()")), 16)
        res = _call(pair, "0x" + sel("getReserves()"))
        r0, r1 = word(res, 0), word(res, 1)
        bnb = (r1 / 1e18) / (r0 / 1e18) if t0 == int(WBNB, 16) else (r0 / 1e18) / (r1 / 1e18)
    return bnb


def quote_usd(quote, bnb_usd):
    """Price one payment token in USD via its PCS stable pair, else via WBNB."""
    for base, base_usd in [(USDT, 1.0), (WBNB, bnb_usd)]:
        p = rpc("eth_call", [{"to": V2_FACTORY, "data": "0x" + sel("getPair(address,address)")
                              + pad(quote) + pad(base)}, "latest"])
        if not p or not int(p, 16):
            continue
        pair = "0x" + p[-40:]
        t0 = int(_call(pair, "0x" + sel("token0()")), 16)
        res = _call(pair, "0x" + sel("getReserves()"))
        if res is None:
            continue
        r0, r1 = word(res, 0), word(res, 1)
        dec = num(quote, "decimals()") or 18
        q = quote.lower()
        if t0 == int(q, 16):                      # token0 = quote, token1 = base
            q_amt, b_amt = r0 / 10 ** dec, r1 / 10 ** 18
        else:                                     # token1 = quote, token0 = base
            q_amt, b_amt = r1 / 10 ** dec, r0 / 10 ** 18
        if q_amt <= 0:
            continue
        return b_amt * base_usd / q_amt
    return None


def exit_curve(reserve_token, reserve_quote, shares_total, tokens_per_share,
               sell_tax_bps=0, step_quote=None):
    """Constant-product dump: what the Nth share still receives."""
    rt, rq = reserve_token, reserve_quote
    out, curve = 0.0, {}
    marks = {1, 10, 100, 1000, max(1, shares_total // 4), max(1, shares_total // 2), shares_total}
    for i in range(1, shares_total + 1):
        x = tokens_per_share * (1 - sell_tax_bps / 10000)
        get = rq * x / (rt + x)
        rt += x
        rq -= get
        out += get
        if i in marks:
            curve[i] = (get, out, rq)
    return curve


# ---------------------------------------------------------------- audit
def audit(ca=None, url=None, chain=56, blocks=120000, skip_logs=False, block_override=None):
    print("=" * 74)
    if url:
        pg = scrape_page(url)
        print(f"PAGE      {url}")
        print(f"  CA on page      : {pg['ca']}")
        print(f"  api paths       : {pg['apis'] or 'none'}")
        print(f"  agent files     : {list(pg.get('agent_files', {}).keys()) or 'none'}")
        ca = ca or pg["ca"]
    if not ca:
        sys.exit("no contract address found; pass --ca")
    ca = ca.strip()
    print(f"CONTRACT  {ca}")

    d = sourcify(chain, ca)
    flags = None
    if d:
        flags, src = source_flags(d, ca)
        print("SOURCE    verified on Sourcify")
        for k, v in flags.items():
            print(f"  {k:16}: {v}")
    else:
        print("SOURCE    NOT verified on Sourcify (recover the ABI from the page script)")

    name, sym = strv(ca, "name()"), strv(ca, "symbol()")
    dec = num(ca, "decimals()")
    print(f"TOKEN     {name} / {sym}  decimals={dec}  totalSupply={num(ca,'totalSupply()')}")
    if dec and num(ca, "totalSupply()"):
        print(f"          supply      : {num(ca,'totalSupply()')/10**dec:,.0f}")

    state = {}
    for sig in ["sold()", "freeClaimed()", "launched()", "phase()", "startedAt()",
                "soldOutAt()", "paused()", "refundedShares()", "price()",
                "MAX_SHARES()", "MAX_FREE_SHARES()", "TOKENS_PER_SHARE()",
                "POOL_TOKENS()", "MAX_SUPPLY()"]:
        v = num(ca, sig)
        if v is not None:
            state[sig] = v
    print("LEDGER    " + ", ".join(f"{k.rstrip('()')}={v}" for k, v in state.items()))
    if state.get("startedAt()") and state.get("soldOutAt()"):
        hrs = (state["soldOutAt()"] - state["startedAt()"]) / 3600
        print(f"          mint ran {hrs:.2f}h  ({ts(state['startedAt()'])} -> {ts(state['soldOutAt()'])})")

    owner = addrv(ca, "owner()")
    treasury = addrv(ca, "treasury()")
    quote = addrv(ca, "quote()") or addrv(ca, "fist()") or addrv(ca, "paymentToken()")
    pair = addrv(ca, "pair()")
    print(f"ROLES     owner={owner} treasury={treasury} quote={quote} pair={pair}")

    bnb_usd = stable_prices()
    q_usd = quote_usd(quote, bnb_usd) if quote else None
    print(f"PRICES    BNB=${bnb_usd:,.2f}  quote=${q_usd:.6f}" if (bnb_usd and q_usd) else "PRICES    unknown")

    resc = None
    if pair:
        res = _call(pair, "0x" + sel("getReserves()"))
        t0 = int(_call(pair, "0x" + sel("token0()")), 16)
        if res:
            r0, r1 = word(res, 0), word(res, 1)
            if t0 == int(ca.lower(), 16):
                rt, rq = r0 / 10 ** dec, r1 / 10 ** (num(quote, "decimals()") or 18)
            else:
                rt, rq = r1 / 10 ** dec, r0 / 10 ** (num(quote, "decimals()") or 18)
            lps = num(pair, "totalSupply()")
            dead_pct = (balance_of(pair, DEAD) or 0) / lps * 100 if lps else 0
            if not rt or not rq:
                print(f"POOL      pair {pair} not seeded yet (pre-launch): reserves 0/0")
                if state.get("phase()") is not None:
                    print(f"          phase {state['phase()']} "
                          f"(0 Pending, 1 Minting, 2 AwaitingLaunch, 3 Trading, 4 Refunds)")
                return
            spot = rq / rt
            resc = (rt, rq)
            print(f"POOL      {rt:,.0f} {sym} vs {rq:,.2f} quote"
                  f"  (${rq*q_usd:,.0f})  LP burned {dead_pct:.2f}%")
            print(f"          spot {spot:.3e} quote/{sym}"
                  f"  -> 1 share = {(state.get('TOKENS_PER_SHARE()') or 0)/10**dec*spot:,.4f} quote"
                  f" (${(state.get('TOKENS_PER_SHARE()') or 0)/10**dec*spot*(q_usd or 0):,.4f})")
            price = state.get("price()") or 0
            if price and q_usd:
                print(f"          mint price/share = {price/10**(num(quote,'decimals()') or 18):,.4f} quote"
                      f"  (${price/10**(num(quote,'decimals()') or 18)*q_usd:,.4f})")

    # who holds the tokens that came out of the mint
    for label, addr in [("contract", ca), ("treasury", treasury), ("owner", owner),
                        ("pair", pair), ("dead", DEAD)]:
        if addr:
            b = balance_of(ca, addr)
            if b:
                usd = ""
                if resc and q_usd and resc[0] > 0:
                    usd = f"  (~${b/10**dec*(resc[1]/resc[0])*q_usd:,.0f} at spot)"
                print(f"BALANCE   {label:9} {addr} {b/10**dec:,.0f} {sym}{usd}")

    if skip_logs:
        return

    latest = int(rpc("eth_blockNumber", []), 16)
    lo = block_override or (latest - blocks)
    sold, free = state.get("sold()"), state.get("freeClaimed()")
    m, fc, sw = [], [], []
    for attempt in range(4):
        print(f"LOGS      scanning {lo}..{latest} ({latest - lo} blocks)")
        m, fc, sw, used = collect_validated(ca, lo, latest, sold, free, pair)
        if used:
            break
        lo -= 60000      # counters disagreed: widen backwards instead of quoting a short count
    if m:
        payers = Counter()
        for x in m:
            payers["0x" + x["topics"][1][-40:]] += word(x["data"], 0)
        print(f"          paid wallets {len(payers)}  shares {sum(payers.values())}"
              f"  top {payers.most_common(3)}")
        print(f"          shares/wallet histogram {sorted(Counter(payers.values()).items())[:12]}")
    if fc:
        recv = Counter("0x" + x["topics"][1][-40:] for x in fc)
        print(f"          free claimers {len(recv)} unique, max/free per wallet {max(recv.values())}")

    if sw:
        send, vol, tos = Counter(), {}, Counter()
        for x in sw:
            s_ = "0x" + x["topics"][1][-40:]
            t_ = "0x" + x["topics"][2][-40:] if len(x["topics"]) > 2 else ""
            v = (word(x["data"], 1) + word(x["data"], 3))
            send[s_] += 1
            vol[s_] = vol.get(s_, 0) + v
            tos[t_] += 1
        qd = num(quote, "decimals()") or 18
        tot = sum(vol.values()) / 10 ** qd
        print(f"SWAPS     {len(sw)} swaps  volume {tot:,.0f} quote (${tot*(q_usd or 0):,.0f})"
              f"  senders {len(send)}  recipients {len(tos)}")
        print(f"          busiest sender {send.most_common(1)[0]}"
              f"  = {send.most_common(1)[0][1]/len(sw)*100:.0f}% of swaps")

    # exit curve
    if resc and state.get("MAX_SHARES()"):
        tps = (state.get("TOKENS_PER_SHARE()") or 0) / 10 ** dec
        total_shares = state["MAX_SHARES()"] + (state.get("MAX_FREE_SHARES()") or 0)
        tax = 0
        if flags and flags.get("tax_bps"):
            tax = sum(int(x) for x in flags["tax_bps"] if int(x) < 1000)
        cur = exit_curve(resc[0], resc[1],total_shares, tps, tax)
        print(f"EXIT      dumping all {total_shares} shares into the pool (sell tax {tax/100:g}%):")
        for n, (one, cum, left) in cur.items():
            print(f"          after {n:>6} shares: last gets {one:,.4f} quote"
                  f" (${one*(q_usd or 0):,.2f})   cumulative ${cum*(q_usd or 0):,.0f}"
                  f"   pool left ${left*(q_usd or 0):,.0f}")


# ---------------------------------------------------------------- discover
WATCH = {
    topic("Started(uint256)"): "Started",
    topic("Minted(address,bytes32,uint256,bytes32)"): "Minted(agent-gated)",
    topic("FreeClaimed(address,bytes32)"): "FreeClaimed(agent-gated)",
    topic("Launched(address,uint256)"): "Launched(pool built)",
    topic("FreeClaimed(address,uint256)"): "FreeClaimed(generic)",
}


def discover(blocks=30000, chunk=1500):
    latest = int(rpc("eth_blockNumber", []), 16)
    lo = latest - blocks
    print(f"watching blocks {lo}..{latest} for fair-launch signatures")
    hits = Counter()
    examples = {}
    b = lo
    while b <= latest:
        e = min(b + chunk - 1, latest)
        for tp, label in WATCH.items():
            r = rpc_strict("eth_getLogs", [{"fromBlock": hex(b), "toBlock": hex(e),
                                            "topics": [tp]}])
            if "error" in r or not r:
                continue
            for lg in r.get("result", []):
                key = (label, lg["address"].lower())
                hits[key] += 1
                examples.setdefault(key, int(lg["blockNumber"], 16))
        b = e + 1
    if not hits:
        print("no launches in window")
        return
    for (label, addr), n in hits.most_common(40):
        print(f"  {label:24} {addr}  events={n}  first_block={examples[(label,addr)]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--ca")
    a.add_argument("--url")
    a.add_argument("--chain", type=int, default=56)
    a.add_argument("--blocks", type=int, default=120000)
    a.add_argument("--from-block", type=int)
    a.add_argument("--skip-logs", action="store_true")
    d = sub.add_parser("discover")
    d.add_argument("--blocks", type=int, default=30000)
    args = ap.parse_args()
    if args.cmd == "audit":
        audit(args.ca, args.url, args.chain, args.blocks, args.skip_logs, args.from_block)
    else:
        discover(args.blocks)

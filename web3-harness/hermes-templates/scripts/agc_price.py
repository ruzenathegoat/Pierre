#!/usr/bin/env python3
"""AGC price / pool report straight from the chain.

    python3 ~/.hermes/scripts/agc_price.py [--sell 1400000]

Reserves come from the pair's own getReserves(), so no indexer sits between the
number and the pool. The BNB/USD leg is the only external input and it is printed
with its source so a stale quote is visible.
"""
import json
import subprocess
import sys

RPC = "https://rpc-bsc.48.club"
AGC = "0x63dea5aCdbE1F27c968907D08610A5f0A0284bA6"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
PAIR = "0xe56041cddbb46db01c67b7a62684f428a04db8c6"
ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"


def curl(url, timeout=25):
    out = subprocess.run(
        ["curl", "-s", "-m", str(timeout), url, "-H", "User-Agent: Mozilla/5.0"],
        capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except Exception:
        return None


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    out = subprocess.run(
        ["curl", "-s", "-m", "25", "-X", "POST", RPC, "-H", "User-Agent: Mozilla/5.0",
         "-H", "Content-Type: application/json", "-d", body],
        capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except Exception:
        return {}


def main():
    sell = 1_400_000.0
    if "--sell" in sys.argv:
        sell = float(sys.argv[sys.argv.index("--sell") + 1])

    res = rpc("eth_call", [{"to": PAIR, "data": "0x0902f1ac"}, "latest"]).get("result")
    if not res:
        print("gagal baca reserves dari pair", file=sys.stderr)
        return 1
    d = res[2:]
    r_agc = int(d[0:64], 16) / 1e18
    r_wbnb = int(d[64:128], 16) / 1e18
    price_wbnb = r_wbnb / r_agc

    # router quote: accounts for the 0.25% pool fee and the price impact
    amt_in = int(sell * 0.98 * 10 ** 18)          # 2% transfer tax leaves 98% for the pool
    data = ("0x0d4f581a" + format(amt_in, "x").rjust(64, "0")
            + format(0x40, "x").rjust(64, "0") + format(2, "x").rjust(64, "0")
            + AGC[2:].lower().rjust(64, "0") + WBNB[2:].lower().rjust(64, "0"))
    # selector for getAmountsOut(uint256,address[])
    quote_res = rpc("eth_call", [{"to": ROUTER, "data": data}, "latest"]).get("result")
    quote = None
    if quote_res and quote_res != "0x":
        q = quote_res[2:]
        quote = int(q[64:128], 16) / 1e18

    # BNB/USD: on-chain WBNB/USDT V2 pair, no external API
    usdt_pair = rpc("eth_call", [{"to": PAIR, "data": "0x0902f1ac"}, "latest"]).get("result")
    bnb_usd = None
    p = rpc("eth_call", [{"to": "0x16b9a82891338f9bA80E2D6970FddA79D1eb0daE",
                          "data": "0x0902f1ac"}, "latest"]).get("result")
    if p:
        dd = p[2:]
        w0 = int(dd[0:64], 16) / 1e18
        w1 = int(dd[64:128], 16) / 1e18
        t0 = rpc("eth_call", [{"to": "0x16b9a82891338f9bA80E2D6970FddA79D1eb0daE",
                               "data": "0x0dfe1681"}, "latest"]).get("result")
        if t0:
            token0 = "0x" + t0[-40:]
            bnb_usd = (w1 / w0) if token0.lower() == WBNB.lower() else (w0 / w1)

    print("=== AGC pool (langsung dari chain)")
    print(f"reserves  : {r_agc:,.0f} AGC + {r_wbnb:.4f} WBNB")
    if bnb_usd:
        print(f"likuiditas: ${(r_wbnb * bnb_usd * 2):,.0f} (2 x sisi BNB) | BNB ${bnb_usd:,.2f}")
    print(f"harga     : {price_wbnb:.6e} WBNB/AGC")
    gross = sell * price_wbnb
    net = quote if quote else gross * 0.98 * 0.9975
    print(f"\n{sell:,.0f} AGC:")
    print(f"  gross   : {gross:.6f} WBNB")
    print(f"  realisasi: {net:.6f} BNB" + (f" = ${net * bnb_usd:,.2f}" if bnb_usd else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

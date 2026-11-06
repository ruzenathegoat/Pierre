#!/usr/bin/env python3
import json, subprocess, time, sys
RPC = "https://rpc-bsc.48.club"
MINT = "0x95AF9fe16fE5c1741b5E3F1b3b045a8c2470eca9"
def rpc(m, p, t=3):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p})
    for _ in range(t):
        o = subprocess.run(["curl", "-s", "--max-time", "12", "-X", "POST", RPC,
                            "-H", "Content-Type: application/json",
                            "-H", "User-Agent: Mozilla/5.0", "--data", body],
                           capture_output=True, text=True).stdout
        try:
            r = json.loads(o)
            if "result" in r: return r["result"]
        except Exception: pass
        time.sleep(0.6)
    return None
latest = int(rpc("eth_blockNumber", []), 16)
step = 5000
lo = int(sys.argv[1]); hi = int(sys.argv[2])
last_hit = None
for k in range(lo, hi + 1):
    toB = latest - (k - 1) * step; fromB = toB - step + 1
    res = rpc("eth_getLogs", [{"address": MINT, "fromBlock": hex(fromB), "toBlock": hex(toB)}])
    n = len(res) if res is not None else "ERR"
    print(f"k={k} {fromB}-{toB} logs={n}", flush=True)
    if isinstance(n, int) and n > 0:
        last_hit = (k, fromB, toB)
print("OLDEST_HIT", last_hit, flush=True)

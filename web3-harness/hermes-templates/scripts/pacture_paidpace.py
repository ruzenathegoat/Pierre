#!/usr/bin/env python3
import json, subprocess, time
RPC = "https://rpc-bsc.48.club"
MINT = "0x95AF9fe16fE5c1741b5E3F1b3b045a8c2470eca9"
MINTED = "0x5f476a6161150ac33452eb8d07dc6b5273aa5068b66161be5e7e6a449aecbc2d"

def rpc(m, p, t=3):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p})
    for _ in range(t):
        o = subprocess.run(["curl", "-s", "--max-time", "20", "-X", "POST", RPC,
                            "-H", "Content-Type: application/json",
                            "-H", "User-Agent: Mozilla/5.0", "--data", body],
                           capture_output=True, text=True).stdout
        try:
            r = json.loads(o)
            if "result" in r:
                return r["result"]
        except Exception:
            pass
        time.sleep(1)
    return None

latest = int(rpc("eth_blockNumber", []), 16)
step = 5000
rows = []
k = 1
while k <= 30:
    toB = latest - (k - 1) * step
    fromB = toB - step + 1
    res = rpc("eth_getLogs", [{"address": MINT, "topics": [MINTED],
                               "fromBlock": hex(fromB), "toBlock": hex(toB)}])
    if res is None:
        print(f"k={k} ERR", flush=True); k += 1; continue
    paid = 0; free = 0
    for r in res:
        d = r["data"][2:]
        w0 = int(d[0:64], 16); w1 = int(d[64:128], 16)
        paid += w0; free += w1
    bb = rpc("eth_getBlockByNumber", [hex(fromB), False])
    ts = int(bb["timestamp"], 16) if bb else 0
    rows.append({"k": k, "from": fromB, "to": toB, "ts": ts, "n": len(res), "paid": paid, "free": free})
    print(f"k={k} ts={ts} minted_events={len(res)} paid={paid} free={free}", flush=True)
    k += 1
json.dump(rows, open("/home/ubuntu/.hermes/cache/scratch/pacture_pace.json", "w"))
print("DONE", flush=True)

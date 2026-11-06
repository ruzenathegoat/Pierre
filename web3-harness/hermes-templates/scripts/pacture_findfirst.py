#!/usr/bin/env python3
import json, subprocess, time, sys
RPC = "https://rpc-bsc.48.club"
MINT = "0x95AF9fe16fE5c1741b5E3F1b3b045a8c2470eca9"

def rpc(method, params, tries=2):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    for i in range(tries):
        out = subprocess.run(["curl", "-s", "--max-time", "10", "-X", "POST", RPC,
                              "-H", "Content-Type: application/json",
                              "-H", "User-Agent: Mozilla/5.0", "--data", body],
                             capture_output=True, text=True).stdout
        try:
            r = json.loads(out)
        except Exception:
            time.sleep(0.5); continue
        if "result" in r:
            return r["result"]
        time.sleep(0.5)
    return None

latest = int(rpc("eth_blockNumber", []), 16)
print("latest", latest, flush=True)
step = 5000
startk = int(sys.argv[1]) if len(sys.argv) > 1 else 4
k = startk
while k <= 400:
    toB = latest - (k - 1) * step
    fromB = toB - step + 1
    res = rpc("eth_getLogs", [{"address": MINT, "fromBlock": hex(fromB), "toBlock": hex(toB)}])
    n = len(res) if res is not None else "ERR"
    print(f"k={k} {fromB}-{toB} logs={n}", flush=True)
    if res is not None and len(res) == 0:
        print("FIRST_EMPTY", fromB, toB, flush=True)
        ofrom = toB + 1
        oto = ofrom + step - 1
        r2 = rpc("eth_getLogs", [{"address": MINT, "fromBlock": hex(ofrom), "toBlock": hex(oto)}])
        if r2:
            blk = min(int(x["blockNumber"], 16) for x in r2)
            bb = rpc("eth_getBlockByNumber", [hex(blk), False])
            print("FIRST_EVENT_BLOCK", blk, "TS", int(bb["timestamp"], 16), flush=True)
        break
    k += 1
print("DONE", flush=True)

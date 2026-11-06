#!/usr/bin/env python3
"""Date a contract's first on-chain event, which is its practical launch.

Usage:
    first_event_age.py <rpc_url> <address> [--topic 0x<topic0>] [--chunk 5000] [--streak 3]

A deployed contract emits nothing, so the first event on it is the earliest on-chain date
available. Sparse activity leaves empty 5000-block chunks ABOVE the real first event, so the
search only stops after --streak CONSECUTIVE empty chunks and then reports the oldest chunk
holding a hit. An errored chunk is not counted as empty, and does not reset the streak.

Explorers are not a shortcut from a datacenter host: BscScan serves a Cloudflare challenge and a
historical eth_getCode answers 'not supported' / 'header not found' on the free nodes.

Stdlib + curl only. One line per chunk, then a final FIRST_EVENT line.
"""
import json
import subprocess
import sys
import time


def rpc(url, method, params, tries=3):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    for _ in range(tries):
        out = subprocess.run(
            ["curl", "-s", "--max-time", "15", "-X", "POST", url,
             "-H", "Content-Type: application/json",
             "-H", "User-Agent: Mozilla/5.0", "--data", body],
            capture_output=True, text=True).stdout
        try:
            r = json.loads(out)
        except Exception:
            time.sleep(0.6)
            continue
        if "result" in r:
            return r["result"]
        time.sleep(0.6)
    return None


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 2
    url, addr = args[0], args[1]
    topic, chunk, streak = None, 5000, 3
    i = 2
    while i < len(args):
        if args[i] == "--topic" and i + 1 < len(args):
            topic, i = args[i + 1], i + 2
        elif args[i] == "--chunk" and i + 1 < len(args):
            chunk, i = int(args[i + 1]), i + 2
        elif args[i] == "--streak" and i + 1 < len(args):
            streak, i = int(args[i + 1]), i + 2
        else:
            i += 1

    latest = int(rpc(url, "eth_blockNumber", []), 16)
    print("latest_block", latest, flush=True)

    empty, k, oldest = 0, 1, None
    while k <= 2000:
        to_b = latest - (k - 1) * chunk
        from_b = to_b - chunk + 1
        if from_b < 0:
            break
        filt = {"address": addr, "fromBlock": hex(from_b), "toBlock": hex(to_b)}
        if topic:
            filt["topics"] = [topic]
        res = rpc(url, "eth_getLogs", [filt])
        n = None if res is None else len(res)
        print(f"k={k} {from_b}-{to_b} logs={n}", flush=True)
        if n is None:
            k += 1
            continue
        if n == 0:
            empty += 1
            if empty >= streak:
                break
        else:
            empty, oldest = 0, (from_b, to_b)
        k += 1

    if oldest is None:
        print("FIRST_EVENT none -- no logs found; widen the scan or check the address")
        return 0

    filt = {"address": addr, "fromBlock": hex(oldest[0]), "toBlock": hex(oldest[1])}
    if topic:
        filt["topics"] = [topic]
    res = rpc(url, "eth_getLogs", [filt]) or []
    if not res:
        print("FIRST_EVENT none -- oldest chunk re-read empty")
        return 0

    blk = min(int(x["blockNumber"], 16) for x in res)
    bb = rpc(url, "eth_getBlockByNumber", [hex(blk), False])
    ts = int(bb["timestamp"], 16) if bb else 0
    lb = rpc(url, "eth_getBlockByNumber", [hex(latest), False])
    now_ts = int(lb["timestamp"], 16) if lb else 0
    print(f"FIRST_EVENT block={blk} ts={ts} now_ts={now_ts} age_hours={(now_ts - ts) / 3600:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

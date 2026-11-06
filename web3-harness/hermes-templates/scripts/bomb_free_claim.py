#!/usr/bin/env python3
"""Digital Bomb (BSC) free-claim runner.

Fires claimFree() from the Binance agentic wallet (the wallet that holds the
soulbound .ai Agent ID) exactly when the mint opens, and reports the result.

Contract facts (verified 2026-11-04):
  core  0xC3f847430D660e5AAbE8D4b2B5792d6Fcbb171F9
  token 0xbE2d0Bc70A3e577C6a1da15e0570D1E67eeBfF55  (BOMB, 18 dec)
  gate  SPACE ID Agent ID 0x60b9262456de011f7d15a54cdd8c48baaa8b022f
  start 1793773800 (2026-11-04 13:30:00 WIB)  free shares 800
  claimFree() = 0xf366afc9 (non-payable, no approve)

Revert selectors:
  0x0d3f7776 NotOpen       0xfbd65f7d FreeGone
  0xc1fba8cf NoIdentity    0x17bf413b AlreadyClaimed
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

CORE = "0xC3f847430D660e5AAbE8D4b2B5792d6Fcbb171F9"
WALLET = "0x74624463e902C11aB37C0034EB216A2B4466269F"
CLAIM = "0xf366afc9"
START = int(os.environ.get("BOMB_START", 1793773800))  # 2026-11-04 13:30:00 WIB
DEADLINE_S = int(os.environ.get("BOMB_DEADLINE", 240))
DRY = os.environ.get("BOMB_DRY") == "1"  # stop right before broadcasting
RPCS = [
    "https://rpc-bsc.48.club",
    "https://bsc-rpc.publicnode.com",
    "https://bsc-dataseed.bnbchain.org",
]
BAW = "/home/ubuntu/.nvm/versions/node/v22.23.4/bin/baw"
ENV = dict(os.environ)
ENV["HOME"] = ENV.get("HOME") or "/home/ubuntu"
ENV["PATH"] = "/home/ubuntu/.nvm/versions/node/v22.23.4/bin:" + ENV.get("PATH", "/usr/bin:/bin")
LOG = "/home/ubuntu/.hermes/cache/bomb_free_claim.log"

ERR = {
    "0x0d3f7776": "NotOpen (belum buka)",
    "0xfbd65f7d": "FreeGone (800 free sudah habis)",
    "0xc1fba8cf": "NoIdentity (wallet gak punya .ai Agent ID)",
    "0x17bf413b": "AlreadyClaimed (ID ini sudah klaim free)",
    "0x73bba196": "OverQuota",
    "0x1cdde67b": "IgnitingClosed",
}


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def rpc(method, params, timeout=10):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    last = None
    for url in RPCS:
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"content-type": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError("all RPC failed: %r" % (last,))


def estimate():
    return rpc("eth_estimateGas", [{"from": WALLET, "to": CORE, "data": CLAIM}])


def revert_sel(resp):
    err = resp.get("error") or {}
    data = err.get("data")
    if isinstance(data, dict):
        data = data.get("data")
    if isinstance(data, str) and len(data) >= 10:
        return data[:10]
    return None


def baw(args, timeout=60):
    p = subprocess.run([BAW] + args, capture_output=True, text=True, env=ENV, timeout=timeout)
    out = (p.stdout or "").strip()
    try:
        return json.loads(out), p.returncode
    except Exception:
        return {"_raw": out, "_stderr": (p.stderr or "").strip()}, p.returncode


def report(lines):
    print("\n".join(lines), flush=True)


def post_alert(txhash, note):
    try:
        p = subprocess.run([
            "python3", "/home/ubuntu/.hermes/scripts/order_alert.py",
            "--action", "CLAIM", "--chain", "BSC",
            "--asset", "BOMB free share (Digital Bomb)",
            "--value", "0 BNB (gas only)",
            "--contract", CORE, "--tx", txhash,
            "--source", "baw agentic wallet (pierre.ai)",
            "--note", note, "--also", "positions", "--wait",
        ], capture_output=True, text=True, timeout=60)
        log("order_alert rc=%s out=%s" % (p.returncode, (p.stdout or "").strip()[:200]))
    except Exception as e:  # noqa: BLE001
        log("order_alert GAGAL: %r" % (e,))


def main():
    log("start, target open %d (%.0fs lagi)" % (START, START - time.time()))

    # wait until just before open, then hammer
    now = time.time()
    if now < START - 1.5:
        time.sleep(START - 1.5 - now)

    # poll until the call simulates clean
    opened = None
    hard_fail = None
    deadline = time.time() + DEADLINE_S
    polls = 0
    while time.time() < deadline:
        polls += 1
        try:
            r = estimate()
        except Exception as e:  # noqa: BLE001
            log("rpc err: %r" % (e,))
            time.sleep(0.3)
            continue
        if "result" in r:
            opened = r["result"]
            break
        sel = revert_sel(r)
        if sel == "0x0d3f7776":
            pass  # not open yet
        elif sel in ("0xfbd65f7d", "0xc1fba8cf", "0x17bf413b", "0x1cdde67b"):
            hard_fail = ERR.get(sel, sel)
            break
        time.sleep(0.12)

    if hard_fail:
        report(["**Digital Bomb free claim: BATAL**", "Alasan: %s" % hard_fail,
                "Wallet %s, kontrak %s" % (WALLET, CORE)])
        return 1
    if not opened:
        report(["**Digital Bomb free claim: GAGAL buka**",
                "Nggak pernah lolos simulasi dalam %ds. Cek manual." % DEADLINE_S])
        return 1

    t_open = time.time()
    log("open terdeteksi setelah %d poll (%.2fs), estimasi gas %s" % (polls, t_open - START, opened))
    gas = int(opened, 16)

    # fire: preview then execute, retry the pair if execute gives no hash
    def extract_hash(resp):
        d = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        for src in (resp, d):
            if not isinstance(src, dict):
                continue
            for k in ("txHash", "txhash", "hash", "transactionHash"):
                v = src.get(k)
                if isinstance(v, str) and v.startswith("0x") and len(v) == 66:
                    return v
        return None

    txh = None
    ex = {}
    rid = None
    for round_ in range(1, 5):
        rid = None
        for attempt in range(1, 8):
            pv, _ = baw(["contract-call", "preview", "--binanceChainId", "56",
                         "--from", WALLET, "--to", CORE, "--value", "0",
                         "--inputData", CLAIM, "--json"])
            if pv.get("success") and pv.get("data", {}).get("requestId"):
                rid = pv["data"]["requestId"]
                log("preview ok (round %d attempt %d) requestId %s" % (round_, attempt, rid))
                break
            log("preview gagal r%d a%d: %s" % (round_, attempt, json.dumps(pv)[:200]))
            time.sleep(0.2)
        if not rid:
            continue
        if DRY:
            report(["DRY RUN: simulasi buka (est gas %s), preview requestId %s. Gak broadcast."
                    % (gas, rid)])
            return 0
        ex, _ = baw(["contract-call", "execute", "--requestId", rid, "--json"])
        log("execute r%d: %s" % (round_, json.dumps(ex)[:400]))
        txh = extract_hash(ex)
        if txh:
            break
        time.sleep(0.2)

    if not txh:
        report(["**Digital Bomb free claim: EXECUTE tanpa txHash**",
                "Respons terakhir: %s" % json.dumps(ex)[:600],
                "Cek riwayat wallet agentic."])
        return 1

    t_fire = time.time()
    log("broadcast tx %s (+%.2fs dari detect), tunggu receipt" % (txh, t_fire - t_open))
    rcpt = None
    sped = 0
    for _ in range(150):
        time.sleep(0.4)
        try:
            r = rpc("eth_getTransactionReceipt", [txh])
        except Exception:
            continue
        if r.get("result"):
            rcpt = r["result"]
            break
        # still pending: bump gas slightly, once or twice
        if sped < 2 and time.time() - t_fire > 4 + sped * 6:
            sp, _ = baw(["wallet", "speed-up", txh, "--level", "HIGH",
                         "--binanceChainId", "56", "--json"], timeout=60)
            sped += 1
            log("speed-up #%d (x1.25): %s" % (sped, json.dumps(sp)[:250]))

    ok = bool(rcpt) and rcpt.get("status") == "0x1"
    head = "SUKSES" if ok else ("REVERTED" if rcpt else "BROADCAST (receipt belum kebaca)")
    lines = ["**Digital Bomb free claim: %s**" % head,
             "tx: %s" % txh,
             "latency: open terdeteksi +%.2fs, broadcast +%.2fs dari detect" % (t_open - START, t_fire - t_open)]
    if rcpt:
        fee = int(rcpt["gasUsed"], 16) * int(rcpt.get("effectiveGasPrice", "0x0"), 16)
        lines.append("block %s, status %s, gasUsed %s, fee %.6f BNB" % (
            int(rcpt["blockNumber"], 16), rcpt["status"],
            int(rcpt["gasUsed"], 16), fee / 1e18))
    if sped:
        lines.append("gas dibump %dx (speed-up HIGH)" % sped)

    if ok:
        try:
            acc = rpc("eth_call", [{"to": CORE, "data": "0x73b9aa91" + WALLET.lower().replace("0x", "").rjust(64, "0")}, "latest"]).get("result")
            if acc:
                b = acc[2:]
                w = [b[i:i + 64] for i in range(0, len(b), 64)]
                names = ["hasId", "agentId", "number", "usedShares", "quota", "followed",
                         "tweeted", "inviteCount", "squad", "crit", "genesis", "bonus"]
                d = {n: int(v, 16) for n, v in zip(names, w)}
                lines.append("akun: hasId=%d squad=%d crit=%d genesis=%d (share ke-)" % (
                    d["hasId"], d["squad"], d["crit"], d["genesis"]))
            st = rpc("eth_call", [{"to": CORE, "data": "0xd80528ae"}, "latest"]).get("result")
            if st:
                b = st[2:]
                w = [b[i:i + 64] for i in range(0, len(b), 64)]
                lines.append("kontrak: soldShares=%d freeClaimed(agentId)=%s" % (
                    int(w[0], 16), rpc("eth_call", [{"to": CORE, "data": "0x0668f9a5" + f"{d['agentId']:064x}"}, "latest"]).get("result")))
        except Exception as e:  # noqa: BLE001
            log("post-read gagal: %r" % (e,))

    lines.append("wallet: %s (agentic, holder .ai Agent ID)" % WALLET)
    lines.append("Token 25,000,000 BOMB, locked sampai pool ignite (share #10,000).")
    post_alert(txh, "Digital Bomb free share claimed via claimFree()")
    report(lines)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        report(["**Digital Bomb free claim: ERROR**", repr(e)])
        sys.exit(1)

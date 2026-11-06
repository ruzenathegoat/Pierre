#!/usr/bin/env python3
"""Probe whether Binance's risk engine still blocks the NIULAI refund preview.

Prints exactly one deterministic token so the cron `monitor` can diff ticks:
  READY                     -> preview accepted, refund can be executed
  BLOCKED:<code>            -> still rejected by the risk engine
  ERROR:<text>              -> probe itself failed

Read-only as far as the chain is concerned: a `contract-call preview` only
simulates and returns a requestId, it never broadcasts anything.
"""
import json
import os
import subprocess
import sys

WALLET = "0x74624463e902C11aB37C0034EB216A2B4466269F"
CONTRACT = "0x15e47c22df42D94Fa2f0aD078Fec5Bea6453d5cF"
RPC = "https://rpc-bsc.48.club"


def selector(sig: str) -> str:
    from Crypto.Hash import keccak

    k = keccak.new(digest_bits=256)
    k.update(sig.encode())
    return k.hexdigest()[:8]


def chain_state() -> dict:
    import requests

    def call(to, data):
        r = requests.post(
            RPC,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": to, "data": data}, "latest"]},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        ).json()
        return r.get("result", "0x")

    phase = call(CONTRACT, "0x" + selector("phase()"))
    sold = call(CONTRACT, "0x" + selector("sold()"))
    return {
        "phase": int(phase, 16) if phase and phase != "0x" else None,
        "sold": int(sold, 16) if sold and sold != "0x" else None,
    }


def probe() -> str:
    try:
        p = subprocess.run(
            [
                "baw", "contract-call", "preview",
                "--binanceChainId", "56",
                "--from", WALLET,
                "--to", CONTRACT,
                "--value", "0",
                "--inputData", "0x" + selector("refund()"),
                "--json",
            ],
            capture_output=True, text=True, timeout=120,
        )
        out = (p.stdout or "") + (p.stderr or "")
        blob = out[out.find("{"):] if "{" in out else out
        try:
            j = json.loads(blob)
        except Exception:
            j = None
        if j and j.get("success"):
            return "READY"
        if j and not j.get("success"):
            err = j.get("error") or {}
            return "BLOCKED:%s" % (err.get("code") or err.get("message") or "unknown")
        return "ERROR:%s" % out.strip().replace("\n", " ")[:120]
    except Exception as e:  # noqa: BLE001
        return "ERROR:%s" % str(e)[:120]


if __name__ == "__main__":
    state = probe()
    try:
        st = chain_state()
        print("STATE phase=%s sold=%s %s" % (st["phase"], st["sold"], state))
    except Exception:
        print("STATE unknown %s" % state)

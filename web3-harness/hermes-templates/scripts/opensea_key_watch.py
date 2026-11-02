#!/usr/bin/env python3
"""OpenSea API v2 key watchdog + auto-rotation for the Pierre web3 harness.

Silent while healthy (cron no_agent job delivers nothing when stdout is empty).

Why it works this way:
  * OpenSea serves collection/NFT reads with ANY non-empty key header, so a
    status probe cannot tell a good key from a junk one. The reliable signal is
    key expiry, which the API reports when a key is minted.
  * So the watchdog keeps a state file with the fingerprint + expires_at of the
    key it knows, and rotates (POST /api/v2/auth/keys: free tier, no wallet,
    7-day life) when that expiry is under 48h away, when the key in .env is
    unknown to it, or when a probe returns 401/403/429.
  * Minting is capped at 2 keys/day/IP; a 429 is reported once per day, not
    on every tick.

Modes: no args = watchdog (may rotate); --check-only = print state, no writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

ENV_PATH = os.path.expanduser("~/.hermes/web3-harness/.env")
STATE_PATH = os.path.expanduser("~/.hermes/web3-harness/.opensea-key-state.json")
TEST_URL = "https://api.opensea.io/api/v2/collections?limit=1"
NEW_KEY_URL = "https://api.opensea.io/api/v2/auth/keys"
ROTATE_BEFORE = timedelta(hours=48)
TIMEOUT = 25


def http(url: str, key: str | None = None, method: str = "GET") -> tuple[int, dict | str]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Accept", "application/json")
    # Cloudflare (error 1010) blocks python-urllib's default UA.
    req.add_header("User-Agent", "hermes-pierre/1.0 (web3-harness; +https://opensea.io)")
    if key:
        req.add_header("X-API-KEY", key)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body
    except Exception as e:  # noqa: BLE001 - network layer, reported as transient
        return 0, str(e)


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def read_env_key(path: str = ENV_PATH) -> str:
    if not os.path.exists(path):
        return ""
    m = re.search(r"^OPENSEA_API_KEY=(.*)$", open(path, encoding="utf-8").read(), re.M)
    return (m.group(1).strip().strip("'\"") if m else "")


def write_env_key(key: str, path: str = ENV_PATH) -> None:
    content = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if re.search(r"^OPENSEA_API_KEY=.*$", content, re.M):
        content = re.sub(r"^OPENSEA_API_KEY=.*$", f"OPENSEA_API_KEY={key}", content, flags=re.M)
    else:
        content = content.rstrip("\n") + f"\nOPENSEA_API_KEY={key}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def state_read() -> dict:
    try:
        return json.load(open(STATE_PATH, encoding="utf-8"))
    except Exception:  # noqa: BLE001 - missing/corrupt state is fine
        return {}


def state_write(**kw) -> None:
    st = state_read()
    st.update(kw)
    st["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)
        os.chmod(STATE_PATH, 0o600)
    except OSError:
        pass


def parse_expiry(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def probe_harness() -> str:
    """End-to-end check through the same code path the tools use."""
    tsx = os.path.expanduser("~/.hermes/web3-harness/node_modules/.bin/tsx")
    probe = os.path.expanduser("~/.hermes/web3-harness/scripts/opensea_probe.ts")
    if not (os.path.exists(tsx) and os.path.exists(probe)):
        return "error"
    try:
        out = subprocess.run([tsx, probe], capture_output=True, text=True, timeout=90,
                             cwd=os.path.expanduser("~/.hermes/web3-harness"))
    except Exception:  # noqa: BLE001
        return "error"
    txt = (out.stdout or "").strip().splitlines()
    last = txt[-1].strip() if txt else ""
    return last if last in ("opensea-v2", "fallback") else "error"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true", help="print state, never rotate or write")
    args = ap.parse_args()

    key = read_env_key()
    fp = fingerprint(key) if key else ""
    st = state_read()
    expires = parse_expiry(st.get("expires_at")) if st.get("fingerprint") == fp else None
    now = datetime.now(timezone.utc)

    if args.check_only:
        print(json.dumps({
            "has_key": bool(key),
            "key_len": len(key),
            "fingerprint": fp,
            "tracked_expires_at": st.get("expires_at") if expires else None,
            "hours_left": round((expires - now).total_seconds() / 3600, 1) if expires else None,
            "harness_source": probe_harness(),
        }, indent=2))
        return 0

    # Key validity cannot be probed: OpenSea serves reads with ANY non-empty
    # key, so a bogus key still returns real data. Only these signals are real:
    # a missing key, an explicit 401/403 rejection, and minted-key expiry.
    critical, why = False, ""
    if not key:
        critical, why = True, "tidak ada key di .env"
    else:
        status, body = http(TEST_URL, key)
        if status in (401, 403):
            critical, why = True, f"API menolak key (HTTP {status})"
        elif status == 429:
            critical, why = True, "kuota API tercapai (HTTP 429)"
        elif status == 0:
            if st.get("alerted_date") != date.today().isoformat():
                state_write(alerted_date=date.today().isoformat())
                print(f"⚠️ OpenSea watchdog: cek koneksi gagal ({str(body)[:120]}). Tidak ada perubahan.")
            return 0

    expires_ok = bool(expires) and (expires - now) >= ROTATE_BEFORE
    if not critical and expires_ok:
        return 0  # healthy and expiry tracked: silent, no mint attempt

    if not why:
        why = "masa berlaku key belum terlacak" if not expires else "key mendekati expire"

    nstatus, nbody = http(NEW_KEY_URL, method="POST")
    if nstatus == 200 and isinstance(nbody, dict):
        new_key = nbody.get("api_key") or nbody.get("key") or ""
        if not new_key:
            print("⚠️ OpenSea: endpoint key balas 200 tanpa api_key. Cek manual di opensea.io/settings/developer.")
            return 0
        write_env_key(new_key)
        new_exp = nbody.get("expires_at")
        state_write(fingerprint=fingerprint(new_key), expires_at=new_exp, alerted_date=None,
                    rotated_at=now.isoformat())
        if critical:
            print(f"🔑 OpenSea API key dirotasi otomatis ({why}). Key baru aktif, expire {new_exp or 'tidak dilaporkan'}. Tanpa restart, harness baca .env tiap request.")
        else:
            print(f"🔑 OpenSea API key dirotasi ({why}). Key baru aktif, expire {new_exp or 'tidak dilaporkan'}. Rotasi berikutnya ~48 jam sebelum expire.")
        return 0

    if not critical:
        return 0  # still usable, retry quietly next tick

    today = date.today().isoformat()
    if nstatus == 429:
        if st.get("alerted_date") == today:
            return 0
        state_write(alerted_date=today)
        print(
            f"⚠️ OpenSea API key bermasalah ({why}) dan rotasi otomatis kena limit "
            "`Maximum 2 keys per day` dari IP VPS. Aksi: buat key baru di "
            "opensea.io/settings/developer lalu ganti OPENSEA_API_KEY di "
            "~/.hermes/web3-harness/.env."
        )
        return 0

    if st.get("alerted_date") != today:
        state_write(alerted_date=today)
        print(f"⚠️ OpenSea watchdog: key bermasalah ({why}) dan rotasi gagal (HTTP {nstatus}). {str(nbody)[:180]}")
    return 0



if __name__ == "__main__":
    sys.exit(main())

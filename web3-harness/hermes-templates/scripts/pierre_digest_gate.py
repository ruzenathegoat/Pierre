#!/usr/bin/env python3
"""Gate for Pierre's 15-minute portfolio digest.

Prints a constant string when there are no OPEN positions so the cron monitor
skips the agent run (no channel spam). Prints a fresh snapshot every tick when
positions exist, so the digest always fires.
"""
import datetime
import json
import sqlite3
import sys

DB = "/home/ubuntu/.hermes/web3-harness/trades.db"


def main() -> int:
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except Exception as exc:  # noqa: BLE001
        print(f"DB_UNREADABLE: {type(exc).__name__}")
        return 0

    try:
        rows = con.execute(
            "SELECT id, chain, asset_type, asset_name, contract_address, token_id, "
            "entry_price_eth, high_water_mark_eth, last_alerted_at, updated_at "
            "FROM positions WHERE status = 'OPEN' ORDER BY id"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        print(f"QUERY_FAILED: {type(exc).__name__}: {exc}")
        return 0
    finally:
        con.close()

    if not rows:
        # Constant output -> identical to previous tick -> agent skipped.
        print("NO_OPEN_POSITIONS")
        return 0

    cols = [
        "id", "chain", "asset_type", "asset_name", "contract_address", "token_id",
        "entry_price_eth", "high_water_mark_eth", "last_alerted_at", "updated_at",
    ]
    payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "open_positions": len(rows),
        "positions": [dict(zip(cols, r)) for r in rows],
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

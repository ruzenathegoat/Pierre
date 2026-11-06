# Reconciling a position book against chain state

Class of question: "I already exited asset X, why is it still showing up in <channel/report>?" The reporter is usually innocent; a status flag in the local book never got flipped because the exit did not go through the code path that flips it.

## Where the divergence comes from

- A position book (here: `~/.hermes/web3-harness/trades.db`) is only updated by the write paths that touch it. A reporter that lists `positions WHERE status='OPEN'` (here: the no-LLM 15m digest script `~/.hermes/scripts/pierre_digest_gate.py`, cron `Pierre Portfolio Digest`) will re-post the row every tick, potentially forever.
- Exits taken outside the harness leave the row open: a contract-level `refund()` that burns the token, a launchpad refund, a manual transfer, an airdrop claim that consumed a share. These produce no SELL row in the `trades` log either, so the absence of a sell record is expected, not evidence the exit did not happen.

## Procedure

1. Read what the reporter reads:
   ```bash
   sqlite3 ~/.hermes/web3-harness/trades.db \
     "SELECT id,asset_name,status,updated_at FROM positions WHERE status='OPEN' ORDER BY id;"
   ```
2. Prove the exit on chain before editing anything (see SKILL.md, "Proving an execution landed on chain", plus the burn-versus-sale pitfall). Zeros plus a matching native balance delta are what justify the edit.
3. Back up the DB, then close the row with the same statement the harness uses (`closePosition` in `src/db.ts`):
   ```bash
   cp ~/.hermes/web3-harness/trades.db ~/.hermes/cache/scratch/trades.db.bak.$(date +%s)
   sqlite3 ~/.hermes/web3-harness/trades.db \
     "UPDATE positions SET status='CLOSED', updated_at=CURRENT_TIMESTAMP WHERE id=<id> AND status='OPEN';"
   ```
   Use a harness CLI/function when one exists and raw SQL only as the mirror of it, so the book stays in the shape the rest of the code expects.
4. Verify by re-running the SELECT. Do **not** run the reporter script as a test: the digest posts straight to a live Discord webhook, so a test run spams the channel and is still not a read-back (channel history is not readable from this host).
5. No restart is needed when the script reads the DB on every tick; say so instead of restarting something.

## Rules

- `CURRENT_TIMESTAMP` in SQLite is UTC. A freshly written `updated_at` that reads ~7 hours behind the wall clock is correct on a WIB host, not a bug.
- Never insert a synthetic SELL/REFUND row into the trade log to "explain" the exit. Recap and PnL jobs aggregate that table, so an invented row double counts. State the realised loss and let the user decide whether to record it: he tracks returned capital separately from PnL and audits the arithmetic.
- Column names that bite: `positions(id, chain, contract_address, token_id, asset_type, asset_name, entry_price_eth, high_water_mark_eth, status, last_alerted_at, updated_at)`; `trades(tx_hash, timestamp, action, chain, contract_address, asset_name, price_eth, realized_pnl_eth, trigger_source)` has no `ts` and no `side` column.
- For selector hashing in ad-hoc probes, import the pure-Python implementation rather than assuming pycryptodome:
  ```python
  import sys; sys.path.insert(0, '/home/ubuntu/.hermes/scripts')
  from pierre_digest_gate import keccak_sel, keccak256_hex
  ```
  `Crypto.Hash.keccak` is not in the base interpreter, and `hashlib.sha3` uses the wrong padding for Ethereum selectors.

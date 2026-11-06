# NIULAI refund unblock watch (cron prompt, report-only)

The monitor script output changed, which means Binance's risk engine stopped
blocking the NIULAI refund preview (output contains READY) or the chain state
moved materially.

## Context

- Ruzena minted 1 paid share (0.002 BNB) of the NIULAI fair-mint on BSC from his
  Binance agentic wallet 0x74624463e902C11aB37C0034EB216A2B4466269F.
- Contract 0x15e47c22df42D94Fa2f0aD078Fec5Bea6453d5cF. Mint did not sell out
  (1760/10000), phase moved to 4 = Refunds, refundBps 8000, so every payer can
  call refund() and get 80 percent of what they paid.
- Binance's contract-call risk engine has been rejecting the preview with code
  351803 "Transaction risk is too high and has been rejected: blocked".
- A read-only eth_call of refund() from that wallet succeeds, so the contract
  itself will pay. Only the BAW signing lane is blocked.
- Refund has no deadline: phase Refunds is permanent while the pool stays shut.

## What to do

Report-only. Never sign, never broadcast, never execute a transaction.

1. Re-run the probe and read the chain: phase(), sold(), launched(),
   paidShares(0x74624463e902C11aB37C0034EB216A2B4466269F) and the wallet native
   BNB balance. RPC https://rpc-bsc.48.club with User-Agent: Mozilla/5.0, and
   Crypto.Hash.keccak for selectors (never hashlib sha3).
2. Probe says READY: say in casual Indonesian that the refund preview is finally
   accepted, give the exact refundable amount (paidShares x 0.002 x 0.8 BNB, plus
   USD at the current BNB price) and the gas estimate, then ask for the go-ahead
   to execute via baw contract-call execute.
3. Probe still BLOCKED: one line saying the risk engine still blocks it and
   nothing needs doing, plus current phase and sold state.
4. phase 3 (Trading) or launched true: say the project launched and refunds are
   off, and give pair 0xe65cd3038c93fd6ba0c2b724d87f8f1249878129 getReserves so he
   sees the real liquidity.

Casual Indonesian, short bullets, no tables, no em dashes.

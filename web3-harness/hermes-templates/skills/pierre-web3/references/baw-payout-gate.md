# Payouts through the Binance Agentic Wallet (baw)

## `wallet send` needs the recipient in the address book

BAW refuses any transfer whose recipient is not already in the user's Binance Wallet address book:

```
{"success": false, "error": {"code": 351703, "name": "SERVICE_ERROR",
 "message": "This transfer was blocked because the recipient address is not in your address book.
             Add this address in your binance wallet app, then retry the transfer."}}
```

Rule: before promising a send to a fresh address (an exchange deposit address, a new payout wallet),
say up front that the user must add it in the Binance Wallet app first. The refusal is a policy gate,
not a gas, nonce, balance or network problem, so do not retry, do not raise gas, and never route the
same amount to a different recipient.

## Flag shape

`baw wallet send` takes `--recipient` (there is no `--to`) and `--tokenAddress`, with the native token
sentinel `0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE` for BNB/ETH. `--amount` is human units;
`contract-call --value` is wei.

## Verify a payout landed

A `success: true` from the CLI is not proof. Confirm with `baw wallet tx-history --binanceChainId 56 --json`
(does a `send` entry exist at all?), then read the recipient's balance on chain and check the sender's
nonce advanced. A scheduled job that reports `last_status: ok` can still have skipped the step entirely,
so reconcile the nonce against the expected transactions after any unattended payout.

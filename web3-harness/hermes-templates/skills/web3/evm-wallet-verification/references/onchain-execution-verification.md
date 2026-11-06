# Verifying an execution on chain (mints, claims, swaps)

Companion to the "Proving an execution landed on chain" section of SKILL.md. Two jobs: prove an execution that a job or CLI claims to have done, and pre-validate an execution path that has never been signed.

## 1. Did the mint/claim actually land?

Read the contract's own state with viem instead of parsing an explorer page:

```js
const abi = parseAbi([
  'event MintFree(address indexed agent, uint256 indexed posId, uint256 shares, uint256 firstIdx, uint256 agc)',
  'event ClaimFree(address indexed agent, uint256 bnb, uint256 agc, uint256 count, uint256[] ids)',
  'function freePositionCount(address) view returns (uint256)',
  'function pending(address) view returns (uint256 freeBnb, uint256 freeAgc)',
  'function quota(address,uint256) view returns (uint256 aLeft, uint256 aUsed, uint256 bLeft, uint256 bUsed, uint256 sharePrice, uint256 agcPerShare)',
])
const fpc = await pub.readContract({ address: MINTER, abi, functionName: 'freePositionCount', args: [WALLET] })
const [freeBnb, freeAgc] = await pub.readContract({ address: MINTER, abi, functionName: 'pending', args: [WALLET] })
const [aLeft, aUsed, bLeft] = await pub.readContract({ address: MINTER, abi, functionName: 'quota', args: [WALLET, 1n] })
```

Interpretation for a fair-mint minter: `freePositionCount` = open positions for that wallet (one per mint tx); `pending` stays `(0, 0)` until the refund delay has passed since the position's timestamp, so zeros on mint day are expected and are NOT a failure; `quota` gives shares left today (`aLeft`) and shares already spent today (`aUsed`).

Then enumerate the events. Public BSC endpoints cap `eth_getLogs` at 5000 blocks, so a single wide query returns `exceed maximum block range: 5000` — chunk it:

```python
topic0 = '0x' + keccak256('MintFree(address,uint256,uint256,uint256,uint256)')  # 0xa77009a7ae07705c8a16f41d4bebc2634992bda20b797ccf1ec29a333ab6dd06
wtop = '0x' + WALLET[2:].lower().rjust(64, '0')
found, start = [], MINT1_BLOCK
while start <= latest:
    end = min(start + 4999, latest)
    r = rpc('eth_getLogs', [{'address': MINTER, 'topics': [topic0, wtop], 'fromBlock': hex(start), 'toBlock': hex(end)}])
    found += r.get('result', [])
    start = end + 1
```

Each hit carries `topics[2]` = `posId` and `data` words = `shares`, `firstIdx`, `agc`; pair it with `eth_getBlockByNumber` for the timestamp so the report can state "posId 1, 5 shares, 1,400,000 AGC at 07:12 WIB".

Pitfalls:
- **`toHex(address, {size: 32})` throws `SizeOverflowError: Size cannot exceed 32 bytes. Given size: 42 bytes.`** viem treats a plain string as UTF-8. Either filter with `getLogs({ event, args: { agent: WALLET } })` or pad the hex yourself (`'0x' + addr.slice(2).toLowerCase().padStart(64, '0')`).
- **`Missing or invalid parameters` from `getLogs` over a wide range is a range problem, not a bad filter.** Chunk it and retry; do not conclude the event is absent.
- **Batch claims can silently under-claim.** A claim function that walks positions in creation order and breaks at the first one still inside its lock window will claim only the older positions. Read that loop before scheduling a batch claim: it must run after the LAST position matures, otherwise schedule one claim per position.
- **Native balance is a cheap independent check.** A refundable deposit (and gas) leaves the wallet only when the transaction executed, so an unchanged balance after a "successful" mint means the tx never landed.

## 2. Pre-validating a sell/swap path that has never been signed

Nothing is sellable before the claim lands, but the path can still be validated:

1. Build the calldata with `encodeFunctionData` and confirm the selector matches the documented one (`0x791ac947` for `swapExactTokensForETHSupportingFeeOnTransferTokens`).
2. `eth_call` it from an address that actually HOLDS the asset (take a large holder from a transfer scan) — a simulation needs no private key.
3. Read the revert. A decoded reason such as `TransferHelper: TRANSFER_FROM_FAILED` (router has no allowance) proves the calldata decoded and execution reached `transferFrom`; a bare `0x` revert means the selector or argument encoding is wrong. That distinction is the entire point of the test.
4. Clamp `amountOutMin` hard (94% of the router quote) because `getAmountsOut` ignores a token's transfer tax and the pool fee, so the quote overstates proceeds for fee-on-transfer tokens.
5. Exercise the guard path for real: run the sell script with an empty balance and confirm it exits with its "no balance" code without sending a transaction.

Report it honestly: encoding and guards are verified, the signed swap is not, and only a real swap proves it.

## 3. Reusable pieces in this harness

- `~/.hermes/scripts/order_alert.py` — posts a normalized order embed to the Discord execution channel; `--wait` returns the created message id as delivery proof, `--dry-run`/`--check` validate without posting, non-zero exit on a failed post so a cron job surfaces it.
- `~/.hermes/scripts/agc_sell_selfcustody.mjs` — sells a token from the self-custody wallet via PancakeSwap V2: derives the address from `WALLET_PRIVATE_KEY`, quotes, approves exactly `amountIn`, swaps, prints `SOLD_OK`. Exit codes: `3` no balance (do not retry), `4` swap reverted (retry once), `5` setup/approve failure.
- `~/.hermes/cache/scratch/agc_positions.mjs` — position counters plus the chunked event scan for a mint wallet.

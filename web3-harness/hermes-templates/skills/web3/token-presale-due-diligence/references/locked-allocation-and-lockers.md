# Verifying a "locked for N months" allocation claim

Answers "emg iya alokasi tim/foundation-nya di-lock setahun?" with the lock record read off the chain, plus the one thing a lock badge never tells you: whether the locker can be emptied early.

## 1. Start from the token's own allocation getters, not the address the user pasted

Ask which address is which, and resolve it from the token:

| getter on the token contract | what it is |
| :--- | :--- |
| `foundation()`, `treasury()` | the allocation wallet the deploy minted to |
| `marketing()` | a second allocation, usually **not** locked |
| `opsWallet()` | tax recipient, funded by swap-backs |
| `lpAdder()`, `minter()`, `router()`, `pair()` | deployment roles |

A user-supplied address is frequently the *original* holder, not the current one: the multisig can hold 0 while the whole allocation sits in a locker. Read `balanceOf` for every role address before saying anything, and lead with "the address you gave me holds nothing now, here is where it went".

## 2. Identify the contract before trusting the label

A Gnosis Safe answers `VERSION()` (`0xffa1ad74`), `getOwners()` (`0xa0e67e2b`), `getThreshold()` (`0xe75235b8`) and `nonce()` (`0xaffed0e0`). Quote owners and threshold, because `2-of-2` owned by a single ops key and a single deployer key is not independent custody. **`nonce() == 1` is the useful signal**: a treasury multisig that has executed exactly one transaction means the only thing it ever did was move the allocation out, so trace that outflow instead of assuming it manages funds.

`getCode` size separates the cases: a Safe proxies ~171 bytes of runtime code, a locker or vesting contract is tens of KB, an EOA is 0 bytes. A locker whose `owner` is an EOA (0 bytes) means one private key can unlock the whole allocation on the unlock date; say that out loud.

## 3. Trace the allocation, then decode the lock event

Scan `Transfer` with `topics: [Transfer, pad(from)]` and again with `[Transfer, null, pad(to)]` in **5000-block chunks** on `https://rpc-bsc.48.club` (it rejects larger ranges with `exceed maximum block range: 5000`), checking the `error` key per chunk.

**Strip the `0x` before padding a topic.** `"0x" + addr.rjust(64, "0")` yields a 66-char token and every chunk answers `-32602 invalid argument 0: invalid hex string`, which a loop that only appends `result` turns into "zero transfers" — reading as "nothing left the wallet" on a wallet that just moved billions. Use `addr.lower().replace("0x", "").rjust(64, "0")`, and print the failed-chunk count.

You rarely need the locker ABI to get the unlock date. A PinkLock-style locker emits
`LockAdded(uint256 indexed id, address token, address owner, uint256 amount, uint256 unlockDate)`,
so from the receipt of the locking tx: `topic0` = the event, `topic1` = the lock id, and data words 2-4 are `token`, `owner`, `amount`, then the `unlockDate` word. Verify the date by converting it rather than assuming the field order.

## 4. Read the lock record, then prove it cannot be shortened

On the locker (PinkSale **PinkLock02**, `0x407993575c91ce7643a4d4ccacc9a98c36ee1bbe` on BSC):

```
getLocksForToken(address,uint256 start,uint256 end)  -> tuple[]  # 0x332f26d7
 totalLockCountForToken(address)                      -> uint256  # 0xe3676f88
 withdrawableTokens(uint256 lockId)                   -> uint256  # 0x6dbdeab3
 multipleVestingLock / vestingLock / unlock / editLock / renounceLockOwnership / transferLockOwnership
```

**Decode with the locker's own ABI, never by slicing return words.** `getLocksForToken` returns a struct whose static fields do not sit where a guess puts them: hand-slicing 8-word groups mislabelled `isLpToken` / `lockDate` / `unlockDate` on the first attempt, swapped lock and unlock on the second, and produced a 1970 date that reads as a broken lock. Fetch `?fields=abi` from Sourcify and decode with viem instead — `readContract({ address: LOCKER, abi, functionName: 'getLocksForToken', args: [token, 0n, 20n] })` returns named fields (`id, token, owner, amount, lockDate, tgeDate, tgeBps, cycle, cycleBps, unlockedAmount, description`), so the vesting parameters and the description string show up without any offset arithmetic. Reconcile `tgeDate` against the `LockAdded` `unlockDate` word from step 3. `withdrawableTokens(id) == 0` plus an `unlockDate` in the future is the state you are looking for. `getLockById(id)` goes through an internal `_getActualIndex` id remap and can answer `Invalid lock id` for an id you read straight off the event; enumerate with `getLocksForToken` instead of concluding the lock does not exist.

Then fetch the locker's source (`https://sourcify.dev/server/v2/contract/{chainId}/{address}?fields=sources`, parse with `json.loads(raw, strict=False)`) and read the two functions that decide whether the lock means anything:

- `unlock(lockId)`: routes to `_normalUnlock` (plain lock) or `_vestingUnlock` (vesting lock), owner-only.
- `_normalUnlock`: `require(block.timestamp >= userLock.tgeDate, "It is not time to unlock")`; releases the whole amount once.
- `_vestingUnlock` + `_withdrawableTokens`: releases `amount * tgeBps / 10000` at `tgeDate`, then `amount * cycleBps / 10000` per `cycle` seconds, capped at `amount`.
- `editLock(lockId, newAmount, newUnlockDate)`: owner-only, requires `newUnlockDate >= userLock.tgeDate && newUnlockDate > block.timestamp` and `newAmount >= userLock.amount`.

Together those mean the lock can only be **extended and topped up**, never shortened or drained early, and there is no admin override. That is the sentence that upgrades "they say it is locked" into "the contract will not release it before then".

**Read `tgeBps` / `cycle` / `cycleBps` before calling any lock "1 year".** A record with `tgeBps = 1000, cycle = 2592000, cycleBps = 1000` is a **vesting** lock, not a cliff: it releases 10% at `tgeDate` (~30 days after the lock) and another 10% every 30 days, so a headline "locked" allocation starts dripping a month later and is gone in ten months. One audited project ran both shapes side by side: the foundation's 4.2B was a genuine plain lock to Nov 2027 (`tgeBps 0`), while the marketing 5.02B locked the same day was a vesting lock with a 30-day cliff. Quote the release schedule (amount and date of the first tranche, then the cadence), the size of each tranche against the pair's token reserve, and what stays unlocked outside the locker.

Two reads make the split explicit and both are needed: `unlockedAmount` (0 while nothing has vested) and `withdrawableTokens(id)` (what could be taken right now). A `withdrawableTokens` of 0 today says nothing about next month.

## 5. What to report

1. The amount, the lock id, the lock owner and the unlock date in the user's timezone.
2. Whether it can be pulled early, with the source condition that settled it.
3. The size against the exit: allocation tokens versus the pair's token reserve, because an allocation worth several times the pool's whole token side is the risk that the lock is deferring, and unlocking it is a destruction event rather than a dilution.
4. **The allocations that are not locked**, read from `marketing()` and friends. A verified one-year foundation lock says nothing about a marketing wallet holding a comparable amount, and reporting the lock without the unlocked sibling is a half-answer.
5. Date discrepancies between the team's public claim and the chain (a tweet naming a date a day off) as a footnote, not as evidence of bad faith.

## 6. Follow the unlocked allocation two hops to the pair

An unlocked allocation is only a risk statement until you find out who is selling it. Trace it:

1. List the allocation wallet's outflows (the 5000-block chunk scan) and read each recipient's `getCode` size. A recipient with **0 bytes of code and 0 remaining balance** is a pass-through, not a holder: it received allocation tokens and forwarded them on.
2. Follow each pass-through recipient's own outflows. On one audited launch, 777M of a 6.3B marketing allocation left in 20 transfers, and at least 154M landed on a single EOA that had already routed **4.7B tokens into the pair across 2,552 transactions** starting minutes after launch. That address, not the marketing wallet, is the seller, and it explains a downtrend that a "no team outflows" check would have missed.
3. Count pair-directed sells directly instead of summing two full scans: one filtered scan with `topics: [Transfer, pad(seller), pad(pair)]` returns every sell that address made, its total, and its first and last activity. That is a single pass, and its `len()` plus sum is the seller-concentration number to quote.
4. Re-check the near term too: an empty outflow scan over the last ~3000 blocks is positive evidence the wallet is quiet *now*, which is a different sentence from "it never sold".

Report the machine, not the label: "one address has sent N tokens to the pair across M txs, still active" is the answer to "kok turun terus".

## Pitfalls

- **Sourcify v2 field names are fixed**: `?fields=abi` and `?fields=sources` work, `?fields=abi,name` is rejected with `Field selector name is not a valid field`. An empty/`404` body from a wrong field list looks like "not verified" — retry with `fields=abi` before saying the contract is unverified.
- **A locker holds many projects' tokens.** Contract-wide counters (`totalTokenLockedCount`) are platform-wide and in the hundreds of thousands; use the per-token reads (`totalLockCountForToken`) for anything you quote, and never present the global number as this project's lock count.
- **`balanceOf(locker)` includes stray dust** from unrelated senders, so it can exceed the locked amount. Quote the lock record's `amount`, not the contract balance.
- **The lock owner is usually not the treasury.** A locker record names whoever called `lock()`, often an EOA that received the tokens one block earlier. That key, not the multisig, controls the unlock.
- **Do not run two full-history scans in one call.** Two complete outflow scans plus per-log `getBlockByNumber` lookups over ~90k blocks of BSC blow past a 300s budget and die at the timeout with no output at all. Filter to the topics you actually need (seller-to-pair), split the scans across calls, and print a chunk counter so a slow scan fails visibly instead of silently.

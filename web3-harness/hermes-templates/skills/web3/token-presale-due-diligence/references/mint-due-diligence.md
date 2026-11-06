# Probe Recipes: Mint / Fair-Launch Due Diligence (BSC)

Run in this order. Each probe either clears the project or yields a number worth quoting in the verdict.

## 1. Verified source (Sourcify v2, no key)

```
curl -sL 'https://sourcify.dev/server/v2/contract/56/<address>?fields=sources,abi' -o /tmp/c.json
```

```python
import json
d = json.loads(open('/tmp/c.json', encoding='utf-8', errors='replace').read(), strict=False)
src = d['sources']; main = [k for k in src if k.endswith('<CONTRACT>.sol')][0]
print(src[main]['content'])
```

- v1 paths (`/server/repository/...`, `/contracts/full_match/...`) return a JSON 404 notice and never the code.
- Source strings carry raw control characters; strict JSON parsing raises `Invalid control character at: ...`.
- Human-readable fallback: `https://repo.sourcify.dev/<chainId>/<address>` shows exact-match status, deployer, compiler, verification time. Recently verified plus a fresh deployer EOA is a signal, not proof of fraud.
- Read the whole mint contract. The interesting parts are the constants (price, per-wallet cap, tokens per share), the payment split, the treasury/LP destinations, and whether an owner, withdraw or upgrade function exists.

## 2. Selectors without eth_utils

```python
from Crypto.Hash import keccak
k = keccak.new(digest_bits=256); k.update(b'paidShares()')
'0x' + k.hexdigest()[:8]   # -> 0x7b6179c2
```

Then `eth_call` the selector on `https://bsc-dataseed.binance.org`.

## 3. Reading live state

```python
import json, subprocess
RPC = 'https://bsc-dataseed.binance.org'
def call(to, data):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
               "params": [{"to": to, "data": data}, "latest"]}
    out = subprocess.run(['curl', '-s', '-X', 'POST', RPC,
                          '-H', 'Content-Type: application/json',
                          '-d', json.dumps(payload)],
                         capture_output=True, text=True).stdout
    r = json.loads(out)
    return int(r['result'], 16) if r.get('result') not in (None, '0x') else None
```

State worth reading on a fair-mint contract: `sharesMinted()`, `paidShares()`, `freeMinted()`, `deadline()`, `mintingOpen()`, `poolOpen()`, `token()`, `pair()`, `treasury()`.

When a dozen typed reads are needed at once, viem in the harness is faster than hand-rolled `eth_call`: write the `.mjs` probe **into `~/.hermes/web3-harness`** and `cd` there before `node`, because viem exists only in that `node_modules` and a script run from `~/.hermes/cache/scratch` dies with `ERR_MODULE_NOT_FOUND: Cannot find package 'viem'`. Load the endpoint from that dir's `.env` (`BSC_RPC_URL`) instead of hardcoding one, and redact the URL when printing diagnostics.

**Liquidity proof:** read the pair's `getReserves()` and its own `totalSupply()` (LP shares). Both zero is the evidence the pool was never seeded; a bare `poolOpen == false` does not exclude a donated or pre-seeded pair. `balanceOf(pair)` on the token should also still be 0 before launch.

## 4. Decoding returns

- **Address**: read the uint256, hex it, take the **last 40 chars**. Confirm with `name()`/`symbol()` on the decoded address before quoting it as a gate or a treasury.
- **String**: byte 32 = offset, bytes 32..64 = length, then `b[off:off+len].decode()`.
- **ERC721 `totalSupply`**: often absent. `0x` means unsupported, not zero supply; use `balanceOf`/`name`.
- **ERC20 balance**: `balanceOf` selector `0x70a08231` + 24 zero-pad + address.

## 5. Exit math (the number that decides the verdict)

```python
paid, free = 300, 8507
lp_usdt = paid * 0.70              # only the LP split is real money
lp_tokens = paid * 7_000_000       # LP_TOKENS_PER_PAID from the contract

def sell(amt, u=lp_usdt, t=lp_tokens, fee=0.0025):
    a = amt * (1 - fee)
    return u - (u * t) / (t + a)
```

Iterate 10,000,000-token sells across all free claimers and report: how many can exit at all, the 1st, 10th, 100th, 500th payout, and the total payment token that can leave the pool. Compare `circulating_supply * open_price` (the FDV the site implies) against real LP depth; the gap is the story.

## 6. Is the campaign actually funded?

1. In the rendered HTML grep `fetch(` and `/api/` paths. Typical: `/api/stats`, `/api/submit`, `/api/status?wallet=`, `/api/kol/stats`.
2. `curl -s https://site/api/stats` — compare `approved`, `pending`, `paid`, `cap * reward`.
3. `paid: 0` next to a large approved/pending count plus a treasury smaller than the advertised pool is decisive.
4. Treasury check: `eth_getCode` (2 hex chars = EOA), `balanceOf`, and `eth_getLogs` with the payment token address, `Transfer` topic `0xddf252ad...`, `from` = treasury, over the last ~20k blocks. Zero outflows while the site claims it pays users means nobody was paid.

```python
def pad(a): return '0x' + '0' * 24 + a[2:].lower()
T = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
logs = rpc('eth_getLogs', [{'address': usdt, 'fromBlock': hex(bn - 20000),
                            'toBlock': 'latest', 'topics': [T, pad(treasury)]}])
```

## 7. Safety surface

- Grep the rendered instructions for the approval amount. An exact-amount `approve` is bounded; `uint256.max` is not.
- No seed-phrase or private-key field is a green flag for theft risk only.
- Never interact with `/api/submit` using fabricated screenshots, links or addresses. Read the stats endpoint instead.

## 8. Eligibility and gas before a free claim

```python
# per candidate signer address
gate_bal = call(gate_nft, '0x70a08231' + '0' * 24 + addr.lower()[2:])           # >0 required
free_ok  = call(mint, sel('freeAvailable(address)') + '0' * 24 + addr.lower()[2:]) == 1
already  = call(mint, sel('mintedBy(address)') + '0' * 24 + addr.lower()[2:])
has_id   = call(mint, sel('hasAgentId(address)') + '0' * 24 + addr.lower()[2:]) == 1
open_    = call(mint, sel('mintingOpen()'))
```

Free calldata is `mint(0)`: `0xa0712d68` plus a 32-byte zero. The gas quote must come from the signer:

```python
est = rpc('eth_estimateGas', [{'from': signer, 'to': mint, 'data': free_calldata}])['result']
gp  = int(rpc('eth_gasPrice', [])['result'], 16)
cost_native = int(est, 16) * gp / 1e18
```

A `mint(0)` on this class of contract estimates roughly 130k-150k gas; a site-suggested 600k limit is a ceiling and would overstate the cost about five-fold if quoted as-is.

Lane check before previewing: `baw wallet settings --json` → `devMode.enabled` must be true. `baw wallet agent-id --json` returns `{claimed, handle, agentId}`, but claim status is not proof the NFT sits in the current wallet, so confirm `balanceOf` on-chain per address.

## Reference point: a real verdict

Verified, ownerless fair-mint contract, 18,888 shares, 1 USDT per paid share, 1 free share per gated wallet. On chain: 300 paid shares (300 USDT raised), 8,507 free mints, so the LP would hold 210 USDT against 85 billion free tokens. Simulated exit: first seller ~$0.99, 100th $0.46, 500th $0.09, whole cohort ~$205. Campaign backend returned `approved: 140, pending: 1600, paid: 0` against a 10,000 USDT promise; treasury EOA held ~108 USDT with zero USDT outflows. Verdict: not a drainer, unfunded reward, user is exit liquidity. That is the shape of output this skill produces.

Execution follow-up on the same project: the free claim was real (gate NFT held, `freeAvailable` true, mint open), gas estimated 136,394 at 0.05 gwei for about 0.0000068 BNB, and the only blocker was Developer Mode off on the agentic wallet while the self-custody key held 0 BNB and no gate NFT. That split, an eligible lane versus a capable lane, is the normal case: check both before promising a signature.

## 9. Receipt verification after execute

`contract-call execute` returns the order and hash, not the outcome:

```json
{"orderId": "...", "status": "BROADCASTED", "txHash": "0x..."}
```

`BROADCASTED` only means submitted. Confirm on chain before reporting success:

```python
r = rpc('eth_getTransactionReceipt', [tx])['result']
status   = r['status']                      # 0x1 = success
block    = int(r['blockNumber'], 16)
gas_used = int(r['gasUsed'], 16)
fee_bnb  = gas_used * int(r['effectiveGasPrice'], 16) / 1e18
bal      = call(token, '0x70a08231' + '0' * 24 + signer.lower()[2:]) / 1e18
minted   = call(mint, '0x505e05fd')          # sharesMinted grew as expected
```

A receipt can be absent for a few seconds after broadcast; poll `eth_getTransactionReceipt` a handful of times rather than declaring failure.

If `requireConfirmation` was true in the preview, execute returns `PENDING_CONFIRMATION` with a null hash: the user must approve in the Binance App, and the hash arrives later.

## 10. Why the wallet UI shows nothing

Dev-mode contract calls are logged as contract calls, not orders:

```
baw wallet tx-history --binanceChainId 56 --json
# -> transactions[0].txType = "contract_call"
#    .txHash, .txTime, .status = "confirmed"
#    .txHashList[0].networkFee.feeValue (wei string)
#    .txHashList[0].instructions.send / .receive
```

The App's Order History page lists market, limit and prediction orders only, so a successful mint leaves it looking empty. Point the user at activity history instead of debugging a nonexistent failure. `tx-history` has no `--limit` option; passing it fails with `unknown option '--limit'`.

## 11. Post-open watch job

Two jobs, both report-only unless the user gave an explicit sell threshold:

- one-shot at the pool deadline plus one minute (e.g. `2026-11-04T19:30:00`), reporting `poolOpen()`, reserves, spot price, LP depth, modelled sell-out and the holder balance;
- recurring every 15 minutes for about two hours after that (`*/15 20-21 4 11 *`, `repeat: 8`) so a price move is not missed.

**Session validity gates an unattended send.** A job that must SIGN at a future time only works if the agentic wallet session is still alive then:

```bash
baw wallet settings --json   # -> data.sessionExpireTime, data.inactiveSignOutTime,
                             #    data.signInMaxTime, data.maxSigninDuration ("48h"),
                             #    data.devMode.expiresAt
```

If `sessionExpireTime` lands before the event, the run dies at execute time and the only fix is `baw auth signin`, which just prints a QR for the user's Wallet App. So: report-only job, plus one line asking the user to sign in shortly before the window (one sign-in covers up to 48h). `devMode.expiresAt` is a separate clock, 7 days per grant.

Put the contract, pair, token and wallet addresses plus every selector in the job prompt: cron runs in a fresh session with no chat context. Include an explicit "do not sell, do not sign" line, because a scheduled run cannot ask for confirmation. After the deadline the pool can be opened by anyone (`openPool()` is permissionless), so the job never needs to send that transaction itself.

## 13. Agent-ID gated fair mint (AgentLaunch shape)

One contract is both the ERC20 and the sale: paid shares, one free share per gate ID, per-ID quota plus referral bonus, atomic auto-launch into a V2 pair with the LP minted to `0xdead`, and a `refundBps` refund if the cap is missed. No owner and no withdraw in the clean version, so the audit is almost entirely economics.

**Read the config from the contract, not the site's prompt.** The page ships an agent prompt with a JSON block naming `contract` and `agentIdRegistry`; that registry is usually the raw SPACE ID handle registry while the contract actually calls a read-only wrapper. Trust only `identity()`, `treasury()`, `quote()`, `pair()` read over RPC.

```python
for sig in ['identity()','treasury()','quote()','pair()','price()','maxShares()',
            'freeShares()','quotaPerId()','tokensPerShare()','liquidityBps()',
            'refundBps()','buyTaxBps()','sellTaxBps()','sold()','freeClaimed()',
            'phase()','launched()','deadline()']:
    print(sig, call(C, '0x' + sel(sig)))
```

Ledger check: the contract's `quote` balance must equal `sold * price` exactly (3.412 WBNB against 1705 shares at 0.002 BNB is a match; a gap means the page is not the ledger). `balanceOf(pair)` is 0 and reserves are 0 until launch, which is correct, not a red flag.

**Gate eligibility.** The wrapper (`AgentIdentity` in this shape) is read-only and hardcodes the registry plus `CHAIN_ID`; it requires `handleOf(addr)` to be a lowercase alnum handle whose `ownerOf(labelhash)` and `ownerOfHandle(handle)` both equal the address, then returns `keccak256("binance.agent-id.v1", 56, registry, label)`.

```python
print(call(wrapper, '0x' + sel('identityOf(address)') + pad(addr)))   # bytes32(0) = no ID
print(call(registry, '0x' + sel('handleOf(address)') + pad(addr)))    # ABI string -> the handle
```

Handles are soulbound (approve/transfer paths are `pure` reverts), so the gate cannot be bulk-bought for sybil, but the registry owner can still `adminRegister` handles, which caps how independent the thousands of "unique" IDs really are. Say which of the two you verified.

**Reading `info()` (strings inside the struct).** Word 0 is the offset to the struct; every field is offset from that struct start, so `treasury` is word 3, `quote` word 4, `native` word 5, `pair` word 6, `price` word 7 and so on down to `phase` word 20. Decoding words in absolute order shifts every field by two.

**Per-ID quota and the real remaining.** `remaining = quotaPerId + bonusById[id] - mintedById[id]`; `bonus` grows by one each time an invitee pays for the first time (cap `MAX_BONUS = 10`). `userInfo(addr)` returns `(id, remaining, freeClaimed, paidShares, bonus, referrer, balance)`; `paidShares` is per address while the quota is per ID, so the same ID from a second address still sees the full quota.

```python
ui = call(C, '0x' + sel('userInfo(address)') + pad(addr))   # 7 words, order above
free_open = call(C, '0x' + sel('freeClaimed()')) < call(C, '0x' + sel('freeShares()'))
```

**Exit math, per share.** `tokensPerShare` is derived so the seeded price equals `price * LAUNCH_PRICE_MULTIPLE`, and `poolTokens = tps * maxShares * liquidityBps / (10000 * multiple)`:

```python
tps   = tokens_per_share / 1e18
lp_q  = maxShares * price * liquidityBps / 10000      # e.g. 20 * 0.8 = 16 BNB
lp_t  = tps * maxShares * liquidityBps / 20000
x     = n_shares * tps * (1 - sell_tax)              # constant product, tax on tokens
payout = lp_q * x / (lp_t + x)
```

Quote at `n = 0, 1000, freeShares, maxShares+freeShares` and add the per-share figure, because with a small share size the whole cohort still recovers a third of entry instead of cents. Also state the hard cap: the total quote that can ever leave is below `lp_q`, whatever FDV the site implies.

**Refund branch.** Unfilled at `deadline` (`phase() == 4`) returns `refundBps` of paid value and sends the rest to `treasury`; sold out but launch failed returns 100%. That haircut (20% in the 8000-bps case) plus the lockup to the deadline (transfers revert `TransfersLocked` until `launched`) is the downside to state before recommending a position, and it doubles as the team's minimum revenue.

**Paid mint execution.** The preview carries the payment itself, so the calldata encodes both args and the value carries `shares * price`:

```python
data = '0x' + sel('mint(uint256,address)') + f'{shares:064x}' + '0' * 64   # referrer = 0x0
# baw contract-call preview --binanceChainId 56 --from <wallet> --to <C> \
#   --value <shares*price wei> --inputData <data> --json
```

Accept the preview only when `simulationResult.balanceChanges` shows exactly one native debit of `shares * price`, one ERC20 credit of `shares * tokensPerShare`, empty `authorityChanges`/`allowanceChanges`, empty `risks.riskDetails`, and `simulationErrorDetail: null`. `requireConfirmation: false` means no App tap is needed, not that the user's own go-ahead can be skipped. Raise `--gasLimit` to 1,000,000 only when this mint is the closing share that also builds the pool.

**Gas and sizing.** `eth_estimateGas` on `mint(uint256,address)` with `value = shares * price` lands near 154k at 1 gwei, about 0.00015 BNB. Compare the signer's native balance against `shares * price + gas` and quote the largest affordable share count, not the quota. The estimate is a ceiling, not the cost: BSC gas price often sits far under 1 gwei, so a 148.7k-gas mint settled at ~0.0000094 BNB (~$0.007) against a $0.11 estimate. Quote the receipt's `gasUsed * effectiveGasPrice` afterwards and present the pre-trade figure as a maximum.

**Variant: constant-based template (JinLong / SAGENT shape).** Same economics, different surface, so re-derive the reads instead of reusing the shape above. Everything is an immutable constant with no setters: `PAID_SHARES`, `FREE_SHARES`, `BASE_QUOTA`, `MAX_BONUS`, `LIQUIDITY_BPS`, `TAX_BPS`, `OPEN_PRICE_MULTIPLE`, `MINT_DURATION`, `LAUNCH_GRACE`, `REFUND_BPS`, `DEAD`. Views are the uppercase constants themselves plus `sold()`, `freeClaimed()`, `refundedShares()`, `launched()`, `startedAt()`, `soldOutAt()`, `freeAllocation(addr)`, `paidSharesOf(addr)`, `remainingQuota(bytes32 id)`, `freeClaimedById(bytes32)`.

- `info()` here returns five plain words `(phase, sold, freeClaimed, deadline, raised)`, so decode them in absolute order; the struct-offset pitfall belongs to the string-returning variant only.
- `mint(uint256,bytes32)` takes a referral **id**, not an address (`IIdentity.idOfHandle(handle)`), so its selector differs from `mint(uint256,address)`. Take the selector from the recovered ABI every time.
- `pair` is created in the constructor, so reserves 0/0 and `balanceOf(pair) == 0` before launch is correct, not a broken deployment.
- `claimFree()` is a separate function and reverts a zero-quantity mint with `InvalidAmount`; a second claim or a drained free cap reverts `QuotaExceeded`, and a wallet with no gate id reverts `NoIdentity`. Transfers revert `TransfersLocked` until `launched`.
- At launch every unclaimed free share is burned (`UnclaimedFreeBurned`). A free claim in a mint that misses its cap therefore ends as gas spent and nothing received. State that before asking for a signature, and quote the refund haircut (`REFUND_BPS`, e.g. 7000 = 30% kept by treasury) as the paid lane's downside.

**Variant: agent-gated ERC721 collection (`claimFree(string)` / `paidMint(uint256,string)`).** A pure NFT collection with no token, no pair and no market contract: the gate is a Binance `.ai` Agent ID handle, the price is a four-rung ladder, and the only thing that can be audited is supply, gate, proceeds routing and whether any secondary market exists at all.

- **ABI comes from the page**, and it is five entries: `status() view returns (uint256,uint256,uint256,uint256,uint256)` = `(minted, freeClaimed, paidMinted, currentPriceWei, currentTier)`, `quote(uint256)`, `eligibility(address,string) returns (bytes32 id, uint256 freeLeft, uint256 paidLeft)`, `claimFree(string)`, `paidMint(uint256,string) payable`. Decode `status` words in absolute order (all plain uint256); `freeClaimed == free cap` is the whole verdict on the free lane no matter what the headline still advertises.
- **Encode the string arg yourself**, since a raw zero word in slot 2 reverts bare `0x`:

```python
def pad(a): return a.lower().replace('0x','').rjust(64,'0')
def enc_str(your_addr, s):
    hb = s.encode()
    head = pad(your_addr) + pad('0x40')
    tail = hex(len(hb))[2:].rjust(64,'0') + hb.hex().ljust(((len(hb)+31)//32)*64,'0')
    return head + tail
# eligibility -> id (bytes32), freeLeft, paidLeft; id == 0 means "this wallet does not own that handle"
```

- **Gate = the SPACE ID wrapper, and it may expose only `handleOf` + `balanceOf`.** `identityOf` and `totalSupply` reverting here is normal, not a wrong address: `handleOf(addr)` returns the handle as an ABI string (empty string = no ID) and `balanceOf(addr)` is 1 for the owning wallet. Resolve the wrapper address from the mint bytecode, because `identity()` / `gate()` / `registry()` / `treasury()` all revert on this shape.
- **Proceeds routing.** Only one PUSH20 constant exists in the code, its 32-byte-padded twin appears twice: once in a view that returns it and once in a `7f<addr>6001600160a01b03165a` (push, GAS, CALL) run. Contract balance 0 plus that CALL means each paid mint forwards its value straight to the dev EOA; check the EOA's balance and nonce to show the money is real, and do not describe the contract as holding user funds.
- **Admin surface check by selector, not by claim.** Compute selectors for `owner()`, `transferOwnership`, `renounceOwnership`, `withdraw` (both arities), `upgradeTo`, `setPrice`, `pause` and intersect them with the `63<selector>` constants in the bytecode. All absent is a credible "immutable, no owner" and can be credited; the website's own sentence is not the evidence.
- **No market is the decisive number for this shape.** With no pair, no marketplace listing and no bids, the exit does not exist rather than being thin, so the report says "koleksi, bukan investasi": cost is price plus gas (~120k gas for a single paid mint) and the amount should be money the user is fine to lose. Never reuse the fair-mint exit-curve language here, there is no curve.
- **Timestamp logs sparingly.** An `eth_getBlockByNumber` per log inside a loop trips the node's rate limit and returns an error dict, so `block['timestamp']` raises `KeyError`. Fetch the first, last and a couple of quantile blocks only, guard with `.get('timestamp')`, and chunk `eth_getLogs` at 1500 blocks on `48.club` (a 40000-block window scans in ~27 calls).
- Calibration from one of these: 1,240/5,000 minted in ~5h, free 1,000/1,000 drained inside the same window, paid tier 1 at 0.0005 BNB with 240/1,000 used, treasury EOA at ~0.17 BNB, no market anywhere. Verdict: free lane gone, paid is a ~$0.35 lottery ticket, skip unless the user just wants a collectible.

### 13a. Racing an FCFS open (fixed free cap, exact start time)

A free lane that opens at a fixed timestamp with a hard cap (first N claims win) cannot be scheduled at minute granularity and handed to a human: the reaction window is the first seconds after `startTime()`. Two facts make the race winnable without any special tooling.

**Turn the contract's own revert table into a state probe.** The site's inline script usually ships an error-selector map next to the ABI, and that map is the contract's custom-error table verbatim:

```js
const ERR = {"0x0d3f7776":["Not open yet. Wait for the countdown."],
             "0xfbd65f7d":["All 800 free shares are taken. Ignite paid shares instead."],
             "0xc1fba8cf":["This wallet holds no .ai Agent ID."],
             "0x17bf413b":["This Agent ID already took its free share."], ...}
```

`eth_estimateGas` on the exact claim calldata with `from` = the signing wallet then returns one of a few states in a single read, and broadcasts nothing:

```
0x0d3f7776 NotOpen        -> wait, re-poll
default revert (no data)  -> the call is failing for another reason, inspect
"result" present          -> open AND eligible AND room: fire now
0xfbd65f7d FreeGone       -> abort, cap full
0xc1fba8cf NoIdentity     -> abort, wrong wallet
0x17bf413b AlreadyClaimed -> abort, idempotent re-run
```

The revert data arrives as `error.data` (a plain hex string on `48.club`); a `0x`-prefixed 4-byte selector is enough to branch on. Keep the selector map in the script so an unattended abort prints a readable reason instead of a hex code. **Ordering trap:** these contracts check the window before the gate, so a pre-open estimate says nothing about eligibility. Prove the gate separately by reading the contract's own `account(addr)` / `hasAgentId(addr)` while the lane is still closed.

**Fire with preview then execute on the first clean simulation.** There is no legal way to send before the window opens, so the fastest sequence is to poll the estimate (roughly 0.12 s apart, starting ~1 s before `startTime`) and on the first clean read run `baw contract-call preview` followed by `contract-call execute`. Two backend round trips, a few seconds. That budget is what buys the place: measured on an 800-slot soulbound-gated cap, the open was detected at +0.38 s and the tx broadcast at +1.42 s, landing at share #473 of 800, while the whole cap emptied in 24 seconds (first claim 13:30:01 WIB, last 13:30:25). A 1.4 s fire path wins a seat; a runner that starts a few seconds late or adds a third round trip loses it, and the loss surfaces only as `FreeGone`. Retry the preview a few times rather than giving up on one `SERVICE_ERROR` (which is how a still-closed or just-filled simulation surfaces), and parse the hash from either `data.txHash` or a top-level `txHash`.

**You cannot buy priority, so escalate after broadcast.** `contract-call` has no gas-price or gas-level flag, so "raise the gas" can only mean resubmitting: poll `eth_getTransactionReceipt` every ~0.4 s and call `baw wallet speed-up <txHash> --level HIGH --binanceChainId 56 --json` (×1.25; `LOW` is ×1.1) when the tx is still pending after ~4 s, at most twice, logging each bump. Every `baw` call spends ~0.5-0.7 s in node startup, so the fire path is preview+execute ≈ 1.2 s and any extra round trip costs real ground on a fixed cap.

**Print the latency so a lost race is legible.** Report the seconds from `startTime` to the clean simulation, from there to the broadcast hash, plus block, `gasUsed` and fee, then re-read the contract's own `account(addr)` and counters to prove the claim landed. "Detected at +0.4 s, broadcast at +1.8 s, 1 share taken" and "FreeGone at +2.1 s" are both useful; a bare failure is not. Say plainly that a fixed cap contested by other agents is never guaranteed however well the run is prepared, so the prep is not read as a promise.

**Schedule a `no_agent` script a minute BEFORE the open, not at the open minute.** Cron fires on the minute and drifts, so a job created for 13:30 may run at 13:30:40; starting at 13:29 and letting the script sleep to `startTime - 1.5` then poll absorbs that drift and makes the script's own poll authoritative. Keep a hard deadline (~a few minutes) and print an explicit abort line for every state, so an unattended failure is readable in the delivered stdout. A `no_agent` job's stdout is delivered verbatim, so the script IS the report; a non-zero exit is classified as a failure, so `exit 0` on a legitimate "free cap was already full" outcome.

**Make the script testable without waiting, and dry-runnable.**:

```python
START = int(os.environ.get("BOMB_START", 1793773800))   # open timestamp
DEADLINE_S = int(os.environ.get("BOMB_DEADLINE", 240))
DRY = os.environ.get("BOMB_DRY") == "1"                 # stop after preview, no execute
```

A pre-open run with `BOMB_START=0 BOMB_DEADLINE=4` then exercises the RPC fallback, the revert decoding and the abort path in seconds. Separately, a `preview` of a harmless calldata (`0x80528ae` = `stats()` on this shape) confirms the response shape (`data.requestId`, `data.expiresAt`, `data.gasLimit`, `requireConfirmation`) without broadcasting, and proves the `baw` env/PATH wiring that cron will use. `baw` lives under `~/.nvm/.../bin`, so pass an explicit `PATH` to `subprocess.run` rather than trusting cron's inherited environment.

**Post the alert from the script.** A direct `baw contract-call` broadcasts nothing on its own, so the script calls `order_alert.py` after the receipt is confirmed (see "Announcing the Execution" in SKILL.md). Pass `--wait` and log the exit code, so the run's own stdout carries the Discord message id instead of an unverified "posted" line.

**After the race: prove the fill and count the cohort from the contract's own logs.** Read `account(addr)` on the mint for `hasId`, `number` (the share index claimed), `genesis` and `squad`, plus `freeClaimed(id)`, and put the share number in the report: "share #473 of 800" is the sentence that says the race was won. For the cohort, `eth_getLogs` on the mint over the open block onwards, group by `topics[0]`, and take the topic whose row count equals the free cap: on this shape `FreeClaimed(address indexed wallet, bytes32 indexed id, uint256 number)` had exactly 800 rows, with the claimer in `topics[1]` (zero-padded) and the share number in `data`. Take addresses from the topic word, not `data`, or 800 claimers read as one wallet. Quote distinct claimers, the first and last claim timestamps, and how long the cap took to empty.

**While the pool is unseeded, "total pool" means the accumulator inside the mint contract, not the pair.** The AMM pair answers `getReserves()` 0/0 and LP `totalSupply()` 0 until ignition, so replying to "poolnya ada berapa?" with the pair says zero and tells the user nothing. Quote the mint contract's own `parked` (the LP split of paid so far) against its ignition target, e.g. `0.098 BNB / 12.88 BNB = 0.8%`, add the raise it came from (`paidWei`) and the shares sold against the ignition threshold, then give the ETA derived from the observed paid pace (paid shares / minutes since open, converted to hours to fill the remaining gap). Close with the consequence for the free holder: no pool means the free allocation is still worth nothing, however fast the claim was.

## 12. Unverified NFT plus its own market contract

When the collection AND the marketplace are self-hosted, unverified, and the site only renders counters, the ABI has to come from the page. Everything below runs on `https://rpc-bsc.48.club`.

**Recover the ABI from the inline script.** Pages built with a CDN ethers bundle keep the ABI in the HTML:

```bash
grep -n -iE 'abi|Contract\(|ethers' page.html
sed -n '/NFT_ABI = \[/,/\];/p' page.html      # ethers string-array ABI
```

That yields exact names such as `publicMinted()`, `difficultyBits()`, `hasMinted(address)`, `listedCount()`, `listedIdAt(uint256)`, `getListing(uint256)`, `LISTING_FEE()`, `MIN_PRICE()`, `tradingOpen()` plus the event signatures, so no guessing at selectors. Cross-check one selector against its keccak hash.

**Enumerate the orderbook, do not trust `totalVolume()`.** View functions like `totalVolume` may simply not exist (bare `execution reverted: 0x`); the listed set does:

```python
cnt = call(MKT, 'listedCount()')
for i in range(cnt):
    tid = int(call(MKT, 'listedIdAt(uint256)', f'{i:064x}'), 16)
    g   = call(MKT, 'getListing(uint256)', f'{tid:064x}')   # (address seller, uint256 price)
    seller = '0x' + g[2+24:2+64]; price = int(g[2+64:2+128], 16)
```

Report: active listings, unique sellers, floor, median, how many asks sit exactly at `MIN_PRICE()`, and listings as a share of minted supply. Hundreds of unique sellers stacked at the minimum price is a queue to exit, not a market.

**Count lifetime sales from the market's own `Sale` log.** Take the topic from the site's `ethers.id("Sale(...)")` line or compute it. Scan from the deployment block in 1500-block chunks, checking each chunk for an `error` key and printing the failed count; a chunk range that some node rejects returns `result: []`, which silently reads as zero sales.

```python
sales = [(int(l['blockNumber'],16), int(l['topics'][1],16),
          '0x'+l['topics'][2][-40:], '0x'+l['topics'][3][-40:],
          int(l['data'][2:][:64],16)) for l in logs]
```

Quote: number of sales, total volume in native units and fiat, unique buyers, whether every sale hit the floor, and the block of the last sale. Six sales at the minimum price against 190+ asks is the decisive sentence.

**Cross-check supply distribution.** `publicMinted()` plus `Transfer` logs from the zero address give mint count; `balanceOf(owner)` shows the team's retained stock; distinct `to` addresses approximate holder count. A mint counter drifting a few units from the page is normal, thousands apart means the page is static markup.

**PoW phase arithmetic.** `difficultyBits()` = required leading zero bits, so expected hashes = `2^bits`. Measure once, then quote both: python keccak ~145k H/s on a 2-core VPS (30 bits ~2 h, 33 bits ~16 h), browser JS in the same order or slower, GPU miner orders of magnitude faster. State the live phase and the breakpoints, because each added bit doubles the work and the ladder advances while users mine.

**Approval caveat specific to this shape.** Listing asks for `setApprovalForAll(market, true)` on a contract with no source and a live `owner()`. Say plainly that whoever controls it can move every approved token, and that the only reason the risk is small is the collection's near-zero floor, not the contract's safety.

## 14. Discovery: find the next mint without a website

Invitation-based fair launches name their own event signatures, so the chain itself is the alerting feed. One `eth_getLogs` per 1500-4000 block window with only `topics[0]` set and no address filter, over the last ~12k-30k blocks (a few hours of BSC at 0.75 s blocks), surfaces every live mint on the chain. Group hits by `address` and count them; the counts are already the metric you want:

```python
WATCH = {
  topic('Started(uint256)'): 'Started',
  topic('Minted(address,bytes32,uint256,bytes32)'): 'Minted(agent-gated)',
  topic('FreeClaimed(address,bytes32)'): 'FreeClaimed(agent-gated)',
  topic('Launched(address,uint256)'): 'Launched(pool built)',
  topic('FreeClaimed(address,uint256)'): 'FreeClaimed(generic)',
}
```

Read the pattern rather than the total:

- hundreds of `FreeClaimed` in a few hours with zero `Minted` = free pool draining while nobody pays, the exit-liquidity shape before it shows up anywhere.
- `Minted` events at a steady rate plus a rising count = a real queue; audit the top address immediately, because the useful window is while the paid pool is still open.
- `Launched` with no `Started` in the window = pool already built, so the only entry left is on the market at whatever price the bots set.
- `sold() == 0` with a live `pair()` whose reserves are 0/0 is pre-launch, not broken: guard the spot-price and exit-curve math against a zero reserve instead of dividing.

`scripts/mint_screener.py discover --blocks N` is this recipe; `audit --ca <addr> --skip-logs` is the fast shape check on a hit, and the full `audit` is the deep one.

**A log scan is only as good as its reconciliation.** Public nodes both cap ranges (48.club 4000-5000, publicnode 50k, dataseed/defibit ~100) and, worse, some serve a block yet answer `[]` for it, which under-reads the mint and turns a sold-out project into a thin one. Scan, then require `sum(Minted.shares) == sold()` and `len(FreeClaimed) == freeClaimed()`; on a mismatch widen the start block backwards (the identity quota opens before the first paid mint, so the earliest events sit below any guessed `latest - N`) and re-scan. A `sold()` of 10,000 against a scan totalling 8,619 is a bad range, never a partial sellout.

**How long the free lane stays open (measure it, do not assume).** The free cap is a fraction of the paid cap and usually drains first, so the free lane sets the reaction window, not the sellout. Take the first and last `FreeClaimed` blocks, fetch their timestamps with `eth_getBlockByNumber`, and quote the 50% and 100% times against `startedAt()`:

```python
blocks = sorted(int(l['blockNumber'], 16) for l in free_logs)
t = lambda b: int(rpc('eth_getBlockByNumber', [hex(b), False])['timestamp'], 16)
mid, end = t(blocks[len(blocks)//2]), t(blocks[-1])
print((mid - t(blocks[0]))/3600, 'h to 50%', (end - t(blocks[0]))/3600, 'h to 100%')
```

On one audited mint that came out to 2.34h for 50% and 2.85h for 100% while the paid pool took 8.14h to fill, so an alert at "90% claimed" left roughly ten minutes to act while an alert on the opening left nearly three hours. Choose the poll interval against this measured drain, and note that `sold()` reaching the cap closes the free lane early regardless of how much free allocation is left.

**Calibration: two real results of this recipe.**

- A mint that sold out in 8.1 h: 10,000/10,000 paid plus 4,444/4,444 free, 1,240 paying wallets of which 1,000 took exactly the 9-share base quota, verified source with no withdraw or upgrade, owner able only to `start`/`setPaused`/`retryLaunch`, LP 100% burned to `0xdead`, 1.5% pair tax. Raise 30,000 quote tokens with 80% into the pool: depth ~$8.3k against a $9.3k raise. Full-cohort dump returned $5.5k (59% of entry), last seller $0.13 a share, entry $0.93, spot $1.12. Swap volume $394k in 19 h came from 56 senders, one bot at 36% of swaps and the top four near 85% of volume. Verdict: cleanest execution of its kind and still too thin to size into, so "successful mint" described the sale, not the exit.
- At the same moment `discover` found a sibling still minting: free pool 3,000/3,000 claimed, paid 10 of 10,000, pair not seeded. Same event signatures, opposite phase: sellout speed and the paid-versus-free split separate them, not the marketing.

## 15. The radar script is also a probe library

For a one-off free-lane check on a bare address, do not re-write `eth_call` plumbing: import the cron radar and reuse its keccak, selector, RPC and eligibility helpers. It already carries a pure-Python keccak (no `Crypto`/`eth_utils`), a two-RPC fallback, and the gate/NFT eligibility resolver.

```python
import importlib.util
spec = importlib.util.spec_from_file_location("radar", "/home/ubuntu/.hermes/scripts/agent_mint_radar.py")
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)

CA = "0x..."
print(r.sym_of(CA), r.view_int(CA, ["FREE_SHARES()", "freeShares()"]),
      r.view_int(CA, ["freeClaimed()", "freeMinted()"]))
print(r.eligibility(CA, r.WALLETS))                    # per-wallet gate verdict, both lanes
print(r.rpc("eth_estimateGas", [{"from": signer, "to": CA,
                                 "data": "0x" + r.sel("claimFree()")}]))
```

- Importing it runs module-level constants only, never `main()`: no state write, no webhook post, safe to call repeatedly.
- `view(ca, sig, *args)` routes args through `pad()`, which is string-only: an `int` argument raises `AttributeError: 'int' object has no attribute 'lower'`. Pass addresses as strings, and pre-pad every numeric arg as hex (`f'{n:064x}'`) — never `str(n)`, which the padder reads as hex digits and silently turns `10000` into 65,536.
- `view_int` tries each name in the list in order and returns the first that answers, so pass the whole family (`FREE_SHARES()`/`freeShares()`) rather than one guess; an absent constant is normal on sibling templates.
- `eligibility()` resolves in order `hasAgentId` → gate `identityOf` → `freeAvailable` → gate NFT `balanceOf`, and prints UNVERIFIED instead of guessing when all four are silent.
- The `eth_estimateGas` round trip is the whole verdict for a free lane: a pass settles the gate, the per-wallet quota and the open window at once, and broadcasts nothing. On this template `claimFree()` estimates around 135k gas and a successful `eth_call` returns bare `0x` — empty output is success, not a broken call.

## 16. Refundable-deposit emission farm (`mintFree` / `mintPool`)

Two contracts: an immutable capped ERC20 (no owner, no setters, a sell tax whose LP half goes to `0xdead`) and a minter that is the only writer of new supply. Nothing is bought and held: the "free lane" is a fully refundable deposit and the reward is freshly minted, so the audit reduces to (a) does the refund have a hole, and (b) what the emission is actually worth at the pool.

**Read the whole config before quoting any yield.** Constants that decide the answer: `PRICE_PER_SHARE`, `REFUND_DELAY` (86,400), `LOCK` (B-lane vesting, e.g. 14 days), `EPOCH` and `MAX_SHARES`, the halving bases (`BASE0`, `REL0`, `STAGE_BUDGET0`, `MULT_CAP`, `PACE_FACTOR_BPS`), `B_QUOTA`, `MAX_BATCH`, and the pause window. Views: `totalShares`, `fundedStage`, `reserveAvail`, `refundOwed`, `pausedUntil`, `pauser`. Two aggregate readers do most of the work: `quota(agent,shares)` returns refCount / aCap / aUsed / aLeft / bCap / bUsed / bLeft / stage / per-share reward / multiplier / reserveLeft / totalShares / sharesLeftInStage / sharesLeftTotal / open / paused, and `pending(agent)` returns (freeBnb, freeAgc, rewardVested, lpWithdrawable).

**Prove the refund is 1:1 backed.** The A lane only adds `msg.value` to `refundOwed` at mint and subtracts it at claim, so the minter's native balance must equal that counter exactly. Equal to the wei means no hole at all and the entire downside moves to the token price; a shortfall means early claimers are being paid with later deposits.

```python
print(int(rpc('eth_getBalance',[MINTER,'latest'])['result'],16)/1e18,   # 78.954
      view_int(MINTER,'refundOwed()')/1e18)                           # 78.954 -> backed
```

**An empty claim-event scan in the first 24h is structural.** `claimFree` skips any position younger than `REFUND_DELAY`, so a `ClaimFree` log scan returns zero rows while `MintFree` deposits are already arriving. Report the running clock (`refundOwed`, position counts) rather than "no claims yet", and never quote the sellable time as the trading-open time: it is `position.time + REFUND_DELAY`, per position. `pending(agent)` reads `(0, 0, 0, 0)` right after a fresh mint for the same reason and is not a failed deposit: prove it landed with `freePositionCount(agent)` (0 -> 1), `userInfo(agent)` (`firstDay` set, `aDay` = today, `aUsed` = shares) and `refundOwed()` growing, and confirm the quota is spent (`aLeft` back to 0) so the next mint has to wait for the UTC rollover. Simulating `claimFree([])` before maturity likewise returns bare `0x` (the scan hits `count == 0` and returns early), so a clean pre-maturity simulation is a no-op, not evidence the claim will work or fail: confirm the calldata against the deployed bytecode (`63<selector>` present) plus the project's own selector table, and let the maturity clock be the thing you verify.

**Price the whole emission against the pool.** Total future mint is the sum of the halved stage budgets (`STAGE_BUDGET0 >> s`) plus the halved base rewards (`BASE0 >> s * EPOCH`), sized to consume exactly `MAX_SUPPLY - deployMint`. Put it next to the pair's token reserve and quote the cohort ceiling as the pool's entire quote reserve:

```
emission 178.5B token vs pool 3.59B token  = 50x the pool's whole token reserve
pool quote side 125 WBNB (~$87K)          = the most all sellers combined can withdraw
```

That comparison, not the per-day dollar figure, is what makes the verdict: the earliest claimers can be paid at today's price and the marginal seller cannot.

**Three clocks, quoted in WIB.** (1) Lane open: `openTime() != 0`, already true on this shape. (2) Exit: mint tx timestamp + `REFUND_DELAY` per position, and the tokens are freely transferable the moment they land, so check `trading()` and that `openBlock` is long past (inside the open block a 99% snipe tax keeps almost everything). (3) Daily quota: `block.timestamp / 1 days`, rolling at 00:00 UTC = 07:00 WIB, so a wallet that mints either side of 07:00 WIB banks two quota windows in one WIB day.

**Team bags against the same pool.** Read the deploy-mint destinations (foundation escrow, marketing, ops) and quote their balances in USD beside the pool's quote side. Two untouched allocations can easily exceed the pool's entire exit; that is the sentence, plus the ops wallet's accumulated tax revenue as the team's running cut.

**Admin surface.** Expect no owner, no withdraw, no setters; the live path is usually a `pauser` that can only halt new mints (`pause()` / `unpause()`, fixed window with a cooldown) while claims and LP withdrawals keep working. Credit that distinction explicitly instead of calling it owner-controlled, and read `paused` from the aggregate reader before promising a mint today.

**"Isn't this free money?" is a two-part answer.** Part one, contract and theft risk: the deposit is refunded 1:1, the reward is minted on demand, there is no approve and no signature, so per position it genuinely is free apart from gas. Part two, value: the reward is denominated in the token whose only exit is that pool, so the real payout is whatever the pool pays at sale time and the emission is a multiple of the pool's depth. Give both, and note the headline daily figure decays (stage halving, the account-age quota ladder 5/5/4/3/1, a multiplier capped by the reserve), so it is a stage-0 number, not a rate.

### 16a. How long the lane is worth running

**Derive the pace from the minter's own mint events, then date the halving.** Reading `totalShares` twice **90 seconds apart yields a burst, not a rate**: that sample said 8,640 shares/hour on a live farm, while the same window measured from 2 hours of `MintFree` + `MintPool` logs gave 5,327 shares/hour, which turned a "base halves in 4 hours" call into "halves in 19 hours" and had to be retracted to the user. Scan the minter's mint events over 1-2 hours, sum the `shares` word (index 0 of the non-indexed data on both events), divide by the block-timestamp span, and only then compute `EPOCH / rate` for the halving ETA, quoting the base before and after it in WIB. A 90-second delta is an upper bound only, usable when the log window is unavailable, and must be labelled as such. A wallet's own quota stays flat while the value per share halves underneath it, and that is the part the user has not priced. Re-sample instead of reusing a stored rate, and call it a snapshot: the pace sags as quota-limited wallets saturate, which stretches the halving.

**Then model one wallet, or the report implies an income stream.** Multiply the account-age ladder (5, 5, 4, 3, then 1 share/day, quota days rolling at 00:00 UTC) by the stage base each mint is projected to land in:

```python
PACE, cur = 5327.0, 49903                                    # shares/hour FROM LOGS, totalShares now
base = lambda h: 280_000 >> int((cur + PACE * h) // 150_000)  # h = hours from now
# day 0 + day 1 land at 280k -> 2.8M token; day 2 at 70k -> 0.28M; day 3 onward rounds to nothing
```

On the live one that came to ~3.2M token for a whole wallet across the farm's life, ~88% of it inside the first 36 hours, with the entire 1.65M-share cap finishing in ~8 days at the observed rate. That converts "≈$6/day steady state" into "a 1-2 day window worth ~$70", which is what makes the decision actionable, and it answers "how long do I keep this running" without another session. It also gives the honest comparison against referral: one referred agent is +1 share/day for the life of the wallet, worth the per-share base at the time it is used, not the base today.

**Quote the project-wide first-claim date, not just the per-position clock.** No `ClaimFree` can exist before `openTime + REFUND_DELAY`, so a mint that opened hours ago has literally zero claims and no sell route for its first day. State that WIB date before discussing how to sell, and do not read the empty scan as a dead lane.

**Route the sell from the wallet that holds the identity.** The ID is soulbound, so the reward lands in the eligible wallet and the sell has to run there: approve the router for exactly the amount (never unlimited), then swap through the fee-on-transfer variant (`swapExactTokensForETHSupportingFeeOnTransferTokens`) with `minOut` from `getAmountsOut` minus the sell tax. Wallet-to-wallet transfers are untaxed on this template while anything touching the pair pays the tax, so moving the token to a cheaper-gas self-custody wallet before selling is legitimate, but it costs one extra tx plus a funded gas balance.

**Fund the minting wallet before anything else.** The deposit must be present in the minting wallet *at mint time*, so read that wallet's native balance first (`baw wallet balance --json`) and compare it against `shares * PRICE_PER_SHARE + gas`: one live wallet held 0.0056 BNB against a 0.02 BNB two-position deposit, and the whole plan stalled on a top-up. Top up the minting wallet, mint, and route gas to the sell wallet only after the refund lands, because the transfer that funds the sell lane is otherwise the transfer that breaks the mint.

**Bank the second quota window as a one-shot signing job that re-checks its own preconditions.** A `no_agent` script cannot mint, because the send needs the Developer-Mode preview/execute pair, so this is an agent job. Schedule it just after the 00:00 UTC rollover (07:10 WIB) with an absolute timestamp and confirm `next_run_at` carries the `+07:00` offset. The prompt has no chat context, so make it verify before signing: re-read `quota(agent,1)` word 3 (`aLeft`) and skip with a report while it is still 0, check the native balance covers `shares * PRICE_PER_SHARE + gas`, simulate the exact calldata with `eth_call` and stop on a revert, then preview/execute and verify the receipt plus the position count. Write the whole agreed plan into the prompt (e.g. 5, 5, 4, 3, 1 then stop); an unattended run with only one slot described will happily mint a quota the user never agreed to.

**Stop triggers worth naming before the first mint.** Any outflow from the foundation escrow or the marketing wallet is the dump signal for a project whose marketing is its own emission; a stage index past 3 leaves the base too small to beat gas; and a `MintPaused` revert is a user-side stop, not an outage, since claims keep working.

### 16b. "Kenapa turun terus, ini bundling bukan?" - pool-flow triage

A V2 pair has no order book, so answer this from reserves and flows and say so plainly before quoting numbers. Four probes settle it.

**1. Reserve delta plus a short swap window are the primary evidence.** `getReserves()` gives the price directly and it disagrees with the indexers: DexScreener's `liquidity.base` / `liquidity.quote` lagged the chain by 10-20% on a fast pair, and two USD figures built on it were quoted too high. Convert from `getReserves()` every time, and confirm the pair's own token and WBNB `balanceOf` matches the reserves so a donation is not skewing the price. Then take a 60-90 second window: read reserves before and after and pull that block range's `Swap` events to separate gross from net.

```
reserves 4,115,044,611/112.225 -> 4,148,158,884/111.355  (-1.57% in 75s)
swaps: sold 44.18M token in | bought 11.47M out | net +32.71M sold, net -0.881 BNB
```

That pair of lines is the whole explanation: sell flow 3.8x the buy flow and the pool paid out 0.88 BNB. Quote the swap count too, because 15 swaps moving the price 1.6% on a $79k pool is a depth statement, not a chart pattern.

**2. Attribute the sell flow before calling it a bundle.** Scan the token's `Transfer` logs over the window with `topics[2]` set to the pair (every sender into the pool), group by `topics[1]`, and compute distinct senders, top-1 and top-5 share, same-block sender counts, and repeated identical amounts (a copy-trading bot signature).

```
305 wallets sold 3.767B token in 1.13h | top1 17.0% | top5 33.3%
blocks with most distinct sellers: 12, 10, 10, 9   (a bundle is one block, one sender, once)
repeated identical sell amounts: 6,823 x12, 6,816 x10
```

Hundreds of distinct senders with a modest top-1 slice plus a high-frequency bot winning the block race is distribution, not a bundle. Quote the numbers and then say "no single entity" out loud, because the real question is whether someone is dumping on them.

**3. Two entries in that sender list are not sells.** The token contract itself appears whenever its tax backlog swaps back (`SwapBack` events, roughly 295M token/hour on a live one: a standing programmatic seller the report must name rather than attribute to a wallet), and the minter appears whenever it seeds B-lane LP (`agc.transfer(pair, ...)` followed by `pair.mint()`). Separating those from genuine exits is the difference between "the protocol taxes and sells continuously" and "someone is dumping 300M an hour".

**4. Check the team wallets for the actual dump signal.** `eth_getLogs` on the token with `topics[1]` set to each deploy-mint destination over the last few thousand blocks, and report the outflow with its USD value against the pool's quote side. On the audited farm the foundation escrow was flat (zero outflow in 3h), marketing had sold 31.8M (~$612), and the ops wallet had sold nothing while banking 12.45 BNB of tax: that sentence ends the bundling fear, and it is also the trigger to watch afterwards.

**Frame the move against depth, not sentiment.** About $9k of net selling over an hour took that pool down 21% because its quote side was 112 BNB ($79k). That ratio explains "turun terus" better than any narrative, and it is the same number that makes a refundable lane's payout shrink minute by minute while the user waits out the 24-hour claim clock.

### 16c. "Real demand atau bot?" - buy-side verification after a bounce

The reciprocal of 16b. A green candle is not demand until you can name who bought, whether they still hold, and how much new money entered the pool. Four probes.

**1. Split the window's flow into buyers and sellers from the pair's own transfers, and use those scans for identities rather than for volume.** `topics: [Transfer, pad(pair)]` is every token leaving the pool (buyer = `topics[2]`); `topics: [Transfer, null, pad(pair)]` is every token entering it (seller = `topics[1]`). Those two answer *who*, including the held-balance check in step 4; the *how much* and the whole native side come from the pair's `Swap` events in step 2, because a token transfer involving the pair is not always a trade (LP seeding and pool withdrawals move tokens through it too). Group by address over a 30-40 minute window and quote unique wallets, top buyers with their tx counts, and the net out of the pool:

```
BELI : 78 wallet unik, 2,176,781,526 token   (top1 13.2%, top3 31.3%)
JUAL : 212 wallet unik,   938,854,786 token   (top1 15.9%)
net  : +1,237,926,740 token keluar dari pool
```

Fewer buyers taking far more size than the crowd selling is accumulation; the reverse (hundreds of small sellers, one big seller) is distribution. Quote both counts, because "78 vs 212" and "net +1.24B" say different things alone.

**2. Account the native side from the pair's own `Swap` events, never by summing quote-token transfers into the pair.** Summing WBNB `Transfer` logs with `topics: [Transfer, null, pad(pair)]` over-counts badly: the router, the minter seeding LP and any other contract also push the quote token into the pair. That scan returned **29.437 BNB from 217 tx** where the pair's own swaps accounted for **20.760 BNB of buys** in the same window, and quoting the larger figure as "new money" had to be retracted to the user. The `Swap` topic (`0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822`) carries `amount0In/1In/0Out/1Out`, so a single scan gives both sides and the net:

```
Swap events, 37.5 menit, 1758 swap, token0 = token, token1 = WBNB
BELI : 94 wallet, 20.760 BNB masuk, 2.389B token keluar  (85 dari 94 belanja < 0.5 BNB)
JUAL : 66 wallet, 27.452 BNB keluar, 3.131B token masuk
NET  : BNB -6.692 (keluar dari pool) | token +0.741B (masuk pool) -> window-nya sudah net jual
```

Quote it as `(gross buy native in, gross sell native out, net)` and say which side the net sits on, because the two methods disagree in sign: the transfer-based scan read as "29 BNB of new money in" while the swap-based one showed the same period had already flipped to net selling. A short sub-window makes the flip visible (`1000 blok`: 17 buyers 2.659 BNB vs 28 sellers 4.633 BNB). Check the token ordering before assigning words (`token0 = min(address)`; the token here sorts below WBNB), and remember a 30-40 minute window over a choppy pair can read one way while the previous one read the opposite: always date the window and say it is a snapshot.

**3. Discount the routers and the round-trippers before crediting the rest.** Two patterns inflate "demand" and both are visible in the same two scans:

- **A pass-through shows in-total == out-total exactly and a 0 token balance.** One market-maker address logged 784,485,867 in over 486 txs and 784,485,867 out over 916 txs with a balance of 0: its volume is directional noise, and quoting it as the top buyer or top seller inverts the story. The same address can lead the sell list one hour and the buy list the next; check `in == out` before rewriting the narrative.
- **Flip volume is the intersection of the two address sets.** Sum `min(buy, sell)` per wallet that both bought and sold inside the window and quote it as a share of gross buys (15 wallets round-tripping 508M against 2.18B bought = 23% of the money is not new).

**4. Prove the leading buyers still hold.** For the top two or three unknown addresses read `balanceOf`, `getCode` size, native balance, and their inbound/outbound counts over a longer window (10-20k blocks). Accumulation is held balance plus zero outbound; new money is a fresh EOA with a handful of inbound txs from a handful of blocks; another router is in ≈ out with a drained balance. On the audited pair two EOAs had each taken 242M and 182M out of the pool in 2-4 txs and still held all of it with no outflows: that, plus 29 BNB of native inflow, is what made the bounce real, while the top-of-book "buyer" was the pass-through from step 3.

Report it as a mix with the discount stated, not as a verdict on price: "net 1.24B tokens absorbed, 29 BNB of new money, but a quarter of the buy volume is round-tripped and the biggest address is a router" is the honest sentence, and add that the same market-maker can flip back to selling at any point.

## 17. Agent-gated fair mint on Ethereum mainnet (gate on BSC)

Shape: token and mint on Ethereum mainnet (`chainId 1`), eligibility gate a soulbound SPACE ID `.ai` Agent ID registry on BSC, and an agent-facing site that publishes its own API and operating docs (`/skill.md`, `/llms.txt`, `/api/*`). The site co-operates more than usual, so the audit is mostly economics plus one cross-chain lane check.

**Trust discovery: `/api/contract` first, then a chainId-1 Sourcify match.** The site names every address, but only accept one that is verified:

```bash
curl -s https://<site>/api/contract      # {"chainId":1,"deployed":true,"token":..,"mint":..,"pair":..,"registry":..,"mintStart":..}
curl -s 'https://sourcify.dev/server/v2/contract/1/<mint>?fields=sources,abi'   # creationMatch/runtimeMatch: exact_match
```

Read `/skill.md` and `/llms.txt` for intent only (gate rule, ladder, split, refund window, tax) and treat every number in them as a claim to re-read on chain.

**The gate is a real registry, and the label is hashed without the suffix.** The BSC address named as the registry answered `name() = "SPACE ID Agent ID"`, `symbol() = "AI"`, and `ownerOf(uint256(keccak256(label)))` returned the wallet, with `handleOf(addr)` giving the handle string. `label` is the handle minus `.ai`, hashed as raw ascii: `keccak("pierre")` resolved, `keccak("pierre.ai")` did not. Confirm it on chain rather than trusting the site's sentence, then report the matching wallet address and its `balanceOf` of 1.

**Eligibility and capability are a cross-chain split.** The eligible wallet is the BSC identity holder; the mint runs on mainnet, so read `eth_getBalance` on chainId 1 for that same address. `baw wallet address --json` lists `{"binanceChainId":"1","chainName":"Ethereum"}` beside `"56"` and all EVM chains share one address, so mainnet is a usable lane, but a BSC balance read says nothing about it and `--binanceChainId 1` is the flag that routes there. Mainnet gas is a live variable: at 0.05 gwei a ~120k-gas `mintFree` is about 1 cent, so quote `eth_gasPrice` at the time instead of calling the free lane expensive on principle.

**The contract does not enforce the Agent ID; their backend does.** The gate is an EIP-712 voucher recovered against `gateSigner()`, an EOA, with the voucher binding `(minter, agentId, wl, shares, nonce, deadline)` to `msg.sender`. So the honest sentence is "eligibility is enforced by their signer checking the registry", never "the contract checks your Agent ID". What the contract does enforce is the caps themselves (`WL_PER_AGENT`, `PUBLIC_PER_AGENT`, `WL_FREE_CAP`, `PUBLIC_FREE_CAP`, `MAX_PAID_PER_WALLET`, `MAX_PER_TX`), which is what makes a forged-web-request story uninteresting: a voucher for more shares than the cap still reverts `Quota()`/`SoldOut()`.

**Free shares are a separate $0 track: no escrow, no LP, locked until the paid lane seeds the pool.** `mintFree(agentId, wl, shares, nonce, deadline, sig)` mints `USER_SHARE` per share straight to the agent, and the token reverts any transfer until `enableTrading()` runs at the pool-open threshold. So the free allocation's value is conditional on the paid lane reaching `OPEN_AT`, not on eligibility:

```
open price   = escrow * POOL_BPS / OPEN_TOKENS      # 80% of 10,000 x $1 over 10,000 x 6,820 tokens
             = $8,000 / 68,200,000 = $0.0001173
free claim   = shares x USER_SHARE x open price     # 5 x 11,000 x 0.0001173 = $6.45 gross
sell into it = lp_q * x / (lp_t + x) minus SELL_TAX_BPS   # ~$6.29 net for a 5-share claim
```

Quote the pool's whole quote side as the ceiling every seller combined can withdraw, and state that the free tokens are illiquid until then: if the paid lane never fills, the free claimant gets nothing while the paid minter refunds 100% after `REFUND_WINDOW` from the first mint.

**Whitelist-full is the normal state of an engagement farm.** `/api/stats` returning `wl_registered == wl_cap` closes the WL track, leaving the public free track plus social tasks (follow / comment / repost / post), an X binding and invites under manual review. Read `/api/alloc?handle=<handle>` for status ("Not registered." is a read) instead of posting to `/api/connect`, `/api/bind-x` or `/api/task`: those are submissions, and a probe must not create one.

**Admin surface: read `renounced()` live, not the docs.** Read `paused()`, `seeded()`, `renounced()` and the token's `blocksDisabled()`, plus `setPaused` / `setPoolBlocked` in the source. Docs said renounce was a separate manual step; on the audited instance it had already been called (`renounced() = 1`, `paused() = 0`, `blocksDisabled() = 1`), so no pause or block was possible. Before renounce the treasury can halt minting and `setPoolBlocked` can make transfers to ANY address revert (the official pair is exempt), a soft-censorship power wider than the "rogue pool" wording; credit the real bound (it cannot touch escrow, pool, LP or anyone's tokens) and report whichever state the chain shows. The treasury here is an EOA and `gateSigner` is a hot EOA that has never sent a tx: name both as single-key points.

**Post-open mint economics (read `_mintShares` / `_curveShare`, do not trust the "ladder" wording).** Once `totalMinted >= OPEN_AT` the pool is open and `refund()` reverts `RefundClosed` for good. A paid mint then MINTS fresh tokens to the buyer at `pay * poolTokens / (poolQuote * 0.99)` and mints matching tokens into the pool for the 80% LP share, so the USD ladder only sets how much ETH goes in; the tokens received are worth about `pay / 0.99` at the current pool price whatever the tier. Tokens per share is therefore `quoteEth(1) / (poolWETH / poolTokens) / 0.99` and moves with every swap (a 31% pool move in minutes took 7,100 down to 5,500 per share); recompute it from live reserves each time it is quoted. Against Uniswap the mint saves the 0.3% fee, the 1% buy tax and slippage, nothing more. Pre-open minters got `USER_SHARE` (11,000) tokens per share against only `POOL_SHARE` (6,820) seeded in the pool per share, so the opening mark-to-market is far above what the seeded pool can pay.

**The floor line is a mark, not a redemption.** `floorValue = totalPaid * FLOOR_LINE / LINE_DENOM` (about 1.8x total paid) is compared with `circulating * pool price`; when below, each paid mint burns pool tokens (at most +0.8% price per tx) toward it. It does nothing without new mints and the number exceeds the pool's actual WETH, so quote the cohort exit instead: `ETH out = R_weth * x / (R_tok + x)` with `x = circulating * (1 - sell tax) * (1 - 0.003)`, divided by total paid (about 56% at the audited moment).

**Gate-signer closed lane.** `/api/alloc`, `/api/connect` and `/api/voucher` all answering `Not registered` / `Whitelist registration has closed` means the free lane is closed to that handle regardless of the docs' "any agent, no whitelist needed" line, because the signer only signs for registered handles. Do not retry, fabricate a registration or hit `/api/connect` repeatedly; the only unlock is registration through the project's own task flow, which only the user can do.

**Farming signature in `Minted` logs.** Group `Minted(address indexed minter, uint256 indexed agentId, uint256 firstSerial, uint256 shares, uint256 paid)` by wallet (minter in `topics[1]`, shares at data word 1). Many wallets stacked at exactly the per-tx or per-wallet cap (hundreds at 10, hundreds at 15, a cluster at 5) is scripted agent wallets, not retail; say it cannot prove one operator because each wallet needs its own Agent ID. Reconcile `sum(shares)` to `totalMinted` and print failed chunks (a ~2% gap came from 5 failed 2,000-block chunks on publicnode).

**Funding mainnet gas for a BSC-identity wallet.** `baw market-order swap` swaps within one chain only, so BNB on BSC cannot become ETH on chainId 1 through it. Options are the user sending ETH from an exchange (the path that worked) or a bridge quote: `GET https://li.quest/v1/quote?fromChain=56&toChain=1&fromToken=0x0000000000000000000000000000000000000000&toToken=0x0000000000000000000000000000000000000000&fromAmount=<wei>&fromAddress=<wallet>` returns `toAmount`, `feeCosts` and a `transactionRequest`; a $1.5 route netted about $1.12 (about 26% lost, mostly the bridge's flat fee) and still needs a Developer-Mode `contract-call` plus likely App confirmation, so present it as a priced option and wait. Size the gas before suggesting a top-up: a `mintFree`/`mint` with signature recovery is roughly 100k-150k gas, so at 4.5 gwei it costs about $1-1.5, not the cents a plain transfer costs; run `eth_estimateGas` from the signer when the voucher exists, and say the figure is an estimate until then.

**Settling "the chain contradicts the verified source".** With `exact_match` in hand and a read that disagrees, the probe is the prime suspect: locate the dispatch entry and disassemble the body instead of arguing from the API response.

```python
code = rpc('eth_getCode', [C, 'latest'])['result'][2:]
i = code.find('63' + sel('priceCents(uint256)'))   # 63 <sel> 14 61 <dest> 57  -> PUSH4, EQ, PUSH2, JUMPI
dest = int(code[i + 14:i + 18], 16)                # 0x2790 here
```

Disassembling from `dest` printed `PUSH32 10000 / GT / ISZERO / JUMPI` to a return-100 path, then `(n - 1) / 10000`, `* 16` (SHL 4) and `+ 100`, exactly the source's flat-then-step ladder, which also settled the economics: paid shares cost a flat $1.00 up to 10,000 shares. The 9x-steeper ladder that had been reported came from passing `10000` to a string padder as `"10000"` (0x10000 = 65,536), and the tell was a self-inconsistent family of reads: `priceUsd(n)` flat while `costUsd(k) - costUsd(k-1)` jumped. Two independent RPCs agreed on those wrong numbers, so a provider cross-check does not substitute for encoding the argument correctly.

## 18. Refund branch: proving it pays when the signing lane is blocked

Once the deadline passes without a sellout, `phase() == 4` and every payer can pull `refundBps` of what they paid. Three things have to be settled before telling the user anything about their money.

**1. The payout is per address and manual, with no deadline.** `refund()` reads `paidShares[msg.sender]`, so it can only be called by the wallet that minted: another address reverts `InvalidAmount` with zero shares. It also burns back the tokens it earned (`shares * tokensPerShare`) and unwraps the quote token to native. Nothing expires the branch while `launched` stays false, so "later" is always available and the user should be told that rather than rushed.

```python
print(call(C, '0x' + sel('phase()')))            # 4 = Refunds
print(call(C, '0x' + sel('refundedShares()')))   # grows as others withdraw
print(rpc('eth_estimateGas', [{'from': wallet, 'to': C,
                               'data': '0x' + sel('refund()')}]))   # ~93k, no value
```

**2. Prove the contract side pays, with a read that no frontend or risk engine sits behind.** A direct `eth_call` of the refund calldata from the minting wallet either returns `0x` (no revert, the path is open) or reverts: that single read is what separates "the contract will not pay me" from "my signer will not send it".

```python
rpc('eth_call', [{'from': wallet, 'to': C, 'data': '0x' + sel('refund()')}, 'latest'])
```

Then reconcile the books: the contract's quote-token balance must equal `(sold - refundedShares) * price` to the wei. On the audited shape, 1760 sold minus 121 already refunded against a 0.002 price matched the held 3.278 WBNB exactly, which is the solvency statement. Finally scan the `Refunded` topic for payers who already got paid at the same amount, which is the strongest available answer to "is this a scam":

```python
h = topic('Refunded(address,uint256,uint256)')   # payer is INDEXED -> topics[1], data = shares, amount
logs = get_logs(C, h, latest - 5000, latest)     # 1200-1500 block chunks on 48.club
for l in logs:
    payer  = '0x' + l['topics'][1][-40:]
    shares = int(l['data'][2:][:64], 16)
    amount = int(l['data'][2:][64:128], 16) / 1e18
```

Sixteen payers withdrawing 0.208 BNB in the first ten minutes of the window, one of them with exactly one share taking 0.0016 BNB, is the sentence that ends the scam question when the user's own lane is blocked.

**3. Isolate the blocker with a control call.** Compare error codes across calls: `351803 ... risk is too high and has been rejected: blocked` on the destination contract, versus a preview of a trivial `balanceOf` on an unrelated verified contract (WBNB) returning a `requestId`. A healthy control plus a blocked destination means the wallet, session and Dev Mode are fine and Binance's risk engine has flagged that contract; repeating the preview cannot clear it. Decode `351805 ... simulation failed: execution reverted` as the contract rejecting the call for a normal reason (closed phase), which is a different problem with a different fix.

**4. Watch for the unblock with a deterministic probe behind `monitor`.** Ship the probe to `~/.hermes/scripts/` and have it print one stable line, e.g. `STATE phase=4 sold=1760 BLOCKED:351803`, then create the job with `monitor: <bare filename>` and a 6-hour schedule: unchanged output suppresses the agent run entirely, and the tick that first reads `READY` delivers the message that asks for the go-ahead. Keep it report-only, since the tick cannot ask a question and a signature the user has not seen should not be sent unattended. The probe only previews, so it broadcasts nothing while polling.

Five commands to keep in the prompt when this runs on a schedule: `phase()`, `sold()`, `launched()`, `paidShares(wallet)` and `eth_getBalance(wallet)`; plus `pair().getReserves()` for the launched case, where refunds are gone and the pool depth is the only thing left to report.

**5. There is no App screen for a hand-built contract call; the App lever is `abnormalTxnHandling`, and flipping it is the fix.** Developer Mode contract calls are CLI-only: the Binance App can enable Developer Mode and can confirm a pending high-risk transaction, but it cannot compose calldata, so "do it manually in the App" is not a route to a refund the CLI refused. The real control is `wallet settings --json` → `abnormalTxnHandling`: `AutoReject` (the default, and the reason a flagged transaction is blocked outright with `351803` before anything is simulated) versus `NeedConfirmation`, which pushes it to the App as a double-confirm instead. Verified end to end on this shape: setting `NeedConfirmation` in Agentic Wallet management page → settings icon, re-running the same preview, got a `requestId` with `requireConfirmation: true` and a clean simulation (`balanceChanges` one native credit, one ERC20 debit, empty `allowances`/`authorityChanges`), and `execute` returned `PENDING_CONFIRMATION` with `"High-risk transaction, please confirm in the App"`. Say the setting name and the path out loud, because the user can only change it there, then re-preview instead of re-diagnosing. Retrying `351803` without that change never clears it, and the block has also been seen to clear on its own hours later with byte-identical calldata, so re-probe as well as advise.

**6. After the user confirms in the App, the hash and the outcome both come from reads, not from the CLI.** `PENDING_CONFIRMATION` carries no `txHash`, so never report the order id as a transaction and never wait for the CLI to produce a hash. Pull the settled tx from the wallet's own history and prove the money moved from state:

```bash
baw wallet tx-history --binanceChainId 56 --json   # txType contract_call, status confirmed,
                                                   # instructions.send/receive, networkFee.feeValue
```

```python
userInfo(wallet)        # paidShares back to 0, token balance back to 0 -> the refund landed
refundedShares()        # grew by this share count
eth_getBalance(wallet)  # + refundBps * paid, minus one receipt's gas
```

Spend the CLI-history call before hunting logs: BSC runs about 0.45 s per block, so a `latest - 3000` window is roughly 22 minutes and a refund confirmed eight hours earlier sits far outside it, which reads as "no such event" and sends you chasing a failed transaction that in fact succeeded. Quote hash, block, `gasUsed * effectiveGasPrice` and the balance delta together, and close the position arithmetic as native out at mint minus native back at refund minus both fees, which on the audited case was about 20% of entry plus about a cent of gas.

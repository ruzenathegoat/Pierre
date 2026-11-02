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

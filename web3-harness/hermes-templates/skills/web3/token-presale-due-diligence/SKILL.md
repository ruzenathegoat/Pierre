---
name: token-presale-due-diligence
description: Use when a mint, presale or NFT collection must be audited.
version: 0.2.0
author: hermes-curator
license: MIT
metadata:
  hermes:
    tags: [web3, bsc, due-diligence, scam-triage, mint, presale]
    related_skills: [pierre-web3, evm-wallet-verification]
---

# Token / Presale Due Diligence

Answers "is this mint or presale worth paying for?" with numbers pulled from the chain and from the project's own backend, not from its whitepaper. The deliverable is a verdict the user can act on: skip, free-claim only, or proceed, each backed by a hard figure.

## When to Use

- User drops a mint site, launch page, token address or a "dapet $X kalo ikut" campaign and asks to check it before spending.
- Anything claiming a reward, airdrop, bounty or prize pool in exchange for holding, posting or submitting screenshots.
- Before a paid mint, a "1 USDT per copy" style sale, or an approve-to-a-brand-new-contract flow.
- User drops a marketplace link (Element, OpenSea, Magic Eden) to a young NFT collection and asks "worth it?". Buy-side collection audits follow the same verdict shape but price the exit from the project's own market contract: see `references/nft-collection-audit.md`.
- Also when the site looks clean: the user still needs the two numbers that decide whether the exit is real (raised vs LP depth).
- The user replies "ambil yang free mint aja" / "just do the free claim" after the verdict. The audit is finished; what remains is execution prep, which has its own gating steps below.

## Procedure

1. **Render the page, do not read the description.** Open the URL in the browser, pull `document.body.innerText`, and grep the rendered HTML for `/api/` paths, `fetch(` calls, contract addresses (`0x[a-fA-F0-9]{40}`) and script domains. The site's own counters (supply, claims, approved users) are marketing until an RPC call or an API response confirms them.
2. **Get the verified source** from Sourcify v2 and read the mint contract end to end. Look for: price and caps, tokens per share, the payment split, every hardcoded destination (treasury, LP, dead address), and the presence of any owner/admin/withdraw/upgrade path. If no verified source exists at all, say so, then recover the ABI from the site's own inline script before calling the contract unauditable: `grep -n '_ABI = \[' page.html` returns ethers string-array ABIs (`function publicMinted() view returns (uint256)`), which give every view function, event and calldata shape the audit needs.
3. **Read live state over public RPC**: shares minted, paid shares, free mints, deadline, payment-token balance of the mint contract, token `totalSupply`. Reconcile against the site's counter; a mismatch of even a few units means the page is not the ledger.
4. **Verify the gate claim.** If minting requires holding some NFT ("only Agent ID holders"), resolve that contract and call `name()`, `symbol()`, `balanceOf`. A real third-party gate is common and proves nothing about value; a gate the same wallet deployed a day earlier is a red flag. Resolve the gate address from the mint contract itself (`identity()`, `gate()`, `registry()`), never from the site's prompt JSON or docs: those name a raw registry, while the contract usually calls a read-only wrapper that is a different address, and only the wrapper's logic tells you what actually qualifies.
5. **Run the exit math before repeating any "you get N tokens" line.** Model the pool with the constant-product formula and the fee, seeded only with the LP portion actually collected, then iterate over the number of free claimers. Report how many holders can exit and what the 100th and 500th seller receives. The first seller always looks fine; that is the design.
6. **Check whether the reward pool exists.** Curl the campaign stats endpoint and compare `approved` / `pending` against `paid`. Then read the treasury: balance and `eth_getLogs` on the payment token's `Transfer` topic with the treasury as `from` over recent blocks. Zero outflows plus `paid: 0` while thousands are queued is proof the prize is unfunded.
7. **Confirm the approval scope** from the site's own instructions (exact amount vs unlimited) before saying it is safe to sign, and check whether any step asks for a seed phrase or private key.

8. **Before any signature, prove eligibility and price the gas.** Read `hasAgentId`/`freeAvailable`/`mintedBy` for the *signing* address, estimate gas from that same address, and check the signer lane is actually usable. See "Executing a Free Claim" below.

9. **For an NFT collection, price the exit from the project's own market contract, not the marketplace page.** Resolve the market address from the contract or the site's brief, then enumerate the orderbook yourself: `listedCount()` then `listedIdAt(i)` for every index and `getListing(id)` for seller plus price (the helper names vary; read the ABI you recovered in step 2). Compute the floor, the median, how many asks sit exactly at `MIN_PRICE()`, and the unique-seller count. Then scan the market's `Sale` logs over its whole life for real volume. Zero sales ever is the decisive number, no matter how many listings exist; hundreds of distinct sellers all stacked at the minimum price against a handful of lifetime sales is the same verdict in another shape.

**Start here, it is already scripted.** `scripts/mint_screener.py` runs steps 1-6 end to end and prints the report shape this skill asks for: `audit --url <mint page>` or `audit --ca <token>` (Sourcify flags, live ledger, quote price in USD, LP depth and burn, balance split, per-wallet mint histogram, swap volume with bot concentration, tax-adjusted exit curve), and `discover --blocks N` which finds live launches with no site at all by watching the `Started` / `Minted` / `FreeClaimed` / `Launched` event signatures. Read the output, then verify the one or two numbers the verdict hinges on by hand; do not re-derive the whole thing with ad hoc probes.

## Standing Radar (no LLM)

`~/.hermes/scripts/agent_mint_radar.py` runs as a `no_agent: true` cron job (`every 2m`) and costs no model tokens: the scheduler executes the script, delivers stdout verbatim, and an empty stdout sends nothing. It discovers candidates from chain events only (`FreeClaimed(address,bytes32)`, `Minted(address,bytes32,uint256,bytes32)` over the last 2000 blocks), then alerts on three conditions, tuned for claiming the FREE lane rather than reporting its death:

- mint opened inside 90 minutes and the free pool still has >= 25% left (`Mint baru buka, free masih ada`) — the actionable one, carries ETA to empty from the observed claim rate
- free pool dropped under 25% left (`Free pool tinggal X%`)
- paid shares grew >= +1000 inside the last 60 minutes (`Paid jalan cepat`); a first sighting backfills the hour from that contract's own `Minted` logs

Do not alert on "free pool drained": on the FAGENT mint the free pool was 50% gone at 2.34h and 100% gone at 2.85h after `startedAt()`, so a 90%-claimed trigger leaves about ten minutes to act. Alert on the opening instead, and every alert prints a per-wallet eligibility line (`hasAgentId` / gate `identityOf` / gate NFT) because `claimFree()` reverts `NoIdentity` for a wallet without one — an alert nobody can act on is noise.

State (`~/.hermes/cache/agent_mint_radar_state.json`) carries per-contract paid and free history plus a dedupe map: the fresh-mint alert fires once per contract per 6h, the low-free heads-up once per 6h, the paid-velocity alert at most once per 3h. Contracts that reach `launched()` are marked done and dropped; a contract whose free pool hits zero stays tracked for the paid watch only. `RADAR_FRESH_S` / `RADAR_LOW_LEFT` / `RADAR_PAID_DELTA` override the thresholds so a test can fire the alert path without waiting for a real mint.

## Before Promising a Free Lane

Two checks decide whether a free-mint watch is worth building at all, and both come before the cron job.

1. **Measure the drain, then choose the cadence.** Read the mint's own `FreeClaimed` logs, take the first and last claim blocks plus their timestamps, and quote the 50% and 100% times. The free cap is far smaller than the paid cap and usually drains first, so the free lane, not the sellout, is the binding reaction window: on one audited mint it was 50% gone at 2.34h and empty at 2.85h while paid took 8.14h. Answer "akan terkejar?" with that arithmetic and the poll interval it justifies, not with reassurance.
2. **Prove the user's own wallet passes the gate before shipping the alert stream.** Call the contract's `identity()` wrapper per wallet and report pass/fail per address. Several sibling projects each deploy their own wrapper but resolve the same handle registry, so a zero from three different gates is evidence about the wallet, not a broken probe. If no wallet passes, say the free lane is closed for them and offer the two real routes (acquire the identity, or watch ungated free mints) instead of delivering alerts that always read not-eligible. Also read the native balance: an eligible wallet with 0 gas cannot execute either.

Cron minimum interval is one minute; anything faster needs a resident loop, not a job. Never wire a radar into an agent job: at 2 minutes that is 720 LLM sessions a day for output a script can format.

Probe commands, selector computation, return decoding, the exit-math snippet and the eligibility/gas recipes live in `references/mint-due-diligence.md` (section 13 covers the agent-ID gated fair mint: gate wrapper versus registry, per-ID quota, per-share exit curve, refund branch; section 12 covers an unverified collection plus its own market: ABI from the inline script, orderbook enumeration, lifetime `Sale` log scan). Section 14 carries the no-site discovery recipe (event-signature watch, what each log pattern means) and the log-scan reconciliation rule that stops a short scan reading as a thin mint. The collection-audit variant (self-documented contracts, project market vs marketplace indexer, 404-branding check, PoW free-mint ladders) lives in `references/nft-collection-audit.md`.

## Executing a Free Claim

The verdict "free claim only" is the start of execution, not permission to sign. Run these in order; each one can end the task.

1. **Find the lane that holds both the gate asset and gas.** Enumerate the signing lanes first (`baw wallet address --json` for the agentic wallet, the derived address of `WALLET_PRIVATE_KEY` for self-custody), then call `balanceOf` on the gate contract per address and read native balance per address. The eligible address and the funded address are frequently different wallets; the claim must be sent from the address that holds the gate NFT.
2. **Prove the claim on-chain, do not infer it from the page.** `hasAgentId(addr)` and `freeAvailable(addr)` must both be true, `mintedBy(addr)` zero, and `mintingOpen()` true, and the contract-wide free pool must still have room (`freeClaimed() < freeShares()`). A per-wallet `userInfo(addr).freeClaimed == false` says nothing when the free cap is exhausted: every `claimFree()` then reverts `QuotaExceeded`, so the audit's only live paths are paid shares or skip. Build the free calldata from the contract's own ABI, never from the site's prompt: some fair mints price the free lane through `mint(0)` (zero quantity, zero value), while others expose a separate `claimFree()` and revert a zero-quantity mint with `InvalidAmount`. Quote the exact bytes you intend to send.
3. **Price the gas from the signing address.** `eth_estimateGas` with `from` = signer, the mint target and the calldata; multiply by `eth_gasPrice`; present it in native units and the user's fiat. Ignore any gas limit the site suggests — that is a ceiling, not a quote.
4. **Gate on signer capability before previewing.** For the Binance agentic wallet, run `baw wallet settings --json` and require `devMode.enabled: true` before any `contract-call preview`. If it is false, hand the user the in-app steps (Agentic Wallet management page → Settings → Developer Mode → read the risk warning → approve the App signature), say the words "tell me when it is on", and end the turn. Do not reroute the claim to a self-custody key that lacks the gate NFT or gas — that trades a two-minute wait for a guaranteed revert.
5. **Restate the lock-up before executing.** Most fair mints make tokens non-transferable until the pool opens and carry a deadline. State the unlock date and that the claim is illiquid until then, so the user cannot mistake a free claim for a $1 balance.

Only then preview, show parsed tx plus risk output, and execute on explicit confirmation. A paid share runs the same gate with the payment in `--value`; the calldata, the `balanceChanges` checks and the fee-versus-estimate caveat are in `references/mint-due-diligence.md` section 13.

## After the Claim: Verify, Then Watch

A broadcast is not a confirmed receipt, and a preview is not a broadcast. Close the loop in this order.

1. **Say which state you are in.** `contract-call preview` only simulates and returns a `requestId`; no transaction exists and there is no hash to report. Once `contract-call execute` returns `status: BROADCASTED` with a `txHash`, then verify and quote the hash.
2. **Verify from the chain, not from the CLI status.** `eth_getTransactionReceipt` for `status: 0x1`, `gasUsed * effectiveGasPrice` for the real fee, then re-read the token `balanceOf` and the mint counter (`sharesMinted`) to prove the delta landed. Report hash, block, fee, and new balance together.
3. **Explain an "empty" history before troubleshooting it.** Devices' Orders pages list trading orders only (market, limit, prediction). A Developer-Mode `contract-call` never appears there; it shows in the transaction/activity history as `txType: contract_call`. Say that instead of hunting a phantom bug.
4. **Schedule the unlock watch only after the claim confirms.** One-shot job a minute after the pool deadline, then a short recurring job (every 15 minutes for a couple of hours) that reads `poolOpen()`, pair reserves, spot price, LP depth and the modelled sell-out. Default to report-only; auto-sell only if the user states an explicit price or value threshold. Once the deadline passes, opening is permissionless, so the pool will open without you calling `openPool()` yourself.

**Check the wallet session outlives the event before promising an unattended send.** `baw wallet settings --json` reports `sessionExpireTime`, `inactiveSignOutTime`, `signInMaxTime` and `maxSigninDuration` (48h); `baw auth signin` only prints a QR that the user scans in the Wallet App, so it cannot be renewed by the agent. If the session expires before the deadline, the job must be report-only and the user must be told to scan once before the window (one sign-in covers up to 48h). Say that up front, not when the job fails.
5. **Do not imply waiting raises the price.** When the LP is seeded at `LP_TOKENS_PER_PAID` per paid share against the LP split, the open price is pinned to the mint price by construction. Say plainly that a higher price requires buyers, not time, so a "wait for a good price" plan is really a "hope a buyer shows up" plan.

Commands for receipt verification and the `tx-history` shape are in `references/mint-due-diligence.md`.

## Verdict Rules

- **Separate theft risk from economic risk.** "No drainer, no seed-phrase request, approve is capped" clears only the theft question. It says nothing about whether the token is worth buying, so never let it end the report.
- **Quote two figures every time:** what was actually raised in the payment token, and how much of it reaches the LP. A project that raised 300 USDT and seeds a 210 USDT pool cannot pay out a 10,000 USDT campaign.
- **Reward bigger than the user's realisable exit is a shill task, not a prize.** When the bounty exceeds what a holder can actually withdraw, name that explicitly.
- **A reward that requires public posting plus wallet address plus screenshots is an engagement farm.** Say it plainly, and note that manual review with no on-chain payouts means nothing will be paid.
- **Credit what is genuinely clean.** Verified source, no admin, bounded approve, funded pool, real payouts: say so without hedging. A mixed verdict is the normal result, not a cowardly one.
- **A sold-out mint is a distribution win, not an exit.** Confirm the sellout from the counters (`sold() == MAX_SHARES`, `freeClaimed()`, `launched`), then say what it is worth: raise versus LP depth, and the full-cohort exit as a share of what holders paid. A mint that filled in hours with a thousand-plus payers can still leave the cohort recovering roughly half of entry, and that sentence is the one the user needs.
- **Price the payment token before quoting any fiat figure.** When the raise is denominated in the project's own token, every USD number rides that token's own pool: read its stable pair, and quote its FDV-versus-liquidity ratio, because a $60M FDV on a $0.5M pool means the dollars are not withdrawable at that price. Never present a fiat total while the quote token is unpriced.
- **Never endorse the token price.** The output is a risk verdict plus a recommended action, not a price target.

## Pitfalls

- **The site's counters can be stale or hardcoded.** Always recompute supply from `totalSupply` and the minted/paid counters; the leaderboard and "X/Y minted" text can drift by tens of units or be static markup.
- **A node that serves a block can still answer `[]` for it.** `bsc-rpc.publicnode.com` returns an empty log set for ranges it does not serve (a block holding a known `Minted` event came back `[]`), which reads as a short mint. Never trust a log scan that has no cross-check: reconcile `sum(Minted.shares)` against the contract's `sold()` and `len(FreeClaimed)` against `freeClaimed()`, and widen the start block until they match. A scan landing 1,000 shares below `sold()` is a bad range, not a partial sellout.
- **Fixed `latest - N` windows understate participation.** The identity quota opens before the first paid mint and free claims can run earlier than any paid one, so the first events sit below a guessed start block. Widen backwards until the counters reconcile.
- **The paid count, not the wallet count, tells you the raise.** Free mints inflate supply enormously; the LP is funded only by paid shares. Compute LP size from paid shares and the LP split, never from total mints.
- **Free mint plus thin LP makes the user the exit liquidity.** The first seller gets roughly the mint price; by the few-hundredth seller the payout rounds to cents. Show the curve rather than the headline "$1 per share".
- **`hashlib.sha3_256` is not Keccak.** Selectors computed with the hashlib SHA3 module are wrong and every call reverts with a bare `execution reverted: 0x`, which reads like a broken contract instead of a broken probe. Compute with `Crypto.Hash.keccak` (or take the selector straight from the bytecode `63<selector>` constants and from the site's own ABI list) before concluding anything.
- **An unverified contract may still document itself.** Before calling it unauditable, fetch `/agent-brief.txt`, `/mcp.json`, `/llms.txt`, `/abi.json` at the site root: agent-facing projects publish their full selector table, error strings, events and constants there. Verified-source absence is a risk statement, not the end of the audit.
- **A 200 on those agent files can be the SPA catch-all.** On Cloudflare Pages every path returns the index HTML with status 200, so a successful curl proves nothing: check the body starts with `<!DOCTYPE` (or the content-type is `text/html`) and treat it as absent, then fall back to the inline-script ABI.
- **Marketplace indexers lie about new collections.** A listing page can show `Items 0`, no floor, no holders and "Content not available yet" while the chain already holds thousands of minted pieces and dozens of live asks. Never quote marketplace stats as the ledger; read the collection and its market contract over RPC and use the marketplace only for its orderbook (bids, collection offers).
- **`totalSupply` on an ERC721 usually does not exist.** An `0x` return means unsupported, not zero supply; verify with `name`/`symbol` and `balanceOf` instead.
- **Decode address returns from the padded word, not from the decimal value.** Take the last 40 hex chars and confirm by calling `name()` on the result; a bad decode points confidently at an unrelated contract.
- **Sourcify v1 endpoints are gone.** `/server/repository/...` and `/contracts/full_match/...` return a JSON 404 notice; use `/server/v2/contract/{chainId}/{address}?fields=sources,abi`.
- **The source JSON contains raw control characters.** Parse with `json.loads(raw, strict=False)` or it dies with `Invalid control character`.
- **Do not submit test entries to a campaign backend** to see how it behaves. Read its stats endpoint; never fabricate submissions, screenshots or wallet addresses.
- **The wallet that is eligible is not necessarily the wallet that can sign.** Agentic wallet and self-custody key are separate addresses with separate balances and separate NFTs; check the gate asset per address instead of assuming the connected wallet is the right one.
- **A site's agent prompt is a call template, not an ABI.** Pages that hand you a ready JSON prompt name the function, the args and sometimes the wrong gate address; every field still has to be confirmed against the verified ABI and the contract's own views, because a zero-quantity mint or a registry address that is not the gate reverts only at broadcast time.
- **Developer Mode being off is a user-side gate, not a tool failure.** The fix is enabling it in the Binance App (7-day validity, each use extends it), and the correct move is to state the steps and wait — never to sign the same call from another lane that fails the gate check.
- **A preview is not a broadcast.** It simulates and hands back a `requestId`; nothing is on chain and no `txHash` exists. Never let the user go looking for a transaction that only ever previewed, and never present a preview as done.
- **Order History is trading orders, not contract calls.** A Developer-Mode call appears as `txType: contract_call` in `baw wallet tx-history --binanceChainId 56`; the App's Orders page shows market/limit/prediction orders only, so an empty Orders list after a successful mint is expected. Note also that `tx-history` rejects `--limit` with `unknown option`; page it with the cursor flags instead of retrying.
- **Never auto-sell on a vague "kalau harganya tinggi".** A scheduled job cannot ask questions, so ask for the threshold once, in chat, before writing the job; otherwise make the job report-only and say you are waiting for the order.
- **A free claim is free of payment, not free of cost or risk.** It still costs gas, still requires the gate asset, and yields a token that may not be transferable for days. Say both before asking for the signature.
- **"Hold N+ NFTs to qualify for the token" with no token contract is the bait, not the value.** Price it: N times the floor is the real ask, and the verdict line is that the allocation has no contract, no snapshot and no announced supply. Sweep it into the same bucket as a prize pool whose treasury shows zero outflows.
- **A proof-of-work mint is a hardware gate, not a free mint.** "Free, no price" can hide a `keccak256(salt||sender||nonce) <= target` gate or a leading-zero `difficultyBits()` ladder, where expected work is `2^bits` doubling per step. Benchmark keccak on the actual host (a 2-core VPS is ~145k-900k H/s, a GPU is 3-4 orders faster) and quote the live difficulty plus the breakpoints before saying anyone can mint. Arithmetic per shape is in `references/nft-collection-audit.md`.
- **Public BSC RPC caps `eth_getLogs` ranges and answers `limit exceeded`.** `bsc-dataseed*.binance.org` / `defibit` reject even a 100-block query with `{"code":-32005,"message":"limit exceeded"}`, `1rpc` caps at 50 blocks, and some nodes want 25. Use `https://rpc-bsc.48.club` (1500-block chunks work, `User-Agent: Mozilla/5.0`), check the `error` key per chunk, and print the failed-chunk count: a loop that swallows the error returns zero events, which reads as "nothing happened on chain". An empty log set from one node is unverified, never proof.
- **A "404" name does not make an ERC404.** Check `decimals()` and query `getPair` on the V2 factory plus `getPool` on the V3 factory across fee tiers. If both come back empty and `decimals()` reverts, it is a plain ERC721 wearing 404 branding: no AMM, so the only exit is a marketplace bid.
- **A large `tokensPerShare` in a fair mint shrinks the dump curve; compute before reusing the exit-liquidity verdict.** When the per-share token amount is tiny against the seeded pool tokens, even a full cohort dump returns tens of percent of entry rather than cents, so quote the per-share payout at 0 / 1000 / all-sellers and the absolute cap on what can ever leave (the pool's whole quote reserve, not the FDV). The free-claimers-are-the-exit story is a calculation, not a default.
- **A launch-price multiple is a formula, not a promise.** A constant like `LAUNCH_PRICE_MULTIPLE = 2` derives `tokensPerShare` so the seeded open price is exactly N x mint price; say that the 2x exists only if a buyer takes the other side of a one-pair pool, and pair it with the refund branch (unfilled by deadline returns `refundBps`, e.g. 80%, rest to treasury) as the real downside bound.
- **An alert nobody can act on is noise, and eligibility is per project.** Every sibling deploys its own `identity()` wrapper, so a wallet can be eligible on one mint and a zero on the next; check the current contract's own gate, not a remembered verdict, and put the per-wallet result in the message so the user knows whether to move.
- **`identityOf` reverting on the gate contract usually means you called the registry, not the gate.** SPACE ID's handle registry exposes `handleOf(address)` (string) and `ownerOf`/`ownerOfHandle` only; an empty handle is "no ID". A zero ID from the wrapper, or a revert on the registry, is a wrong-address signal before it is a "gate broken" signal.
- **A struct view that returns strings has its fields shifted.** For `info()` returning `(string,string,...)`, word 0 is the offset to the struct; every later field sits relative to that struct start, so field k is at word 1+k after skipping the two string pointers. Reading words in absolute order silently assigns the treasury to `quote` and the pair to `native`.
- **595 log rows can be 418 humans or one bot army.** Recompute the participant count from `Minted`/`FreeClaimed` logs: distinct payer addresses, distinct IDs, and shares per payer. 4444 free claims from 4444 distinct handles against 418 paid wallets reads as free-allocation farming, and those wallets are the first sellers at launch.

## Reporting Shape

For this user's preview channel: casual Indonesian, no em dashes.

1. One bold verdict line that answers the question in a single sentence.
2. A short block of what is genuinely fine (contract verified, no admin, bounded approve, gate is a real NFT).
3. A short block of what makes it risky, each bullet carrying one hard number or address.
4. A recommendation line: skip, free-claim with gas only, or proceed, plus the specific approval caveat.
5. When the user takes the free-claim path, a separate short check-in before signing: eligible yes/no with the gate asset, exact gas in native units plus fiat, unlock date, and the one action still blocking execution (e.g. Developer Mode off).

No tables on Discord. Keep the arithmetic explicit enough that the user can check it.

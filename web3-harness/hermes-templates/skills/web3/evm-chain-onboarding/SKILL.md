---
name: evm-chain-onboarding
description: Use when adding a new EVM chain to a bot or harness.
version: 0.1.0
author: hermes-curator
license: MIT
metadata:
  hermes:
    tags: [web3, evm, viem, rpc, chains, mcp]
    related_skills: [pierre-web3, evm-wallet-verification]
---

# Adding an EVM Chain to a Multi-Chain Harness

## When to Use

- The user asks to add or support a chain: "bisa tambahin chain X?", "support this L2?", "kenapa chain X nggak ada di tool".
- A newly launched chain's tokens, NFTs, or presales must become inspectable or tradable by an existing bot.
- A market-data tool returns zeros or fallback for a chain and you must decide whether the chain is actually wired.
- Before answering "is chain X supported?" from code alone: confirm with a live RPC call.

Class of task: "bisa tambahin chain X?", wiring a newly launched L2 into an existing multi-chain trading/minting bot, or answering whether a chain is supported. The deliverable is a chain that resolves through every layer (type union, client factory, DEX path, explorer links, tool schema) and has been exercised with real reads, plus an honest statement of what still needs a restart or a fund.

## 1. Facts first, from the chain's own docs

Capture chainId, native currency, public RPC, explorer, and the vendor's deployment registry link. Aggregator blogs and search snippets for new chains are routinely wrong on chainId or list unverified endpoints.

Check whether viem already ships the chain before writing a definition:

```bash
node -e "const c=require('viem/chains');console.log(Object.keys(c).filter(k=>/KEYWORD/i.test(k)))"
```

If it exists (e.g. `robinhood`, chainId 4663), import it: id, RPC URLs, explorer and multicall3 come free, and the object is what `createPublicClient` / `createWalletClient` need. Prefer that over a hand-written `defineChain`.

## 2. Resolve contract addresses, then prove them on-chain

Use the vendor registry, not a search result. Uniswap publishes one file per chain id:

```
https://raw.githubusercontent.com/Uniswap/contracts/main/deployments/<chainId>.md
```

It lists `UniswapV2Router02`, `UniswapV2Factory`, `SwapRouter02`, `UniversalRouter`, `Permit2`. Then prove each address you intend to ship (`scripts/verify-chain-addresses.mjs <viem-chain-name> <router> [addr...]` prints chainId, live block, `factory()`, `WETH()` and code size):

- `router.factory()` must equal the documented factory address.
- `router.WETH()` gives the wrapped-native address to hardcode.
- `getCode(address) !== '0x'` for every address.
- `publicClient.getChainId()` and a live `getBlockNumber()` prove the RPC actually serves that chain.

Why this matters: on brand-new chains, same-name forks and a sentinel contract literally named `UnsupportedProtocol` sit at addresses that look canonical in blog posts, and a wrong router only surfaces later as a reverted mainnet tx.

## 3. Marketplace and screener slugs are their own identifiers

Never assume the chain slug equals the chainId or the name:

- OpenSea: `curl -s -H "X-API-KEY: $KEY" -A "Mozilla/5.0" https://api.opensea.io/api/v2/chains` and read the `chain` field. A wrong slug returns an empty/fallback payload that looks like an empty market.
- DexScreener: search a token that actually trades on the chain and read `chainId` off the returned pairs.

## 4. Enumerate every touch point before patching

Chain lists duplicate across layers. Grep the existing chain names first, then patch all hits in one pass:

```bash
grep -rn "ethereum'\|'bsc'\|base'" --include=*.ts src | grep -v test-
```

Typical layers in this kind of harness: type union + normalizer alias (and its error message listing supported chains), client factory (chain object + `<CHAIN>_RPC_URL` env fallback), DEX router / wrapped-native map, explorer tx URL builder, native symbol helper, and the MCP tool `inputSchema`/`description` strings that enumerate chains. The schema strings are not cosmetic: they are what the agent reads when choosing arguments, so a chain missing there gets ignored even though the code supports it.

Keep address literals lowercase or correctly checksummed; viem throws on a bad checksum at runtime, not at compile time.

## 5. Verify with real calls, not just a typecheck

1. `./node_modules/.bin/tsc -p tsconfig.json --noEmit` in the project dir.
2. A `tsx` probe that imports the project's own functions and asserts chainId, live block number, spend cap, router/wrapped-native pair, and the encoded sell selector (`0x791ac947` for `swapExactTokensForETHSupportingFeeOnTransferTokens`).
3. `fetchBestBid`-style read on an asset that genuinely trades on the chain, one ERC20 and one ERC721, checking the provenance field (`source: 'dexscreener'` / `'opensea-v2'`) rather than an HTTP 200. Find a real collection via `GET /api/v2/collections?chain=<slug>&limit=1` instead of inventing a contract.
4. Delete scratch probes; write them inside the project dir so `viem` resolves.

## 6. Deploy and make it live

- Long-running watchers: `pm2 restart <watcher>` picks the change up immediately.
- The MCP server is usually a long-lived child of the Hermes gateway, so tools keep the old chain list until the gateway restarts. That restart cannot be issued from inside the gateway process (the lifecycle guard refuses it, and it would kill the in-flight reply), so hand the user `hermes gateway restart` to run in their own shell. State it as the single remaining step instead of implying the feature is already live.
- Report the evidence: chainId, block height, live orderbook source and numbers. Then the cap: executions on a new chain need native gas there, so check the wallet balance on that chain and say "reads work, execution blocked until funded" when it is zero.

## 7. Cost and risk answer, unprompted

The user asks "nambah cost gak?" before approving an ops change. Answer it in the same message as the change:

- No subscription cost: same API keys, same free tiers; only quota is now shared across more chains (so 429s arrive sooner).
- Real cost is gas, and only when executing; per-tx caps (`MAX_ETH_PER_TX` / `MAX_BNB_PER_TX`) apply per chain, so the existing cap still bounds the new chain.
- Optional upgrade path (paid RPC) only if the public endpoint rate-limits; do not present it as required.

## 8. Repo hygiene after the patch

- Two copies usually exist: the running dir (e.g. `~/.hermes/web3-harness`) and a git checkout (e.g. `~/pierre-repo`). Copy the changed files into the repo and commit, so `git status` does not become a permanent unknown.
- Read `.github/workflows/deploy.yml` before pushing to `main`. A push-triggered deploy commonly does `cd <live dir> && git reset --hard origin/main` then `npm ci --omit=dev` and `pm2 restart` of the gateway app: that wipes live-only edits, `--omit=dev` deletes dev-only binaries the pm2 processes run on (`tsx` is a devDependency in this stack), and restarting the gateway app kills the session. Confirm the live dir is even a git checkout, and flag the hazard instead of discovering it mid-deploy.
- Sync any skill template copy of the chain table (e.g. `hermes-templates/skills/*/SKILL.md`) with the live skill; the template is what a fresh deploy installs.
- `git push` needs credentials this host may not have (no credential helper, no SSH key beyond `authorized_keys`). Check before promising a push; offering a repo deploy key with write access keeps the token out of chat.

## Pitfalls

- **A chain added to code is not a chain available to the agent.** The MCP process holds the schema it started with; until the gateway restarts, `chain="newchain"` still errors in the tool even though the source is patched and typechecks.
- **Do not size a chain addition by the diff.** Four files and a router map look small; the failures come from layers you did not grep for (explorer link, cap symbol, schema description, OpenSea slug).
- **No funding means no execution, not broken code.** Zero native balance on the new chain fails the simulation step with a gas error that reads like a contract bug; check the balance first.

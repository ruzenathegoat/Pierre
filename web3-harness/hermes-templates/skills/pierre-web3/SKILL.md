---
name: pierre-web3
description: Web3 NFT Minting, Trading, Airdrop Claiming, BNB Chain Agentic (.ai) Token Trading, and HWM Auto-Sell execution rules for Pierre.
---

# Pierre Web3 Execution & Portfolio Skill (`pierre-web3`)

This skill defines the standard operating procedures, URL/contract extraction workflows, hybrid wallet routing rules, and High-Water Mark (HWM) autonomous sell logic for **Pierre**.

---

## 1. Supported Chains & Hybrid Wallet Architecture

| Chain Name | Alias | Native Currency | Max Cap Env Var | Explorer |
| :--- | :--- | :--- | :--- | :--- |
| `base` | `base` | `ETH` | `MAX_ETH_PER_TX` (`0.05 ETH`) | `https://basescan.org` |
| `ethereum` | `eth`, `mainnet` | `ETH` | `MAX_ETH_PER_TX` (`0.05 ETH`) | `https://etherscan.io` |
| `bsc` | `bnb`, `binance` | `BNB` | `MAX_BNB_PER_TX` (`0.15 BNB`) | `https://bscscan.com` |
| `robinhood` | `rh`, `hood` | `ETH` | `MAX_ETH_PER_TX` (`0.05 ETH`) | `https://robinhoodchain.blockscout.com` |

**Robinhood Chain** = Arbitrum Orbit L2, chainId `4663`, gas in ETH, public RPC `https://rpc.mainnet.chain.robinhood.com` (override with `ROBINHOOD_RPC_URL`). viem ships a `robinhood` chain object, so no custom definition is needed.
- Uniswap V2 Router02 `0x89e5db8b5aa49aa85ac63f691524311aeb649eba` + WETH9 `0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73` (verified on-chain: `router.factory()` = `0x8bcEaA40B9AcdfAedF85AdF4FF01F5Ad6517937f`, `router.WETH()`). V2-style sell path (`swapExactTokensForETHSupportingFeeOnTransferTokens`) works.
- OpenSea chain slug and DexScreener chainId are both `robinhood` (confirmed via `GET /api/v2/chains` and DexScreener search).
- Pitfall: web results for Robinhood Chain routers are polluted with unofficial forks and with `UnsupportedProtocol` / old UR addresses. Trust `https://raw.githubusercontent.com/Uniswap/contracts/main/deployments/4663.md`, then confirm on-chain before wiring an address.

### Hybrid Wallet Routing Rules:
1. **Binance Agentic Wallet (`baw` CLI with `.ai` Agent ID — Tool: `execute_baw_agentic_trade`):**
   - Use this tool whenever trading **Four.Meme (`four.meme` OpenFour `.ai` Agent ID Exclusive Mode)** or **Flap (`flap.sh` ID Agent Curve)** tokens on **BNB Chain (`bsc`)**, especially when `inspect_market_orderbook` reports `launchpadStage: "BONDING_CURVE_EXCLUSIVE"`.
   - Workflow:
     1. Call `inspect_market_orderbook(chain="bsc", contractAddress="0x...", assetType="ERC20")`.
     2. Call `execute_baw_agentic_trade(action="QUOTE", chain="bsc", tokenAddress="0x...", amountBnb="...")` and present the quote to the user on Discord.
     3. Upon user confirmation, call `execute_baw_agentic_trade(action="BUY", chain="bsc", tokenAddress="0x...", assetName="...", amountBnb="...")`.
2. **Viem Isolated Private Key Wallet (Tools: `simulate_and_prepare_tx` $\rightarrow$ `execute_signed_tx`):**
   - Use for all EVM NFT mints/buys (`ERC721` / `ERC1155`), airdrop claims (`CLAIM`), and graduated DEX swaps (`PancakeSwap` on `bsc`, `Uniswap` on `base`/`ethereum`).
   - **NEVER** call `execute_signed_tx` without first running `simulate_and_prepare_tx` and receiving confirmation from the user.

---

## 2. Known Marketplace URL & Selector Patterns

### A. NFT Marketplaces & Launchpads (`base`, `ethereum`, `bsc`)
* **OpenSea (`opensea.io`):**
  * URL Pattern: `https://opensea.io/assets/<chain>/<contract_address>/<token_id>` or `https://opensea.io/collection/<slug>`
  * Orderbook & Fulfillment: Handled natively via `inspect_market_orderbook` and `execute_autonomous_sell` (Seaport v1.6 `0x0000000000000068F116a894984e2DB1123eB395`, Conduit `0x1E0049783F008A0085193E00003D00cd54003c71`).
* **Common Mint Selectors:**
  * `0x1249c58b` — `mint()` (zero-arg payable mint)
  * `0xa0712d68` — `mint(uint256 quantity)`
  * `0xfb0f3ee1` — Seaport `fulfillBasicOrder_efficient_6GL6yc`

### B. BNB Chain `.ai` Agent Token Launchpads & DEXs (`bsc`)
* **Four.Meme (`four.meme` — OpenFour `.ai` Agent ID Exclusive Mode):**
  * Bonding Curve Phase: Requires Binance Agentic Wallet with `.ai` Agent ID (`execute_baw_agentic_trade`). Max holding cap during curve is typically 1% of total supply.
  * Graduated Phase: Automatically migrates liquidity to PancakeSwap V2 (`0x10ED43C718714eb63d5aA57B78B54704E256024E`).
* **Flap (`flap.sh` — ID Agent Curve):**
  * Bonding Curve Phase: Trade via `execute_baw_agentic_trade`.
* **PancakeSwap V2 / Uniswap V2 Selectors:**
  * `0x7ff36ab5` — `swapExactETHForTokens`
  * `0xb6f9de95` — `swapExactETHForTokensSupportingFeeOnTransferTokens`
  * `0x791ac947` — `swapExactTokensForETHSupportingFeeOnTransferTokens` (used for selling `.ai` tokens with creator transfer tax)

---

## 3. HWM Trailing Peak Alert Evaluation (`TRAILING_PEAK_ALERT`)

When `watcher.ts` wakes you with a JSON payload containing `"trigger_type": "TRAILING_PEAK_ALERT"`:
1. Verify current open position state via `get_active_positions` and inspect `orderbook_context`:
   * `roi_pct`: Current ROI vs entry price (activation gate $\ge +30\%$).
   * `drop_from_peak_pct`: Drawdown from `high_water_mark_eth` (trigger threshold $\ge -5\%$).
   * `top_3_bids_eth`: Liquidity depth of top 3 bids/offers.
   * `sales_velocity_1h`: `"ACCELERATING"` | `"STABLE"` | `"DECELERATING"`.
2. **Decision Matrix:**
   * **EXECUTE SELL (`execute_autonomous_sell`):** If `sales_velocity_1h === "DECELERATING"`, OR if `top_3_bids_eth` shows a steep drop-off ($>15\%$ gap between 1st and 2nd/3rd bid), OR if `drop_from_peak_pct` is worsening rapidly $\rightarrow$ call `execute_autonomous_sell(positionId)` immediately to lock in profit.
   * **HOLD:** Only hold if `sales_velocity_1h === "ACCELERATING"` and bid support is tightly stacked. State your reasoning clearly; `watcher.ts` will apply a 5-minute cooldown and keep an emergency hard-stop at $-15\%$ drawdown.

---

## Order Alert Routing (mandatory for every execution)

Every order Pierre executes must announce itself in `#order-execution`. An order that ran but never posted is an unlogged order, so treat the alert as part of the execution, not as a report about it.

- **Through the harness MCP tools** (`execute_signed_tx`, `execute_autonomous_sell`, `execute_baw_agentic_trade`): `webhook.ts::broadcastToDiscord` already posts to `#order-execution`, then routes `BUY`/`MINT` to `#positions` and sells to `#positions` + `#pnl`. Pass the real action to `simulate_and_prepare_tx` (the enum accepts `BUY, MINT, CLAIM, SELL, AUTO_SELL, EMERGENCY_SELL, TRANSFER, SWAP, APPROVE, LP_ADD, LP_REMOVE, CONTRACT_CALL`) so the label is right; the harness trades only what was staged.
- **Outside the MCP** (direct `baw contract-call`, viem probe scripts, cron jobs, manual claims/sells/transfers): nothing broadcasts, so call the standalone poster yourself:

```
python3 ~/.hermes/scripts/order_alert.py --action MINT --chain BSC \
  --asset "Agentic Coin (AGC) · lane A share 1/2" --value "0.0100 BNB" \
  --contract 0x... --tx 0x... --source BAW_AGENTIC_WALLET_AI \
  --note "POSITION=5 share = 1,400,000 AGC" --also positions
```

- `--action` picks the colour (`MINT` champagne, `CLAIM` emerald, `TRANSFER` blue, `SWAP` violet, `SELL`/`AUTO_SELL` champagne, `EMERGENCY_SELL` crimson, `APPROVE`/`CONTRACT_CALL` slate); `--also positions,pnl` mirrors the harness routing. `--dry-run` prints the embed, `--check` prints which webhooks resolved without posting.
- Exit code 0 with `HTTP 204` per channel is success. Discord returns 204 on a webhook post; Python `urllib` gets blocked with Cloudflare `error code: 1010`, so the script posts via `curl` with a browser UA. A failed post exits 1 so a cron job surfaces it instead of silently going quiet.
- `COLORS` in `order_alert.py` mirrors `ACTION_COLORS` in `~/.hermes/web3-harness/src/webhook.ts`. Change both together, and remember the harness picks its copy up only when the MCP server respawns.

## 4. OpenSea API Key Hygiene

* `OPENSEA_API_KEY` lives in `~/.hermes/web3-harness/.env` (mode 600). `marketplace.ts` re-reads the file on every call, so a key edit takes effect without restarting the gateway or the MCP server.
* Never print or paste the key in chat. Ask the user to edit `.env` themselves; treat any key pasted in chat as burned and rotate it.
* Watchdog: `~/.hermes/scripts/opensea_key_watch.py` (cron job "OpenSea API key watchdog", daily 09:10 CST, `no_agent`, silent stdout when healthy). It mints a fresh free-tier key via `POST /api/v2/auth/keys` when the tracked expiry is under 48h, and alerts once per day when blocked.
* Pitfall: OpenSea serves reads with ANY non-empty `X-API-KEY`, so a 200 probe cannot prove a key is valid. Verify end to end with `inspect_market_orderbook` and check `source === "opensea-v2"` (fallback means no key data).
* Free keys expire in 7 days; minting is capped at 2 keys/day per IP and returns 429 after that. Cloudflare blocks Python's default user agent (error 1010), so send a normal UA when calling the API from scripts.

## 5. Learned Patterns Log (Self-Patched by Pierre)

<!-- SELF_PATCH_LOG_START -->
* Order alert workflow: every execution must post to `#order-execution`. Standalone poster `~/.hermes/scripts/order_alert.py` (curl-based, exit 1 on failed delivery) covers direct `baw` calls, viem scripts and cron jobs; harness paths keep using `broadcastToDiscord`. Widened `TradeActionType`/`ACTION_COLORS` in `db.ts`/`webhook.ts` and the `simulate_and_prepare_tx` actionType enum from `BUY|MINT|CLAIM` to the full 12-action set.
* Added `robinhood` (Robinhood Chain, chainId 4663) across `db.ts` normalizeChainName, `getClients`, `marketplace.ts` (OpenSea/DexScreener slug + Uniswap V2 router/WETH9), and `webhook.ts` Blockscout explorer URL. Addresses verified on-chain, not copied from blog posts.
* PACTURE (agent-gated fair mint on BSC) exit tooling: `pacture_swap_calldata.mjs` auto-detects which PancakeSwap V2 pair exists (PACTURE/WBNB -> swapExactTokensForETH..., PACTURE/USDT -> swapExactTokensForTokens) and prints approve+swap data; `pacture_autosell.py` runs as the `systemd --user pacture-autosell.service` resident loop (cron's 1-minute floor cannot trail a 0.45s-block pool). Rules: delta = clamp(k*sigma_horizon, 8%, 35%) from the realised variance of the executable-out series, flow-based regime flip (mu = net quote inflow / quote reserve), depth guard on the quote reserve, and a time cap after pool open. `--instant-if-mult N` sells at open instead of trailing. Gate: `PairCreated`/`getPair` on the V2 factory is the only way to know the pool exists, since the token is non-transferable until sold out.
<!-- SELF_PATCH_LOG_END -->


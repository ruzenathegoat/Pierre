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

## 4. Learned Patterns Log (Self-Patched by Pierre)

<!-- SELF_PATCH_LOG_START -->
* Initial baseline initialized with `opensea.io`, `four.meme`, `flap.sh`, `pancakeswap.finance` and standard mint/swap selectors.
<!-- SELF_PATCH_LOG_END -->


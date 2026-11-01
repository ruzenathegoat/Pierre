# Project Blueprint: "Pierre" — Web3 Hermes Trading  Agent

> **CRITICAL INSTRUCTIONS FOR AI CODING AGENTS (CLAUDE / CODEX / ANTIGRAVITY):**
>
> 1. **DO NOT BUILD EVERYTHING IN ONE SHOT.** You must execute this project strictly **Phase by Phase** (Sprint by Sprint).
>
> 2. **WAIT FOR USER CONFIRMATION** after completing each Phase and verifying its **Exit Criteria** before writing code for the next Phase.
>
> 3. **UPDATE PROGRESS:** Whenever a task is completed and tested, mark its checkbox from `[ ]` to `[x]` in this file so future sessions immediately know the current state.
>
> 4. **STRICT STDIO RULE:** Inside the MCP Server (`mcp-server.ts`), **NEVER use `console.log()`** because `stdout` is reserved for JSON-RPC communication with Hermes Agent. Always use `console.error()` for logging.
>
> 5. **NEVER EXPOSE SECRETS:** Private keys, OpenRouter API keys, Discord tokens, and Webhook URLs must only be loaded via `dotenv` from `.env` and never hardcoded or exposed to the LLM context.

## 1. System Architecture & Tech Stack Overview

* **Agent Name:** Pierre

* **Core Orchestrator:** Hermes Agent (`NousResearch/hermes-agent`)

* **LLM Brain (Ultra-Low Latency & Cost):** **DeepSeek V4 Flash** via **OpenRouter API** (`deepseek/deepseek-v4-flash` / `deepseek/deepseek-v4-flash-latest`), authenticated via `OPENROUTER_API_KEY`.

* **Input Gateway:** Discord Bot (`DISCORD_BOT_TOKEN` with `Message Content Intent` enabled, locked to `DISCORD_ALLOWED_USERS`).

* **Execution Harness (Hybrid Wallet Architecture):** Custom TypeScript MCP Server (`@modelcontextprotocol/sdk`) combining:
  * **Viem Isolated Private Key (`WALLET_PRIVATE_KEY`):** For **Base**, **Ethereum**, & **BNB Smart Chain (`bsc`)** (ERC-721/1155 NFTs, PancakeSwap/Uniswap V2 swaps, & public contracts).
  * **Binance Agentic Wallet CLI (`@binance/agentic-wallet` / `baw` with `.ai` Agent ID):** For **Four.Meme (OpenFour `.ai` Agent ID Exclusive Mode)** and **Flap (ID Agent Curve)** bonding curves on BNB Chain where a verified `.ai` Agent ID is required, plus seamless graduation trading on PancakeSwap.

* **State & Memory (No LangGraph):**

  * **Financial State (Single Source of Truth):** Local SQLite (`trades.db` via `better-sqlite3` in **WAL mode**) storing `trades` history, open `positions` (with High-Water Mark & alert cooldown tracking), and persistent `staged_transactions` (5-minute TTL).

  * **Conversational & Procedural Memory:** Hermes native SQLite (`~/.hermes/state.db`), persistent rules (`~/.hermes/MEMORY.md`), and self-patching skills (`~/.hermes/skills/pierre-web3/SKILL.md`).

* **Autonomous Sell Engine:** Background Node.js/TypeScript daemon (`watcher.ts`) polling best bids every 15–30 seconds without burning LLM tokens, waking Pierre via Structured Context Injection only when trailing peak conditions are met.

* **Multi-Channel Trade Feed Notification (`src/webhook.ts`):** Deterministic, extensible Discord Webhook Router supporting dedicated channels:
  * **Channel 1 — `#positions` (`DISCORD_WEBHOOK_POSITIONS`):** Tracks `POSITION_OPENED`, `HWM_UPDATED`, `TRAILING_PEAK_ALERT`, and `POSITION_CLOSED`.
  * **Channel 2 — `#order-execution` (`DISCORD_WEBHOOK_ORDER_EXECUTION`):** Logs raw transaction receipts (`BUY`, `MINT`, `CLAIM`, `AUTO_SELL`, `EMERGENCY_SELL`) with explorer links.
  * **Channel 3 — `#pnl` (`DISCORD_WEBHOOK_PNL`):** Broadcasts dedicated Realized PnL & ROI % cards upon closing positions.
  * **Dynamic Extensibility (`DISCORD_WEBHOOK_<CHANNEL_NAME>`):** Adding any new channel in the future only requires adding `DISCORD_WEBHOOK_<NAMA_CHANNEL>` in `.env`.

* **Production Infrastructure:** **Tencent Cloud Lighthouse** VPS (`2 vCPU, 2 GB RAM, 40 GB SSD`) in **Singapore (`ap-singapore`)** running the official **Hermes Agent v0.21.5** Application Image, managed by **PM2** and deployed via **GitHub Actions SSH CI/CD**.

## 2. Directory Structure

```
~/.hermes/
├── config.yaml                       # Hermes Agent, OpenRouter model & MCP Server registration
├── MEMORY.md                         # Persistent instructions & Self-Patching rules
├── .env                              # OpenRouter API Key, Discord Bot Token & gateway config
├── skills/
│   └── pierre-web3/
│       └── SKILL.md                  # Self-updating Web3 patterns skill
└── web3-harness/                     # Git repository synced via CI/CD
    ├── .github/
    │   └── workflows/
    │       └── deploy.yml            # GitHub Actions CI/CD to Tencent Cloud Lighthouse VPS
    ├── src/
    │   ├── db.ts                     # SQLite (WAL mode) initialization & queries
    │   ├── marketplace.ts            # Free-Tier OpenSea API v2 (auto-key) & DexScreener orderbook/fulfillment
    │   ├── webhook.ts                # Multi-Channel Discord Rich Embed Webhook Router
    │   ├── baw-keepalive.ts          # 6-hour Binance Agentic Wallet (.ai) session keep-alive heartbeat
    │   ├── mcp-server.ts             # Viem + BAW MCP Server (Simulate, Execute, Orderbook, Auto-Sell, State)
    │   └── watcher.ts                # 24/7 HWM Price Watcher, Context Trigger & BAW Keep-Alive Daemon
    ├── known_patterns.json           # Domains & ABI function selectors registry
    ├── trades.db                     # Local SQLite database (gitignored)
    ├── .env                          # Isolated Wallet Private Key & RPC URLs (gitignored)
    ├── .env.example                  # Template for environment variables
    ├── .gitignore
    ├── package.json
    └── tsconfig.json

```

## 3. Mathematical & Algorithmic Specifications

### A. High-Water Mark (HWM) & Trailing Peak Calculation (`watcher.ts`)

For every open position in the `positions` table, `watcher.ts` fetches the **Current Best Bid / Top Offer** (instant liquidity price, NOT floor list price) every 15–30 seconds and computes:

$$
\text{HWM}_{\text{new}} = \max(\text{HWM}_{\text{old}}, \text{Bid}_{\text{current}})
$$

$$
\text{ROI}_{\text{current}} = \frac{\text{Bid}_{\text{current}} - \text{Price}_{\text{entry}}}{\text{Price}_{\text{entry}}}
$$

$$
\text{Drawdown}_{\text{peak}} = \frac{\text{HWM}_{\text{new}} - \text{Bid}_{\text{current}}}{\text{HWM}_{\text{new}}}
$$

* **Activation Gate:** Only activate trailing peak alert when $\text{ROI}_{\text{current}} \ge \theta_{\text{profit}}$ (e.g., $0.30$ or $+30\%$).

* **Trigger Condition & Anti-Spam Cooldown:** Wake Pierre (LLM) with a **Structured Context Payload** when $\text{Drawdown}_{\text{peak}} \ge \delta_{\text{trail}}$ (e.g., $0.05$ or $-5\%$ drop from peak) OR when orderbook top bids show thin depth. If Pierre decides to **HOLD**, enforce a **5-minute Alert Cooldown** (`last_alerted_at`) so `watcher.ts` does not spam LLM calls every 20 seconds unless drawdown breaches the emergency threshold.

* **Hard Stop Fallback (Zero-LLM):** If $\text{Drawdown}_{\text{peak}} \ge \delta_{\text{emergency}}$ (e.g., $0.15$ or $-15\%$ crash) or LLM API is unreachable, execute the instant sell fulfillment (including ERC-721/1155 `setApprovalForAll` check) deterministically without waiting for LLM reasoning.

### B. Structured Context Payload Format (Sent by `watcher.ts` to Pierre)

```
{
  "trigger_type": "TRAILING_PEAK_ALERT",
  "position_id": 1,
  "asset": "Collection Name #ID",
  "chain": "base",
  "entry_price_eth": 0.05,
  "current_best_bid_eth": 0.135,
  "high_water_mark_eth": 0.142,
  "roi_pct": "+170.0%",
  "drop_from_peak_pct": "-4.93%",
  "orderbook_context": {
    "top_3_bids_eth": [0.135, 0.132, 0.110],
    "sales_velocity_1h": "DECELERATING",
    "listed_ratio_pct": 4.2
  }
}

```

## 4. Phased Implementation Roadmap (Step-by-Step Sprints)

### PHASE 1: Local Project Scaffolding, SQLite Ledger & Webhook Module

**Objective:** Set up the TypeScript repository on local machine, configure strict type-checking, build the SQLite database layer (`db.ts`), and implement the Discord Webhook broadcaster (`webhook.ts`).

#### Tasks:

* \[x\] **1.1 Initialize Repository:** Create `web3-harness` directory, run `npm init -y`, and install dependencies:

  ```
  npm install @modelcontextprotocol/sdk viem better-sqlite3 dotenv zod
  npm install -D @types/node @types/better-sqlite3 typescript tsx
  
  ```

* \[x\] **1.2 Configure TypeScript & Gitignore:**

  * Create `tsconfig.json` with `"module": "NodeNext"`, `"moduleResolution": "NodeNext"`, `"target": "ES2022"`, `"strict": true`.

  * Create `.gitignore` excluding `node_modules/`, `.env`, `*.db`, `*.db-journal`, `*.db-wal`, `*.db-shm`, `dist/`.

  * Create `.env.example` with placeholders:

    ```
    WALLET_PRIVATE_KEY=0x...
    BASE_RPC_URL=https://base-mainnet.g.alchemy.com/v2/YOUR_KEY
    ETH_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY
    BSC_RPC_URL=https://bsc-dataseed.bnbchain.org
    # Optional: if empty, marketplace.ts auto-generates & rotates a free 7-day key via OpenSea /api/v2/auth/keys
    OPENSEA_API_KEY=
    MAX_ETH_PER_TX=0.05
    MAX_BNB_PER_TX=0.15
    BAW_CLI_PATH=baw
    DEX_SLIPPAGE_BPS=300
    # Multi-Channel Discord Webhooks (Extensible: add DISCORD_WEBHOOK_<CHANNEL_NAME> for future channels)
    DISCORD_WEBHOOK_POSITIONS=https://discord.com/api/webhooks/...
    DISCORD_WEBHOOK_ORDER_EXECUTION=https://discord.com/api/webhooks/...
    DISCORD_WEBHOOK_PNL=https://discord.com/api/webhooks/...
    DISCORD_TRADE_WEBHOOK_URL=https://discord.com/api/webhooks/...
    
    ```

* \[x\] **1.3 Build Database Module (`src/db.ts`):**

  * Initialize `better-sqlite3` pointing to `trades.db` and immediately enable concurrent access safety:

    ```
    db.pragma('journal_mode = WAL');
    db.pragma('busy_timeout = 5000');
    
    ```

  * Create table `trades`:

    ```
    CREATE TABLE IF NOT EXISTS trades (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tx_hash TEXT,
      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
      action TEXT,
      chain TEXT,
      contract_address TEXT,
      asset_name TEXT,
      price_eth REAL,
      realized_pnl_eth REAL DEFAULT 0,
      trigger_source TEXT
    );
    
    ```

  * Create table `positions` (including `asset_type` and `last_alerted_at` for anti-spam cooldown):

    ```
    CREATE TABLE IF NOT EXISTS positions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chain TEXT,
      contract_address TEXT,
      token_id TEXT,
      asset_type TEXT DEFAULT 'ERC721',
      asset_name TEXT,
      entry_price_eth REAL,
      high_water_mark_eth REAL,
      status TEXT DEFAULT 'OPEN',
      last_alerted_at DATETIME,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    
    ```

  * Create table `staged_transactions` (persistent across MCP stdio turns with 5-minute TTL):

    ```
    CREATE TABLE IF NOT EXISTS staged_transactions (
      tx_id TEXT PRIMARY KEY,
      chain TEXT,
      contract_address TEXT,
      calldata TEXT,
      value_eth REAL,
      action_type TEXT,
      asset_name TEXT,
      source_url TEXT,
      token_id TEXT,
      is_fresh_input INTEGER DEFAULT 0,
      expires_at INTEGER
    );
    
    ```

  * Export helper functions: `insertTrade()`, `insertPosition()`, `getOpenPositions()`, `getPositionById()`, `updateHWM()`, `markPositionAlerted()`, `closePosition()`, `saveStagedTx()`, `getValidStagedTx()`, `deleteStagedTx()`.

* \[x\] **1.4 Build Multi-Channel Discord Webhook Router (`src/webhook.ts`):**

  * Implement `resolveWebhookUrl(channel)`, `sendDiscordChannelEmbed()`, `broadcastPositionUpdate()`, `broadcastPnlReport()`, and `broadcastToDiscord()` routing Rich Embeds across `#positions`, `#order-execution`, `#pnl`, and any future `DISCORD_WEBHOOK_<CHANNEL_NAME>` channel with dynamic colors, explorer links (`basescan.org` / `etherscan.io` / `bscscan.com`), and native currency symbols (`ETH` / `BNB`).

#### Phase 1 Exit Criteria:

* Running `npx tsc --noEmit` returns zero errors.

* Running a small test script creates `trades.db` and sends a test embed message to the Discord Webhook channel.

### PHASE 2: Core Viem MCP Server & Dry-Run Simulation Harness

**Objective:** Build `src/mcp-server.ts` exposing isolated wallet tools to Pierre with mandatory `eth_call` / `estimateGas` simulation and hardcoded spending caps.

#### Tasks:

* \[x\] **2.1 Initialize Viem Clients & Signer Isolation:**

  * Load `WALLET_PRIVATE_KEY` via `dotenv` into `privateKeyToAccount()`.

  * Create `getClients(chainName)` helper returning `publicClient` and `walletClient` for `base`, `ethereum`, and `bsc` (accepting `bnb` as an alias for `bsc`).

  * Use SQLite `staged_transactions` (5-minute TTL) to persist simulated transactions across MCP stdio invocations.

* \[x\] **2.2 Implement Tool 1 — `get_active_positions` (Anti-Context-Loss Tool):**

  * Queries `SELECT * FROM positions WHERE status = 'OPEN'` from `trades.db` so Pierre always reads exact entry prices and HWM values from SQLite instead of relying on chat history.

* \[x\] **2.3 Implement Tool 2 — `simulate_and_prepare_tx`:**

  * Accepts `chain` (`base` | `ethereum` | `bsc`), `contractAddress`, `calldata`, `valueEth` (native value in ETH or BNB), `actionType`, `assetName`, `sourceUrl`, and optional `tokenId` (since `tokenId` is unknown prior to mining during `MINT`).

  * **Guardrail 1:** Block immediately if `parseFloat(valueEth)` exceeds `MAX_BNB_PER_TX` (on `bsc`) or `MAX_ETH_PER_TX` (on `base` / `ethereum`).

  * **Guardrail 2:** Run `publicClient.estimateGas()` and `publicClient.call()` dry-run simulation. If it reverts, return `SIMULATION_REVERTED` with exact reason.

  * Check `known_patterns.json` against `sourceUrl` domain and `calldata.slice(0, 10)` selector to set `is_fresh_input: boolean`.

  * Save valid payload in SQLite `staged_transactions` via `saveStagedTx()` with a 5-minute TTL and unique `tx_id`, returning preview to Pierre.

* \[x\] **2.4 Implement Tool 3 — `execute_signed_tx`:**

  * Accepts `txId`, retrieves and validates non-expired payload via `getValidStagedTx(txId)`, then signs and broadcasts via `walletClient.sendTransaction()`.

  * Waits for receipt via `publicClient.waitForTransactionReceipt()`.

  * **Auto-Extract `tokenId` on `MINT`/`BUY`:** If `tokenId` was not provided upfront, parse `receipt.logs` for the ERC-721 `Transfer(from, to, tokenId)` or ERC-1155 `TransferSingle` event matching `wallet.address` so the exact minted/purchased `token_id` is recorded accurately.

  * Logs trade to `trades` table, adds to `positions` table if `BUY`/`MINT`, deletes the consumed `staged_transactions` row, and triggers `broadcastToDiscord()`.

* \[x\] **2.5 Implement Free-Tier Marketplace Module (`src/marketplace.ts`), Tool 4 (`inspect_market_orderbook`) & Tool 5 (`execute_autonomous_sell`):**

  * In `src/marketplace.ts`, implement 100% Free-Tier orderbook & fulfillment helpers:
    * **OpenSea API v2 (for ERC-721 / ERC-1155 NFTs):** Auto-provisions & caches a free 7-day API key via `POST https://api.opensea.io/api/v2/auth/keys` if `OPENSEA_API_KEY` is blank. Fetches highest executable bid, top 3 bid depth, and listed ratio via `/api/v2/offers/collection/...`, and generates Seaport instant-sell fulfillment calldata via `POST /api/v2/offers/fulfillment_data`.
    * **DexScreener API (for ERC-20 Tokens):** Queries `https://api.dexscreener.com/latest/dex/tokens/{address}` (free, no API key required, 300 req/min) for real-time price in ETH/USD, liquidity depth, and 1h buy/sell velocity.

  * **Tool 4 — `inspect_market_orderbook` (On-Demand Orderbook Inspector):**
    * Accepts `chain`, `contractAddress`, `tokenId` (optional), and `assetType` (`ERC721` | `ERC1155` | `ERC20`).
    * Returns live best bid, top 3 bids depth, floor price, 1h sales velocity, and liquidity metrics so Pierre can inspect the market on-demand whenever asked on Discord or right before selling.

  * **Tool 5 — `execute_autonomous_sell`:**
    * Accepts `positionId` (plus optional override `marketplaceRouter`, `sellCalldata`, `expectedBidEth`).
    * Supports **both NFTs (Seaport)** and **`.ai` BEP-20/ERC-20 Agent Tokens** (routing via `baw market-order swap` if held in Binance Agentic Wallet MPC, or via PancakeSwap/Uniswap V2 `swapExactTokensForETHSupportingFeeOnTransferTokens` if held in local Viem wallet).
    * **Mandatory Approval Check:** Checks `isApprovedForAll` (for NFTs) or ERC-20 `allowance` $\rightarrow$ `approve` so sells never revert.
    * Executes instant sell transaction, updates `positions` status to `CLOSED`, calculates `realized_pnl_eth`, logs to `trades`, and broadcasts to Discord Webhook.

  * **Tool 6 — `execute_baw_agentic_trade` (Binance Agentic Wallet `.ai` Exclusive Bridge):**
    * Accepts `action` (`STATUS` | `QUOTE` | `BUY` | `SELL`), `chain` (`bsc`), `tokenAddress`, `assetName`, `amountBnb`, `positionId`.
    * Bridges Pierre to `@binance/agentic-wallet` (`baw` CLI) holding a verified `.ai` Agent ID to trade **Four.Meme (`.ai` Exclusive Mode)** & **Flap** bonding curves, enforcing `MAX_BNB_PER_TX` guardrails, logging positions to `trades.db` for 24/7 HWM tracking, and broadcasting to Discord Webhook.

#### Phase 2 Exit Criteria:

* Running `npx tsx src/mcp-server.ts` starts cleanly and prints `"Hermes Viem MCP Harness berjalan di stdio..."` to `stderr` without crashing.

* `npx tsc --noEmit` passes with zero errors.

### PHASE 3: Self-Patching Skill Engine ("Fresh Input" Loop)

**Objective:** Configure Pierre's procedural memory so every new marketplace URL or contract pattern automatically triggers `skill_manage(action="patch")` after responding to the user.

#### Tasks:

* \[x\] **3.1 Create Pattern Registry (`known_patterns.json`):**

  ```
  {
    "domains": ["opensea.io", "magiceden.io", "blur.io"],
    "selectors": ["0x1249c58b", "0xa0712d68"]
  }
  
  ```

* \[x\] **3.2 Add Pattern Updater Tool (`register_learned_pattern`) in `mcp-server.ts`:**

  * Expose a quick MCP tool allowing Pierre to append newly verified domains and 4-byte selectors to `known_patterns.json` alongside patching its `SKILL.md`.

* \[x\] **3.3 Create Base Skill Template (`~/.hermes/skills/pierre-web3/SKILL.md`):**

  * Define YAML frontmatter (`name: pierre-web3`, `description: Web3 NFT Minting, Trading, Airdrop Claiming, and HWM Auto-Sell execution rules`).

  * Document known URL structures, ABI extraction procedures, and simulation requirements.

* \[x\] **3.4 Configure Persistent Self-Patching Directive (`~/.hermes/MEMORY.md`):**

  * Add strict operational rule for Pierre:

    ```
    ## Identity: Pierre (Web3 Execution & Portfolio Agent)
    1. Never execute a write transaction without calling `simulate_and_prepare_tx` first.
    2. Always check `get_active_positions` and `inspect_market_orderbook` when asked about portfolio status, orderbook depth, or sell decisions.
    3. SELF-PATCHING RULE: Whenever `simulate_and_prepare_tx` returns `"is_fresh_input": true` and the transaction succeeds:
       - First, deliver the final transaction summary to the user on Discord.
       - Second, immediately call `skill_manage(action="patch", name="pierre-web3", ...)` and `register_learned_pattern` to record the new URL pattern, contract method selector, and extraction workflow.
    
    ```

#### Phase 3 Exit Criteria:

* Skill file and `MEMORY.md` templates are created and validated for Hermes Agent compatibility.

### PHASE 4: Deterministic HWM Watcher Daemon (`src/watcher.ts`)

**Objective:** Build the background polling service that tracks peak prices 24/7 with zero LLM token usage during normal price movement, waking Pierre only when trailing peak conditions trigger.

#### Tasks:

* \[x\] **4.1 Build Market Bid Fetcher (`src/marketplace.ts` & `src/watcher.ts`):**

  * Implement `fetchBestBidEth(chain, contractAddress, tokenId, assetType)` using **OpenSea API v2** (for ERC-721/1155 NFTs, with automatic 7-day free key provisioning) and **DexScreener API** (for ERC-20 tokens) to retrieve the highest executable instant bid, top 3 bid depth, and 1h velocity while respecting `X-RateLimit-Remaining` headers.

* \[x\] **4.2 Implement HWM Update Loop (Every 20 Seconds):**

  * Fetch all `OPEN` rows from `positions` table.

  * If `currentBestBid > position.high_water_mark_eth`, update `high_water_mark_eth` in SQLite immediately.

* \[x\] **4.3 Implement Trailing Peak Alert, Cooldown Gate & Emergency Fallback:**

  * Calculate $\text{ROI}_{\text{current}}$ and $\text{Drawdown}_{\text{peak}}$.

  * **Emergency Hard-Stop Fallback (Zero-LLM):** If $\text{Drawdown}_{\text{peak}} \ge 0.15$ (or if Hermes CLI fails/times out), bypass LLM reasoning and execute the instant sell directly via `fetchInstantSellFulfillment()` + Viem (`setApprovalForAll` check + fulfillment broadcast) or `baw market-order swap` inside `watcher.ts`.

  * **Trailing Peak LLM Trigger (with 5-Min Cooldown):** If $\text{ROI}_{\text{current}} \ge 0.30$ and $\text{Drawdown}_{\text{peak}} \ge 0.05$, check `last_alerted_at` to ensure at least 5 minutes have elapsed since the last alert (preventing token-draining loops if Pierre chose to `HOLD`):

    * Call `markPositionAlerted(position.id)` in SQLite.

    * Construct the JSON **Structured Context Payload** (including orderbook bid depth and sales velocity).

    * Invoke Hermes CLI (`hermes chat --message "<JSON_CONTEXT_PAYLOAD>"`) to wake Pierre so Pierre evaluates the orderbook context and calls `execute_autonomous_sell(positionId)` (or holds if orderbook support is strong).

* \[x\] **4.4 Implement Binance Agentic Wallet 6-Hour Session Keep-Alive (`src/baw-keepalive.ts`):**

  * Because Binance Web3 MPC / Agentic Wallets (`.ai`) automatically unbind/log out after **48 hours of inactivity**, execute a zero-cost authenticated heartbeat (`baw wallet status`, `baw wallet balance`, and `baw market-order quote` on BSC) every **6 hours** inside `watcher.ts` (and via PM2 cron `baw-keepalive`).
  * Automatically send a high-priority warning embed to Discord `#positions` if the session is ever detected as unbound/expired.

#### Phase 4 Exit Criteria:

* Inserting a mock open position into `trades.db` and simulating a rising then dropping bid price accurately updates `high_water_mark_eth` and triggers the structured payload alert.

### PHASE 5: Tencent Cloud Lighthouse (`Hermes Agent` Image), Node.js Setup & OpenRouter (DeepSeek V4 Flash)

**Objective:** Harden the Tencent Cloud Lighthouse VPS (pre-installed with the `Hermes Agent v0.21.5` Application Image in Singapore), install Node.js v22 + PM2 for the Web3 harness, configure OpenRouter with DeepSeek V4 Flash, and connect the Discord Bot gateway.

#### Tasks:

* \[x\] **5.1 Harden Tencent Cloud Lighthouse VPS (`Hermes Agent v0.21.5` Image, Singapore):**

  * Instance provisioned on **Tencent Cloud Lighthouse** in **Singapore (`ap-singapore`)** (`2vCPUs 2GB, 40GB SSD`) with the **Hermes Agent v0.21.5** Application Image. Bind your SSH key in the Lighthouse Console.

  * In the **Tencent Cloud Lighthouse Console $\rightarrow$ Firewall**, restrict inbound rules to only allow `SSH (TCP:22)` (remove default HTTP/HTTPS rules if unused, as Discord Gateway & Webhooks use outbound connections only).

  * Automated via `bash ~/.hermes/web3-harness/scripts/setup-vps.sh` (or run manually):

    ```
    sudo apt update && sudo apt upgrade -y
    sudo apt install -y git curl wget unzip jq build-essential sqlite3 ufw fail2ban
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    sudo ufw allow OpenSSH
    sudo ufw enable
    
    ```

* \[x\] **5.2 Verify Pre-installed Hermes Agent, Install Node.js v22 + PM2 & Binance Agentic Wallet (`baw`):**

  * Because the Tencent Lighthouse **Hermes Agent v0.21.5** image already includes Python (`uv`) and `hermes-agent` pre-installed, verify Hermes and install Node.js v22 + PM2 + `@binance/agentic-wallet` (`baw` CLI):

    ```
    hermes --version
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
    source ~/.bashrc
    nvm install 22 && nvm use 22
    npm install -g pm2 tsx @binance/agentic-wallet
    npx skills add binance/binance-skills-hub/skills/binance-web3/binance-agentic-wallet
    
    ```
  * Authenticate your **Binance Agentic Wallet (`.ai` Agent ID)**:
    1. In the **Binance Mobile App** $\rightarrow$ **Web3 Wallet**, claim/enable your **`.ai` Agent ID** and enable **Wallet Settings $\rightarrow$ Developer Mode**.
    2. Run `baw auth signin` on the VPS terminal and scan the QR code from the Binance App.
    3. Verify via `baw wallet status` and `baw wallet address`.

* \[x\] **5.3 Configure OpenRouter API & DeepSeek V4 Flash Model:**

  * Store the OpenRouter API key in `~/.hermes/.env`:

    ```
    hermes config set OPENROUTER_API_KEY sk-or-v1-YOUR_KEY
    
    ```

  * Configure `openrouter` and **DeepSeek V4 Flash** (`deepseek/deepseek-v4-flash` or `deepseek/deepseek-v4-flash-latest`) in `~/.hermes/config.yaml` (or interactively via `hermes model`):

    ```
    model:
      provider: openrouter
      default: deepseek/deepseek-v4-flash
    
    ```

* \[x\] **5.4 Configure Discord Bot & `~/.hermes/config.yaml`:**

  * Add `OPENROUTER_API_KEY`, `DISCORD_BOT_TOKEN`, and `DISCORD_ALLOWED_USERS=<YOUR_DISCORD_USER_ID>` to `~/.hermes/.env`.

  * Register `viem_web3_harness` under `mcp_servers` alongside the `model` config in `~/.hermes/config.yaml` (adjust `/home/ubuntu` to `/root` if running under the `root` user):

    ```
    model:
      provider: openrouter
      default: deepseek/deepseek-v4-flash

    mcp_servers:
      viem_web3_harness:
        command: "tsx"
        args:
          - "/home/ubuntu/.hermes/web3-harness/src/mcp-server.ts"
        env:
          NODE_NO_WARNINGS: "1"
    
    ```

#### Phase 5 Exit Criteria:

* Running `hermes` CLI and typing `/tools` displays `get_active_positions`, `inspect_market_orderbook`, `simulate_and_prepare_tx`, `execute_signed_tx`, `execute_autonomous_sell`, `execute_baw_agentic_trade`, and `register_learned_pattern`.

* Sending a message to Pierre on Discord returns a response powered by **DeepSeek V4 Flash** (`deepseek/deepseek-v4-flash`) via OpenRouter.

### PHASE 6: CI/CD Pipeline (GitHub Actions $\rightarrow$ Tencent Cloud Lighthouse PM2) & Live Dry-Run

**Objective:** Automate deployment from local VS Code to the Tencent Cloud Lighthouse VPS and run a complete end-to-end paper/micro transaction test.

#### Tasks:

* \[x\] **6.1 Create GitHub Actions Workflow (`.github/workflows/deploy.yml`):**

  * Configure GitHub Repository Secrets: `VPS_HOST` (Tencent Lighthouse Public IP), `VPS_USER` (`ubuntu` or `root`), and `VPS_SSH_KEY` (Private SSH Key).

  ```
  name: Deploy Pierre Web3 Harness to Tencent Lighthouse VPS
  
  on:
    push:
      branches:
        - main
  
  jobs:
    validate-and-deploy:
      runs-on: ubuntu-latest
      steps:
        - name: Checkout Repository
          uses: actions/checkout@v4
  
        - name: Setup Node.js & Typecheck
          uses: actions/setup-node@v4
          with:
            node-version: "22"
            cache: "npm"
        - run: npm ci
        - run: npx tsc --noEmit
  
        - name: Deploy to Tencent Cloud Lighthouse via SSH
          uses: appleboy/ssh-action@v1.0.3
          with:
            host: ${{ secrets.VPS_HOST }}
            username: ${{ secrets.VPS_USER }}
            key: ${{ secrets.VPS_SSH_KEY }}
            script: |
              export NVM_DIR="$HOME/.nvm"
              [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
              cd ~/.hermes/web3-harness
              git fetch origin main
              git reset --hard origin/main
              npm ci --omit=dev
              pm2 restart price-watcher
              pm2 restart hermes-discord
  
  ```

* \[x\] **6.2 Start & Persist PM2 Processes (Including 6h BAW Session Keep-Alive Cron) on Tencent Cloud Lighthouse:**

  ```
  pm2 start "hermes gateway" --name "hermes-discord"
  pm2 start "tsx ~/.hermes/web3-harness/src/watcher.ts" --name "price-watcher"
  pm2 start "tsx ~/.hermes/web3-harness/src/baw-keepalive.ts" --name "baw-keepalive" --cron-restart="0 */6 * * *" --no-autorestart
  pm2 save
  pm2 startup
  
  ```

* \[x\] **6.3 End-to-End Acceptance Testing:**

  * Test 1: Send a sample NFT/mint link on Discord $\rightarrow$ Verify dry-run simulation preview $\rightarrow$ Confirm execution $\rightarrow$ Verify SQLite entry & Discord Webhook broadcast.

  * Test 2: Verify `is_fresh_input: true` triggers `skill_manage(action="patch")` on `pierre-web3/SKILL.md`.

  * Test 3: Verify `git push origin main` from local PC automatically updates the Tencent Cloud Lighthouse VPS and restarts PM2 without losing SQLite state.

#### Phase 6 Exit Criteria:

* All 3 acceptance tests pass in production on the Tencent Cloud Lighthouse VPS.
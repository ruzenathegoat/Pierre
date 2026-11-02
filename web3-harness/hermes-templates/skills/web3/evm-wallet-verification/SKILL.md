---
name: evm-wallet-verification
description: Use when an EVM key or API data feed must be verified.
version: 0.1.0
author: hermes-curator
license: MIT
metadata:
  hermes:
    tags: [web3, wallet, viem, rpc, verification]
    related_skills: [pierre-web3]
---

# EVM Wallet Verification

Answers "is this private key actually wired up, and does the wallet hold anything?" for a viem-based harness. The deliverable is the derived address plus native balances per chain, with the key never echoed.

## When to Use

- The user asks whether a self-custody key is connected, loaded, or funded ("sudah connect belum", "cek saldo wallet", "is my key wired up").
- The user asks whether an external data feed is wired up ("udah nyambung ke api opensea belum"), or a market/orderbook tool returns zeros.
- Before the first execution of a session, to confirm the signing lane actually has the key and gas.
- After editing an env file (RPC URL, caps), to confirm it still parses and the derived address is unchanged.

## Procedure

1. Locate the env file that holds the key. Look for `WALLET_PRIVATE_KEY` (also common: `PRIVATE_KEY`, `DEPLOYER_KEY`). Confirm the file exists before reading it; do not guess a path twice.
2. Report which variable names exist, never their values. `grep -oE '^[A-Z_]+' .env` lists key names without content; `sed -E 's/=(.{0,4}).*/=\1…<redacted>/'` gives redacted previews for config values you must reason about (RPC URLs, caps).
3. Derive the address and read balances:
   ```bash
   # copy scripts/wallet-probe.mjs into a dir where `viem` resolves, then:
   node .wallet-probe.mjs /path/to/.env
   ```
   The probe prints `{ok, hex_ok, address, balances, caps}` and never the key.
   When the JS toolchain is not usable in that directory, the dependency-free lane is `python3 scripts/derive-address.py --selftest` (proves the math against the private-key-1 vector), then `python3 scripts/derive-address.py <env-file> [VAR]`. It prints the address and nothing else.
4. Validate before deriving: prepend `0x` if absent, then require `^0x[0-9a-fA-F]{64}$`. On mismatch report `hex_ok:false` — never substitute a guessed address.
5. Report each chain separately with its own native unit (`ETH` on Base/Ethereum, `BNB` on BSC). Zero is a legitimate answer: say "connected but unfunded" rather than implying execution is possible.

## Pitfalls

- **`viem` does not export `privateKeyToAccount` from the package root.** Use `import { privateKeyToAccount } from 'viem/accounts'`; the bare import throws `does not provide an export named 'privateKeyToAccount'`.
- **Node resolves `node_modules` from the script's own directory.** A probe written to `/tmp` fails with `Cannot find package 'viem'`; copy it into the project that has viem installed (e.g. the harness dir) and run it there.
- **Do not assume `dotenv` is installed.** Parse the env file line by line (`^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$`, strip surrounding quotes); it removes a dependency and works everywhere.
- **One derivation path failing is not a verdict about the wallet.** viem, ethers, `eth_account` and a project's own CLI are four different ways to ask the same question; when the cheap one is missing, run the pure-python lane and keep the balance read unchanged. Report the address plus per-chain native balance regardless of which path produced it.
- **Never print, log, or paste the key** — not truncated, not masked beyond four characters of non-secret config. Secrets in tool output get replayed into transcripts.
- **Per-tx caps live in the same env file** (`MAX_ETH_PER_TX`, `MAX_BNB_PER_TX`, `DEX_SLIPPAGE_BPS`). Read the real values: documented defaults are upper bounds and the deployed file is usually stricter, so the cap rather than the balance rejects the tx.
- **Env edits do not hot-reload into a long-lived MCP/tsx server.** The process keeps the environment it started with; a changed RPC URL or cap needs a restart. Say so and ask before restarting.
- **A gateway cannot restart itself.** Killing the MCP child or the gateway from inside a gateway-run turn is refused by a lifecycle guard (and would kill the in-flight reply). Hand the user `hermes gateway restart` (or `systemctl --user restart hermes-gateway`) to run in their own shell, and leave the repo patched so the restart is all that is left.
- **Use the project-local binaries.** `./node_modules/.bin/tsx` and `./node_modules/.bin/tsc -p tsconfig.json --noEmit` inside the project directory; `npx` variants can be blocked by the lifecycle scan and single-file `tsc` misses project aliases. Run a probe from inside the project because module resolution starts at the script's own directory.

## RPC failures are endpoint failures, not chain failures

`HTTP request failed`, `An internal error was received`, or `Missing or invalid parameters` from a public endpoint means try another endpoint before concluding anything about the chain. Endpoints that answered for mainnet reads:

| Chain | Endpoints |
| :--- | :--- |
| ethereum | `https://ethereum-rpc.publicnode.com`, `https://eth.drpc.org`, `https://1rpc.io/eth`, `https://rpc.flashbots.net` |
| base | `https://mainnet.base.org` |
| bsc | `https://bsc-dataseed.bnbchain.org` |
| robinhood (chainId 4663, Arbitrum Orbit L2, ETH gas) | `https://rpc.mainnet.chain.robinhood.com` |

When the configured URL fails, back the file up (`cp .env .env.bak.$(date +%Y%m%d%H%M)`), swap in a working URL, rerun the probe, and tell the user a restart is still pending.

## API-key-backed data feeds (orderbook, marketplace, price APIs)

"Connected?" questions about a data API are answered with a live request, not by reading the env file. An env line can exist with an empty value, and a wrapper can silently swallow a failed call. Probe in this order and never report a feed as connected until step 3 passes:

1. **Key presence and true length** — print the name and `len(value)` only, never the value. Length `0` means unset even though the line is there. Check `.env.bak*` too: empty values are copied forward across backups, so a backup proves nothing.
2. **Live request with the key** — `curl -s -w '\nHTTP %{http_code}\n' -H "X-API-KEY: $KEY" "<endpoint>"`. A `401 Missing an API Key` means the key is empty or rejected. A `2xx` proves reachability, not key validity: OpenSea serves public reads with any non-empty `X-API-KEY`, so a fabricated 32-char key still returns live data. Only `401` and `429` are status-level verdicts; let step 3 decide whether the feed is genuinely wired.
3. **End to end through the actual tool** — call the tool the user cares about on a well-known asset and inspect the JSON `source`/provider field. Treat `source: "fallback"`, all-null, or all-zero output as "feed not connected", not as "market is empty".

Pitfalls:
- **A zeroed payload is usually a failed fetch, not an empty market.** Wrappers that fall back keep the schema intact, so `floorPrice: 0`, `bestBid: 0`, `top3: []` all look like valid data. Always read the provenance field before quoting numbers, and say "data unavailable" when the source is a fallback. Check the request before the credentials: the same fallback appears when the contract is not indexed on the chain you asked for (an Ethereum collection queried with `chain="base"`), and wrong-chain is indistinguishable from dead-feed in the payload.
- **Free-tier key auto-provisioning is rate limited per IP.** `429 ... Maximum N keys per day` means this host's quota is spent; do not retry in a loop. Report the limit, then offer the manual key path or a wait for the daily reset.
- **Re-verify through the tool after adding a key.** Long-lived MCP/tsx servers keep the environment they started with, so a rebuilt `.env` may need a restart before the tool itself sees the key. The durable fix is to re-read the env file inside the key getter on every call (parse `^OPENSEA_API_KEY=(.*)$` from disk, fall back to `process.env`), so key rotation never needs a restart; ship that change and only restarts for code changes remain.
- **Install the new key before revoking the old one.** Rotation order is: create new key, write it to `.env`, verify `2xx` plus a live tool call, then revoke the old key at the provider. Reversed, the feed goes dead in the gap and the failure looks like a config bug.
- **Separate feeds fail separately.** In one orderbook tool, NFT data can be dead while the token/DEX feed (different provider) is healthy. Scope the warning: "NFT preview unavailable, token preview still live" beats a blanket "API down".

### Who the key belongs to does not matter

Marketplace/data-API keys authenticate the request and set rate limits; they are **not** bound to a wallet. A key minted from the user's personal account, a colleague's account, or the anonymous instant-key endpoint reads the same public data. What actually authorizes a trade is the signature of the signing key in the harness env (`WALLET_PRIVATE_KEY`), and that wallet must own the asset and have approved the marketplace operator. So when the user asks whether a key from a different wallet will work: for reads, yes unconditionally; for execution, the key is irrelevant and the signed wallet is everything. One key cannot move funds.

Caveats to state: the account owner can revoke the key at any time, the key inherits that account's rate limits, and free instant keys expire (7 days at time of writing).

### Secrets the user pastes in chat

Never ask for the key, and when one arrives anyway: configure it, then tell the user plainly that Hermes cannot delete Discord messages, so the value stays in channel history and must be revoked provider-side. Offer the self-run alternative so the next rotation does not repeat the exposure:

```bash
python3 -c "import re,pathlib,sys;p=pathlib.Path.home()/'.hermes/web3-harness/.env';s=p.read_text();p.write_text(re.sub(r'^OPENSEA_API_KEY=.*$','OPENSEA_API_KEY='+sys.argv[1],s,flags=re.M))" '<new-key>' && chmod 600 ~/.hermes/web3-harness/.env
```

Re-runnable probe: `scripts/probe-feed-key.sh <env-file> [url]` prints HTTP status and key length only.

Provider-specific endpoints, key-location paths, and limits: `references/api-feed-triage.md`.

## Reporting shape

Label each execution lane separately (e.g. MPC/agentic wallet vs. self-custody key) with its address and balances. Two lanes usually mean two different addresses — never merge them into one list or attribute one lane's balance to the other. Close with the caveats that matter: unfunded balances, effective per-tx caps, and any pending restart.

# API feed triage: OpenSea v2 and similar

Reference for the "is this feed connected?" procedure in SKILL.md. Applies to the Pierre harness (`~/.hermes/web3-harness/`) and any viem wrapper that proxies a marketplace API.

## OpenSea v2

| Item | Value |
| :--- | :--- |
| Key env var | `OPENSEA_API_KEY` (in the harness `.env`) |
| Auth header | `X-API-KEY: <key>` |
| Key cache | `.opensea-key-cache.json` next to `.env`; `marketplace.ts` writes the key into `.env` too |
| Auto-provision | `POST https://api.opensea.io/api/v2/auth/keys` (free 7-day key) |
| Rate limit | key creation capped per IP per day; over the cap returns `429 Key creation rate limit exceeded` |
| Probe | `GET /api/v2/collections?limit=1`, or `GET /api/v2/chain/<chain>/account/<addr>/nfts?limit=1` |
| Chain mapping | `ethereum`, `base`, `bsc` (OpenSea chain slugs differ from the harness aliases; check `toOpenSeaChain()` in `marketplace.ts`) |

Health signal inside `inspect_market_orderbook` output: `source` is `opensea-v2` when live, `dexscreener` for ERC20/BEP20 token pairs, `fallback` when the fetch failed and the numbers are placeholders.

## Zero-or-error cheat sheet

- `HTTP 401 Missing an API Key` → key empty/rejected; check length, not just presence.
- `HTTP 429` on `/auth/keys` → daily IP quota spent; manual key or wait.
- `HTTP 200` but `source: "fallback"` → wrapper never sent the key (process env stale) or the collection/token is unknown to that provider; re-probe the API directly to tell the two apart.
- `HTTP 200` with a real payload but zero bids → genuinely no bids; this is the only case where zero means zero.

## Reporting template

Lead with the verdict (`belum nyambung` / `udah nyambung`), then the evidence as bullets: key length, HTTP status of the probe, rate-limit state if relevant, and the tool's `source` field. Close with the two concrete ways to fix it and ask which one the user wants. Keep the tone casual Indonesian and avoid em dashes.

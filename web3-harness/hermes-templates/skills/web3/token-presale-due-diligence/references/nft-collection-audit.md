# NFT Collection Buy-Side Audit (BSC / EVM)

The user drops a marketplace link to a young collection. The question is not "is the mint real" but "if I mint/buy, who buys it from me". Same verdict shape as the presale audit, different ledger.

## 1. Get the contract and the real supply

Marketplace pages obfuscate the address (`0xab6b...9759`). Grep the rendered HTML for full addresses, take the most frequent one:

```python
import re
html = js("document.documentElement.innerHTML")
addrs = {}
for a in re.findall(r'0x[a-fA-F0-9]{40}', html):
    addrs[a.lower()] = addrs.get(a.lower(), 0) + 1
print(sorted(addrs.items(), key=lambda x: -x[1])[:5])
```

Then `name()`, `symbol()`, `totalSupply()`, `totalMinted()`, `MAX_SUPPLY()`, `remaining()`, `owner()`, `ROYALTY_BPS()`, `baseURI()`. A collection can be hours old and already 50% minted; the page's "Items 0" is worth nothing.

## 2. Read the site's own agent-facing docs first

Unverified contract, no Sourcify match: fetch the machine-facing files before declaring it unauditable.

```
curl -s https://<site>/agent-brief.txt   # full selector table, error strings, events, constants, math
curl -s https://<site>/mcp.json          # addresses (contract, registry, market), bases, constants
```

These list every selector with its human name, which removes the 4byte round trip entirely. Cross-check each selector against the bytecode `63<selector>` constants so the brief is not aspirational.

## 3. The gate

Resolve the registry address from the contract (`REGISTRY()` or the brief), then `name()` it. A real third-party gate reads back as its issuer (`SPACE ID Agent ID` / `AI`), not as a contract deployed by the same wallet. Note that gates are usually checked at mint time only: sellers of listed pieces can hold zero ID afterwards.

## 4. The market contract is the exit, the marketplace is not

Read from the project's own escrow market (address in `mcp.json`, or `market()` on the NFT):

```
listedCount() totalVolume() totalSales() salesLast24h() volumeLast24h()
floorUsd8() floorWei() burnedBelowFloor() BURN_ADDRESS() paused() nft()
listedPage(uint256,uint256)   -> (uint256[] ids, uint96[] prices, address[] sellers)
offersOf(uint256) / offerCount(uint256)
```

Decode `listedPage` as three dynamic arrays: word 0/1/2 are byte offsets, each array = length then elements.

How to read the result:
- `totalSales == 0` with 20+ listings means nobody has ever paid for this art, whatever the floor says. That is the verdict line.
- Cheapest ask versus the contract's paid-mint price (`paidPriceWei()`): if the ask is at or below mint price, minting blind is strictly worse than buying a chosen piece.
- A floor rule that sends under-floor listings to the burn address ("burned below floor") means the project can delete cheap supply. Read `burnedBelowFloor()` before calling the floor real.
- Marketplace collection offers (Element's "best offer") live on the marketplace's own book and can sit below the project market's floor, so they are not executable there. Quote them as a bid, not as liquidity.

## 5. Is it actually a 404 token?

```python
# PancakeSwap V2 factory 0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73
sel('getPair(address,address)') + chip + wbnb     # 0x0 = no pool
# PancakeSwap V3 factory 0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865
sel('getPool(address,address,uint24)') + chip + wbnb + fee   # fee 100/500/2500/10000
```

`decimals()` reverting on a "404" token plus zero pools on both factories means the 404 in the name is branding. There is no AMM, so the piece is only worth what a marketplace bid says.

## 6. Free-mint difficulty ladders

Some free mints gate on proof of work. Read them rather than repeating the site copy:

```
weightNow() targetNow() epochSize() baseBits() topBits() weightAfter(uint256)
trialOpen() paused() MAX_MINTS_PER_WALLET() maxPerWallet() PIECES_PER_MINT()
```

`weightNow()` as bits N means one attempt in 2^N: 2^32 is about 0.8 s on a reference GPU (~5 GH/s), and each +10 bits is ~1000x. Convert to minutes on a GPU and days on a 4-thread CPU, then say plainly whether a normal user can mint at all. Ladder growth (`epochSize` pieces per step, up to `topBits`) means the window closes while supply fills.

## 7. Art and metadata durability

Fetch one token's `tokenURI`, then the JSON, then the image, and check the host:

```
curl -s -o /dev/null -w '%{http_code} %{content_type} %{size_download}\n' https://<host>/art/<id>.png
```

A 200 PNG on a project-owned domain (`art.<site>`, not ipfs/arweave) is fine art with mutable existence: the project can swap or drop it. Indexers that have not fetched it yet show "Content not available yet", which is an indexer gap, not proof the art is missing. Say which one it is.

## 8. Money on the table

`paidCount()` x `paidPriceWei()` versus the contract's native balance, plus the presence of `withdraw()` / `withdraw(address)` / `setPriceFeed()` / `setPaused()` / `transferOwnership()`. Paid revenue still sitting in an owner-controlled contract with unverified code is the concrete risk to quote, in native units and fiat.

## 9. Verdict arithmetic that landed

1,585 of 3,000 minted in 15 h. Free lane: 2 pieces, proof at 2^42 (about 15 min on an RTX 4090, days on CPU), rising to 2^52. Paid lane $2/piece = 0.002824 BNB at the on-chain BNB/USD of $708.24. Project market: 25 listings, cheapest 0.0029 BNB ($2.05), `totalVolume` and `totalSales` zero, zero offers per token. Element showed 0 items, no floor and a $0.79 best offer. Contract unverified, 0.48 BNB of paid revenue inside, `withdraw()` present, no DEX pool on V2 or V3.

Verdict: free lane only if the user holds the Agent ID and a GPU, never the paid lane, never the listings.

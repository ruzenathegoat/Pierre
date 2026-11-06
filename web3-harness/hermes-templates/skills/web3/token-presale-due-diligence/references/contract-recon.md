# Bare-address contract recon (what is this thing, and is it the project's?)

For "coba cek 0x..." with no site, no context, and an explorer that will not render. Order matters:
source first, selectors second, state third, lineage before any scam call.

## 1. Contract or EOA, in one batched probe

One Python `eth_call`-style batch per candidate RPC, never a `curl` shell loop per chain:
`eth_getCode` (non-`0x` = contract), `eth_getBalance`, `eth_getTransactionCount`.
A contract with nonce 1 and zero balance is a deployer-created contract, not a hot wallet.

Do not read the bytecode's first selector as an interface hint. Read the source.

## 2. Verified source: Sourcify v2, `?fields=all`

```
GET https://sourcify.dev/server/v2/contract/{chainId}/{address}?fields=all
```

Returns `sources` (full Solidity), `abi`, `metadata`, `deployment`, `signatures`, `match`.
`match` / `creationMatch` / `runtimeMatch` = `exact_match` is the strongest verification available and
is quotable without an explorer. `fields=compilation,match` is rejected with `invalid_parameter`;
use `fields=all` or no field selector at all.

The compat route is browser-only and answers a JSON notice telling you so, not a 404:
`/server/files/any/{chainId}/{address}`.

`deployment` carries `transactionHash`, `blockNumber`, `deployer`. **That is the deploy block and the
deployer address, with no archive node and no bisect**. It is the fix for the `eth_getCode` bisect that
converges on `latest` (or dies with `missing trie node`) on public BSC nodes.

Unverified contract? Fall through to `llms.txt` / `skill.md` / inline-script ABI, then selectors.

## 3. Selector discovery from the runtime bytecode

Walk the code for `0x63` (PUSH4) and collect the 4-byte operand. This over-collects (error selectors,
string fragments, jump-table noise): filter by resolving names, then keep only what a live `eth_call`
answers. Never report a collected constant as a function without a call behind it.

Resolve names one selector per request:

```
GET https://api.openchain.xyz/signature-database/v1/lookup?function=0x<selector>
-> result.function["0x<selector>"][].name
```

Pitfalls that cost real time:

- Repeating `function=` in one GET returns **HTTP 500**. Loop singles with a ~0.1s sleep.
- `4byte.directory/api/v1/signatures/?hex_signature=` can answer **403 Forbidden** from this host.
  Openchain is the working resolver; do not spend calls retrying 4byte.
- Selector computation needs real Keccak. `Crypto.Hash.keccak.new(digest_bits=256, data=sig.encode())`,
  not `hashlib.sha3_256`, and note `__import__("Crypto.Hash.keccak")` returns the module: call `.new()`
  on the module, there is no `module.keccak`.
- Filter the unknown leftovers before printing. A dispatch-shaped list of 59 selectors on an 8 kB
  contract typically resolves to ~35 real functions; the rest are `57600080`-style fragments.

## 4. Read every config getter, then the state

A recovered list showing `publicPrice/extraPrice/maxSupply/HARD_MAX/agentRegistry/feeRecipient/root`
means the whole rule set is readable without source. Decode strings by taking the ABI offset word and
length word rather than assuming a 32-byte short string.

## 5. The immutable-getter trap

When source is available, read it before interpreting any small-integer return. Public immutables and
`constant`s expose getters that look exactly like business functions:

- `freeAi()` returned `2`, `freeV2()` returned `4` — these are the *allowances*, not status codes.
  Read as "status 2/4" they invent mint states that do not exist.
- The same shape applies to `publicPrice()`, `extraPrice()`, `HARD_MAX()`, any `bytes32 root()`.

Rule: a getter whose name duplicates a constructor parameter is config. Only functions with side
semantics (`claimFree`, `mint`, `claimPublic`, `buyExtra`) are lanes, and only those get simulated.

## 6. Prove each lane per wallet by simulating the exact calldata

`eth_call` with `from` = the candidate wallet and `eth_estimateGas` from the same address settle
eligibility, branch and gas in two round trips, nothing broadcast.

Dynamic array argument with an empty proof is `offset(0x20) || length(0)`:

```
data = sel("claimFree(bytes32[])") + "0"*63+"2" + "0"*64
```

A revert selector (`0x7ca55c77` = `BadProof()`) on one wallet and a clean `0x...<id>` return on another
is the per-wallet verdict. Do not infer it from quota getters.

An empty merkle proof is a legitimate path on contracts that branch
`if (_isV2(proof)) return freeV2; if (isAiHolder(msg.sender)) return freeAi; return 0;` — an Agent-ID
holder claims with `[]` and gets the smaller allowance. Read the branch order in the source before
telling the user a proof is required.

## 7. Lineage before the scam verdict

An unlinked, unadvertised contract reusing a live project's name and `baseURI` is not automatically a
clone. Compare three hardcoded addresses against the project's own published contracts
(`/api/status`, `llms.txt`, `skill.md`):

- `deployer` from Sourcify's `deployment` field
- `feeRecipient()` / treasury / withdraw destination
- the gate registry (`agentRegistry()`, `identity()`, `gate()`)

Matching deployer *and* fee recipient *and* registry is lineage evidence, and it is what separates
"the project shipped an NFT the site has not linked yet" from "someone forked the branding".
State it as evidence, not proof: the contract can still be a bad deal.

## 8. Report skeleton for a bare address

1. Contract or EOA, verified or not (name the verification source and `match` value).
2. Deployer, deploy time in WIB, age, and whether deployer == fee recipient == the known project.
3. The rule set as the contract reads it: price per path, per-wallet caps, hard cap, supply progress.
4. Per-wallet eligibility for every lane the user could sign from, with the wallet's native balance.
5. Metadata / site mismatch: a `baseURI` that serves JSON while the mint page 404s, description text
   ("1 per wallet") that contradicts the contract (2 free for .ai), no market or floor yet.
6. Offer execution, do not execute.

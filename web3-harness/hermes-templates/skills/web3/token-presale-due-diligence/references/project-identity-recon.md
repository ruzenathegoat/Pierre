# Project Identity Recon (who is behind this token)

Answers "ada twitter / website nya gak?" for a token that is already in a watch list, an alert feed, or a bare address. The deliverable is a per-token row: verified site, verified social, unverified look-alike, or none — with the evidence that puts it in that bucket.

## Rule 1: a site is the project's only when its own HTML carries the token's contract address

A name match, a domain guess, and a search hit are not identity. Bind by address:

```bash
body=$(curl -sL -m 15 -A 'Mozilla/5.0' "https://$domain/" | tr -d '\000' | tr 'A-Z' 'a-z')
case "$body" in *"$addr"*) echo "$domain -> VERIFIED $sym";; *) echo "$domain -> not the same project";; esac
```

- Add `tr -d '\000'` before any grep on these pages: the HTML contains null bytes, so a plain `grep` prints `binary file matches` and looks like no result. Use `grep -aoiE` when grepping the raw stream directly.
- This single check is what demotes a plausible sibling. On one pass, `runinai.com` (symbol-identical, `@RuninAI_com` on its page) and several guessed domains did **not** contain the tracked address, so they were reported as "name collision, unverified" instead of being credited as the project's Twitter.
- Sites that only render the mint widget client-side still carry the address in inline script or a constants block, so the raw fetch usually settles it. If it genuinely does not, say the binding is unproven rather than falling back to the symbol.

## Rule 2: extract socials from the raw HTML, not from a markdown extract

```bash
curl -sL -m 20 -A 'Mozilla/5.0' "https://$domain/" | tr -d '\000' \
  | grep -aoiE '(https?://)?(www\.)?(x\.com|twitter\.com|t\.me|telegram\.me|discord\.gg|discord\.com)/[A-Za-z0-9_./-]*' | sort -u
```

A markdown/readability extraction of these one-page mint sites returns **zero** socials even when the page has one, because the links sit in inline markup the extractor drops. Also try the agent-facing text files at the root (`/skill.md`, `/agent.md`, `/llms.txt`, `/config.json`): a 200 there can be the SPA catch-all serving the index HTML, so check the body before believing it.

## Rule 3: presence/absence is the finding for anonymous clone mints

The Agent-ID fair-launch family on BSC ships one site per token, identical contract template (a few thousand free shares plus a paid cap, one price per share, per-token `identity()` wrapper), and frequently no social account at all. Establish the template from the contract constants, not from the name, then:

- No X/Telegram/Discord anywhere on the project's own page, which does carry the token address, means there is no official channel to verify — say that plainly; it is a verdict, not a search gap.
- Handles found only through third-party posts (aggregator pages, KOL threads) stay unverified. Do not promote one to "official" without the address-bound page.
- A page-verified handle (`@shibagentid` on the site that also carries the contract) is the only tier that may be presented as the project's own account.

## Reporting shape

Three groups, casual Indonesian, no em dashes, no tables: verified (with the evidence that it is address-bound), has a trace but unconfirmed (say what is missing), and nothing at all. Close with the template/identity sentence when the set is anonymous, since that is what the user is actually asking when they ask for a Twitter.

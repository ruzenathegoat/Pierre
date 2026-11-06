---
name: ai-api-plan-vetting
description: Use when vetting an AI API provider or coding-plan deal.
version: 1.0.0
author: hermes-curator
license: MIT
metadata:
  hermes:
    tags:
      - api-providers
      - pricing
      - due-diligence
      - subscriptions
    related_skills:
      - token-presale-due-diligence
      - hermes-agent
---

# Vetting AI API providers and subscriptions

Covers both shapes of the question: "is this free-API claim real?" (aggregators, gateways, free tiers) and "is this paid plan worth it?" (coding-plan subscriptions, model resellers).

## When to Use

Trigger on any "is this worth it / is this real" question about a third-party AI API, gateway, model aggregator, or coding-agent subscription, including:

- "X katanya bagi API gratis, bener ga?" — a free-tier or free-API claim to verify.
- "Y plan-nya worth it ga?" — a monthly subscription price to judge.
- "Cuma mau pakai model Z, bagus ga langganan?" — single-model fit for a plan's per-model allowance.
- Comparing a subscription against what the user already pays per-token, or deciding whether to route Hermes itself through a provider.

Not for: choosing between models on quality alone (no vendor/pricing claim to verify), or vetted infrastructure already in use. Once the verdict is "worth it" and the plan actually has to be wired into Hermes as a provider, hand off to `llm-subscription-provider-setup`.

## Always-on rules

- **Read the vendor's own docs, never a directory or review page.** Aggregator/AI-directory listings are paid placements and their "reviews" are affiliate copy. Go to `<site>/pricing` and `<site>/docs/plans/*`, plus any public model/price catalogue endpoint. If there are no independent reviews anywhere, say so instead of quoting the listing.
- **Probe the API before forming a view.** A live gateway and a marketing shell look identical on the landing page. Public catalogue endpoints and the shape of an unauthenticated error are evidence; the home page is not.
- **Never relay a headline multiplier as fact.** Separate the headline number ("up to $100 of credits") from the model-level allowance (per-model multipliers mean only boosted models reach it) and from the rolling pacing caps (what you can actually use per 5h / per week). All three together are the product.
- **Finish with a break-even in the user's own numbers.** Name the monthly spend figure above which the subscription wins and below which pay-as-you-go wins. A generic "seems decent" is not an answer.
- **Convert every provider time window to the user's local time (WIB, UTC+7).** Peak/off-peak windows and quota resets are only actionable once expressed in their clock and weekday.
- **Separate what you verified from what the vendor claims, and name what you could not verify.** Buy a real key only when the user decides to; until then say "untested" out loud.

## Procedure

1. **Recon (parallel).** Search the provider name plus `review`, and the model/plan name. In the same turn, pull the vendor's own pricing page and plan docs with web_extract. A search hit on the vendor's own page is data, not an endorsement.
2. **Probe the live API from the shell.** Public catalogue first, then error shape:
   ```bash
   curl -s -m 20 -w "\nHTTP %{http_code}\n" https://api.<vendor>/v1/text/models          # public catalogue: real model IDs, real prices
   curl -s -m 20 -w "\nHTTP %{http_code}\n" -X POST https://api.<vendor>/v1/chat/completions \
     -H 'Content-Type: application/json' -d '{"model":"<id>","messages":[{"role":"user","content":"hi"}]}'   # no key -> missing_api_key
   # repeat with a bogus key -> invalid_api_key
   ```
   Distinct, well-formed codes for missing vs invalid keys mean a real billing gateway. Parse the catalogue in python and list every free/zero-priced ID rather than eyeballing it.
3. **Build the value model from the docs, not the ad copy.** Per model: input/output/cache-read rates, per-model monthly allowance, rolling 5h and weekly caps, whether API access is included (the cheap tier usually excludes it), unstated add-ons (processing fee, per-hour cloud charges), and pass-through pricing changes (peak/off-peak, provider re-pricing).
4. **Measure the user's actual spend** instead of asking them to guess. Hermes records every model call it makes in `~/.hermes/state.db`, table `session_model_usage`, with token counts and an estimated USD cost. Run the recipes in `references/hermes-spend-audit.md`. Always state the window covered and that it excludes calls made outside Hermes.
5. **Compute the break-even.** Cost per day/week at the measured rate, projected to a month, against the plan price. Say which model allowance the user's traffic actually lands on: a plan can be excellent for one model and mediocre for another.
6. **Report** in the format below.

## Red flags to look for and name

- A "free tier" endpoint listing frontier models (Claude Opus, top-tier GPT) among its free IDs. Implausible generosity on the expensive models is bait for signups; do not present that list as proof of free access to those models.
- Domain age in the low months, WHOIS identity hidden, zero independent reviews, presence only in affiliate directories.
- "Free for a limited time" / deal-based allowances carrying the headline number. Flag it as movable and never let the recommendation depend on it.
- A pacing cap that makes the monthly figure unreachable in practice: the subscription is then the cap, not the credits.
- Unstated processing fee on top of the listed monthly price.
- Reseller routing: prompts leave for an unknown backend. Tell the user not to send sensitive content, that keys belong on trusted servers only, and that ZDR-style opt-ins exist only where the docs document them.

## Pitfalls

- **One shared pool, caps measured in credit value.** Mixing models changes how much a 5h/weekly window holds, so "14 credits per 5 hours" converts to different dollar amounts per model. Do not convert once and apply it to every model.
- **Quota reset timezones.** "Resets at 00:00 UTC" is 07:00 WIB; peak windows need the same conversion. Get this wrong and the saving tip you give is worthless.
- **Estimated cost is an estimate.** `estimated_cost_usd` comes from published model pricing and `cost_status` may read `estimated`. Call it approximate.
- **A heavy day is not a monthly run rate.** Say which it is. One busy setup day extrapolated to a month overstates the case; any spend-based verdict must state its sample size.
- **Directory trust scores flatter the site.** "70/100, likely safe" from a scanner means no malware hijack, not that the service is honest or durable.
- **"Free" tiers usually require a key.** Zero balance may be fine, but signup still gate-keeps the claim; say "real but limited" rather than "yes, free".

## Report format (this user)

- Casual Indonesian, no em dashes, bullets and short labeled lines (Discord has no tables).
- Order: what I verified myself (with the probe or the number) -> what the vendor claims -> red flags -> the money math -> break-even verdict -> one concrete next-step offer.
- Quantify red flags; do not just say "suspicious".
- Recommend the cheaper correct option when the user's spend is under the break-even, even though they asked about the paid plan. "Not worth it yet, here is when it becomes worth it" is a valid, expected answer.
- Compare on the model the user actually intends to use, not the plan's average model.

## References

- `references/hermes-spend-audit.md` — exact SQLite recipes for pulling real token and cost usage out of Hermes state, by model, day (WIB), and task type, plus cron LLM fires.

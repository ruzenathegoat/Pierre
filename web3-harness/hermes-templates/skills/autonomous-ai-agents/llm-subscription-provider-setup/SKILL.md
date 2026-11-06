---
name: llm-subscription-provider-setup
description: Use when wiring a subscription LLM into Hermes.
version: 1.0.0
author: hermes-curator
license: MIT
metadata:
  hermes:
    tags:
      - providers
      - oauth
      - subscriptions
      - claude
      - hermes-config
    related_skills:
      - hermes-agent
      - ai-api-plan-vetting
---

# Running Hermes on a consumer LLM subscription

Wiring a paid consumer plan (Claude Pro/Max/Ultra, ChatGPT/Codex, SuperGrok, Qwen, MiniMax) in as the model provider, so turns draw on the plan's allowance instead of pay-per-token API billing.

## When to Use

- "bisa pakai langganan X buat model Hermes ga?", "harus API key ga?"
- Any request to switch Hermes' main provider onto a subscription the user already pays for.

Executes the decision that `ai-api-plan-vetting` reaches. If the question is still "is this plan worth it", that skill answers first.

## Route selection (settle this before touching config)

| Plan | Route | What it consumes |
|---|---|---|
| Claude Max | built-in `anthropic` OAuth, or the official DirectSDK plugin | built-in OAuth: only purchased extra-usage credits (base allowance untouched); plugin: plan allowance |
| Claude Pro / Ultra | official `claude-subscription-directsdk` plugin only | plan allowance |
| ChatGPT / Codex | `openai-codex` OAuth | plan quota (semantics not documented) |
| SuperGrok / X Premium+ | `xai` browser OAuth | subscription quota |

- Pro cannot use the built-in Anthropic OAuth path at all. Ultra sits above Max, and the Claude Code CLI accepts Pro/Max/Ultra/Team/Enterprise, so for Ultra the plugin is the correct answer.
- Prefer the sanctioned plugin over letting built-in `anthropic` borrow Claude Code's stored credential. That borrow happens silently, and routing third-party-harness traffic through Free/Pro/Max credentials is disallowed by the vendor, so the user's account is the thing at risk. Name that risk when the built-in path comes up; do not present it as an equivalent option.
- Get the plan tier from the user and read the provider's own docs table. Never infer eligibility from the plan sounding expensive.

## Procedure (Claude subscription via DirectSDK)

1. **Check prerequisites on the box** (parallel): `node -v`, `npm -v`, `hermes --version` (needs >= 0.21.4), `which claude`.
2. **Install the CLI.** If `npm install -g` fails with EACCES under `/usr/lib/node_modules`, the npm prefix is system-owned. Fix: `npm config set prefix "$HOME/.npm-global"` then reinstall. This is the supported shape for the plugin, which searches `~/.npm-global/bin` on its own, no extra config needed. Also append `export PATH="$HOME/.npm-global/bin:$PATH"` to the shell rc, because the user runs the login command themselves.
3. **Install and enable the plugin:**
   ```sh
   hermes plugins install claude-subscription-directsdk
   hermes plugins enable claude-subscription-directsdk-experimental
   ```
   The installer ends on "installed but not enabled" even though the README says no `plugins.enabled` entry is needed. Enabling is a real step; skip it and the provider never registers.
4. **Hand the browser login to the user:** `claude auth login`. On a headless host it prints a URL to open on another machine, so it cannot be scripted past that point. Never run `claude setup-token` or export `CLAUDE_CODE_OAUTH_TOKEN` for this provider: the client path rejects inherited API-key, endpoint and cloud-backend overrides and has no silent HTTP fallback.
5. **Verify one real request through the new provider before repointing anything.** Run it explicitly (`hermes --provider claude-subscription-directsdk-experimental -m sonnet`) rather than by changing the default. A provider that is installed but unauthenticated looks perfectly healthy in `hermes plugins list`.
6. **Only then switch the default.** Set `model.provider` / `model.default` for real, and check whether the previous provider's `model.base_url` / `model.api_mode` still apply to the new one before leaving them in place.

## Pitfalls

- **Never repoint the live provider before auth is verified.** Every turn on the affected surface (gateway included) fails until the CLI is logged in, so install + enable + login + one verified request come first, and the user is told plainly why the switch is being held back.
- **A provider change lands on NEW sessions.** The live chat session keeps the model it started with; "it's still answering as the old model" right after a `hermes config set` is expected, not a broken switch.
- **The plugin adds no account-level overage cap.** Tell the user to disable extra usage in the account if they do not want overage billing; nothing in Hermes stops it.
- **Native list-price accounting is not a bill.** `total_cost_usd` / "estimated API list-price equivalent" in the logs is an estimate, never proof the subscription was charged. Do not present it as a cost.
- **Quota-bucket semantics are often undocumented.** Say "not documented" rather than asserting the plugin's usage does or does not share a bucket with the user's interactive CLI use.
- **Model aliases carry minimum CLI versions.** An older CLI answers `400 ... does not support this model`, so check the version floors in the reference and `claude update` before blaming Hermes.

## Reporting (this user)

- Casual Indonesian, no em dashes, bullets and short labeled lines (Discord renders no tables).
- Split the report by step and say per step who acts: anything needing a browser or a credential is his, the install/enable/config work is yours. Never ask for a password, token or one-time code in chat.
- Separate what you verified (with the version string or command output) from what the vendor claims. Do not narrate the tool calls.
- Close by offering the next step as a question, not by having already switched his live provider.

## References

- `references/claude-subscription-directsdk.md` — plugin depth: per-model CLI version floors, plugin settings and env knobs, update/pin behavior, the auth-override guard.

# claude-subscription-directsdk — operating notes

Provider id `claude-subscription-directsdk-experimental`, displayed as "Claude Subscription DirectSDK (Experimental)". Official Nous plugin, `kind: model-provider`, so the enable/disable state in `hermes plugins list` is the switch that registers or unregisters the provider.

It drives the unmodified official `claude` executable as a request-scoped model client over a loopback relay. Hermes keeps its own agent loop, tools, approvals and compaction. Everything authenticates through the CLI; the plugin holds no credentials and never reads or prints the CLI's credential files.

## CLI version floors (per alias)

An older CLI answers `400 Claude Code ... does not support this model`, which reads like a Hermes bug and is not one. Run `claude update` first.

- Each alias has its own minimum: `opus` is the lowest floor, `sonnet` higher, `haiku` the newest, and an access-gated model is qualified on the newest build of all.
- An access-gated model (organization-verified only) keeps its window and capabilities but is never appended to the picker, so only an account whose own picker offers it ever sees it. Pinning must never reveal a gated model to everyone.

Exact floors and the current model/plan table are vendor truth at `https://code.claude.com/docs/en/model-config` ("Extended context" for windows and which plans include them). Read it rather than trusting a cached version.

## Settings

- `plugins.entries.claude-subscription-directsdk-experimental.settings.claude_code_telemetry` (default true). Claude Code fetches feature flags and sends usage telemetry; the flags are what unlock newer models in the picker, so turning it off can shrink the picker to each family's current model.
  ```sh
  hermes config set plugins.entries.claude-subscription-directsdk-experimental.settings.claude_code_telemetry false
  ```
  Read on every spawn for the active profile, so it applies to the next request without a restart.
- `claude_config_dir` — per-profile login config directory, overriding the inherited `CLAUDE_CONFIG_DIR`.
- Whatever the settings, the plugin never lets the CLI auto-update itself or use its feedback upload path; a user's own opt-out env vars pass through untouched.

## Env knobs (optional, non-secret)

- `CLAUDE_SUBSCRIPTION_DIRECTSDK_COMMAND` — absolute path to the CLI when it is not on `PATH`. The plugin otherwise searches the usual install dirs (`~/.local/bin`, `~/.claude/local`, `~/bin`, `~/.npm-global/bin`, `~/.bun/bin`, `~/.volta/bin`, `/opt/homebrew/bin`, `/usr/local/bin`).
- `CLAUDE_SUBSCRIPTION_DIRECTSDK_CONFIG_DIR` — a separately CLI-managed auth directory.

The plugin checks for `claude` at every seam (load, `hermes model`, pickers, each request) and refuses with the install hint instead of half-working, so a missing CLI surfaces as a clean message rather than a traceback.

## Auth-override guard (fail-closed)

The normal client path refuses inherited API-key, custom Anthropic endpoint and cloud-backend overrides before spawning, and names the conflicting variables without printing their values. There is no silent API-key fallback. Practical consequence: when the user selects this provider, remove `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL`-style overrides from the launching environment instead of expecting Hermes to negotiate.

The low-level Python `Client(env=...)` injection bypasses that guard and is for controlled local fixtures only, not a supported auth path.

## Updating

`hermes plugins update claude-subscription-directsdk` follows the pin in the hermes-agent plugin catalog, not the plugin repo's `main`. Routing, context-window, thinking-policy or admission fixes merged upstream reach nobody until that pin moves. To track main instead, reinstall from the repo form (`hermes plugins install NousResearch/hermes-official-plugins#claude-subscription-directsdk`). A user reporting a window mismatch is a pin question before it is a code question — confirm the installed version/commit first.

## Context-window invariant worth knowing

Native Claude Code runs a plain model id inside a 200K window and only selects the 1M window for an explicit `[1m]` route. So a plain id must always resolve to a real window: if the resolver returns nothing for a plain id, core falls back to a family-substring guess, the two disagree, and the user sees "server rejected this request as too large" on a conversation the error itself calls small. Do not weaken that resolution when editing anything here.

---
name: read-shared-chat-links
description: Use when given a Gemini/ChatGPT share link to read.
---

# Reading shared AI-chat links and other JS-rendered pages

## Procedure
1. Try `web_extract` once. For Gemini share links (share.gemini.google/..., gemini.google.com/share/...) it returns only the page shell (nav, sign-in), and plain `curl` returns a large HTML with no chat text. Do not spend more calls on either.
2. Short links (share.gemini.google/<id>) redirect to `gemini.google.com/share/<hash>`; the hash shows up in the sign-in URL inside the `web_extract` shell, and opening that canonical URL in the browser is the reliable route. Open the link in the browser (`new_tab(url)`). The first `Runtime.evaluate` calls (page_info, js) can time out while the heavy page loads. Do not conclude it is broken: wait, take `capture_screenshot()` to confirm the chat rendered, then retry `js('document.body.innerText')` in a fresh browser_exec step.
   If calls keep timing out after `ensure_real_tab()` plus a re-open, do other work (e.g. a `curl` probe) for ~30-60s and retry `js` in a new browser_exec; the page finishes rendering in the background and the 100k+ char text then reads fine.
3. Dump the text to a file in the scratch dir (`~/.hermes/cache/scratch/`) from inside the browser step (use an explicit path via os.path.expanduser; the `workspace` variable may not be defined in every call). A long chat is 100k+ chars.
4. Read it with `read_file` in chunks. Math formulas come out one token per line, so filter with `awk 'length($0)>35'` and `cut -c1-400` to read prose only. Grep the user-turn marker (e.g. the page-language equivalent of "You said") with `grep -n` to list the user's questions and section boundaries.
5. Read the user's questions first, then the last answers (often the chat's own summary), then fill in the middle.

## Reuse the saved text
Keep the dumped file. If the user later changes direction (e.g. drops one strategy and returns to another), re-read the relevant sections from the saved file with `awk 'NR>=a && NR<=b'` instead of re-fetching the page.

## Compiling a blueprint
- Verify the chat's checkable claims (API hosts, endpoints, rate limits, fee models, program IDs) against official docs or the OpenAPI spec (`curl` the spec, list its paths) before putting them in the blueprint. Tag each claim [VERIFIED] / [GEMINI] (unchecked) / [TODO]. Chat-supplied weights and thresholds are usually invented; label them v0 hypotheses to calibrate on the user's own data.
- Third-party docs for the same product can disagree across versions (old vs new fee model); note both and mark which is live as TODO instead of hardcoding one.
- Revisions: `write_file` refuses to overwrite a file not fully read in the task, so write revisions to a new versioned filename (`..._v1.md`, `..._v2.md`) and say the old one is kept.
- End the blueprint with a numbered 'questions for the user' section (capital, signing/custody, chain priority, own heuristics, keys) so research input maps onto algorithm decisions.
- Speed-critical strategies (memecoin entry/exit) conflict with a 'user signs every tx' policy: surface that as an explicit decision (capped dedicated hot wallet vs alert-only) instead of assuming either.
- When asked for realistic profit, give scenario ranges with the fee/rent/slippage arithmetic shown, state it is an estimate, and say small capital is for proving the system, not for income.

## Output rules
- When the user wants a compiled blueprint: write a .md file and send it with `MEDIA:/abs/path`, plus a short Discord summary (no tables on Discord).
- Flag where the chat's content differs from the user's stated goal, and which numbers are unverified model output. Mark values that lost symbols in extraction with (?).
- Adapt to the user's stated constraints (cost, single agent, no fine-tuning) instead of copying the chat's recommendations.
- Casual Indonesian, no em dashes, for this user.

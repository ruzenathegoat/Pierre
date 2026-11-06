# Designing rich embeds for a webhook feed (alerts, radar, reports)

Use when the user asks for a "rich embed" / message.style design that will actually run in the server (not a throwaway JSON draft). "Design for webhook" means the result must be wired into whatever script or cron posts there.

## Procedure

1. Find the poster first. Grep `~/.hermes/scripts/` and `~/.hermes/cron/jobs.json` for the channel's webhook env file. An existing `build_embed()` is usually already there; redesign that function, keep its signature and the filter/dedupe/state logic untouched. Back the script up (`cp x.py x.py.bak-$(date +%s)`) before editing.
2. Match house style: the Pierre feeds use zero emoji, short caps labels, a one-line footer (`... report only`). Do not add emoji colour-coding in the first draft.
3. Build a draft, then ask only what is needed: which poster to wire, which channel. If the user already says "pasang langsung", just wire it.
4. Verify with a real post, not just a compile: monkeypatch `post_webhook` to print the HTTP status and run the script's own test mode (`--test-webhook` style, no state writes). 200 with multipart / 204 on plain JSON = delivered. Then tell the user which channel to look at, since reading history back via the bot API can be blocked from the host.

## Design rules learned from user feedback

- A stack of equal-weight text fields reads as a wall: users cannot tell what to read first. Put ONE hero fact in the title/description (status sentence + the key number), and push the numeric detail into a rendered image card.
- Unicode block-char progress bars (`\u2588\u2591`) render with mismatched glyph widths in Discord and look broken. Draw bars in an image instead.
- Keep headers sparse. Do not repeat the same label in the image header, the embed title, and the author line: the user asked for whitespace and said it read cleaner after the redundant tags were removed. Use author = brand name only, title = the subject (token symbol) only, and put the signal type (New Free Pool, Free Pool Low) once as a bold line at the top of the description. The card header carries only the subject; the accent colour already encodes signal type. Test-mode labels (e.g. RADAR SNAPSHOT) should not be rendered at all.
- When the user asks to confirm a change, re-run the script's test mode and report the HTTP status; they check the channel and send annotated screenshots, so name the channel and keep each tweak to exactly what they circled.
- Plain webhooks cannot carry buttons or select menus (components need an application-owned message). The interactive substitutes are masked links in the description (`[BscScan](url)`) and a clickable embed `url` on the title. Offer a bot-authored message only if the user wants real buttons.

## Current house style (supersedes the image-card approach below)

The user tried image cards, then asked for clean, minimalist, interactive embeds without images. Default to native embeds plus link buttons:

- Plain webhooks accept `components` only with `?with_components=true`, and only non-interactive ones: link buttons (type 2, style 5, `url`) in action rows, 5 per row. Action-triggering buttons (custom_id) need a bot-authored message. Components V2 (`flags: 32768`, `container`/`text display`/`separator`) also works on a plain webhook but cannot be mixed with `embeds`; offer it only if the user wants the message.style container look.
- Layout: author = brand only, title = subject (clickable `url`), description = 1-3 short lines with the one key number in bold, then one or two rows of 3 inline fields with short backticked values, a non-inline contract/address field, buttons for explorer links. Footer short; rely on the native `timestamp` instead of writing the time in the footer.
- One message per alert when buttons are involved: buttons attach to the message, so with several embeds in one post they would be ambiguous.
- If a 400 comes back with components, retry the same post without them so the alert is never lost.
- Shared kit: `~/.hermes/scripts/pierre_ui.py` (`post()` with `_buttons`, `link_rows`, `make_embed`) and `pierre_post.py` (LLM crons write a spec JSON with title/description/tone/fields/buttons, then run the script; it prints `posted <code>`).
- Non-alert channels (e.g. #welcome): edit the bot's own existing message in place (`PATCH /channels/<id>/messages/<mid>`, send `content:""` plus embeds/components) so a pinned message stays pinned and nothing duplicates; back up the old text first. Channel links go in as `<#id>` mentions inside fields (clickable) and as `https://discord.com/channels/<guild>/<channel>` link buttons. Bot history reads work from this host for channel GET /messages; the 40333 block applies to some other calls.

## Image-card technique (Pillow) — legacy, only if the user asks for image cards again

- Render a ~1000x420 PNG with Pillow (check `import PIL` first; fonts in `/usr/share/fonts/truetype/dejavu/`). Draw at 2x and downsample with LANCZOS for smooth edges. Layout: accent rail on the left, header row (symbol + signal label), one big hero number, full-width gradient progress bar, status chips (green/red dot + label), a row of small stat tiles.
- Keep the renderer in its own module next to the script (`radar_card.py`), import it lazily inside `build_embed` in a try/except, and fall back to a plain field-based embed on any failure so the alert never disappears because of a rendering problem. Pass the PNG bytes under a private key (`_card`) and strip it in the poster.
- Posting an image needs multipart: part `payload_json` (with the embed `image.url = attachment://cardN.png`) plus `files[N]` parts; one card per embed, up to 10 embeds per message. Keep the explicit `User-Agent` header the script already sets.
- Small brand icons (author `icon_url`, thumbnail): explorer sites (bscscan.com, etherscan) answer 403 to scripted fetches and to hotlinking, and brand-asset zips are blocked the same way. Fetch a favicon via `https://www.google.com/s2/favicons?domain=<site>&sz=128` (returns the real 48x48 PNG), check it by eye, save it under `~/.hermes/assets/`, and attach it to every post as a multipart file referenced by `attachment://<name>.png` (works for `author.icon_url`, not only `image`). In the poster, drop `icon_url` when the file is missing so the alert still sends. Say the icon is only 48px; offer to swap in a sharper logo the user provides. If the user means the webhook's sender avatar instead, that is the payload's `avatar_url`, a different field; ask when ambiguous.
- Look at the rendered PNG (vision) for clipping/overlap before wiring it in; render a preview with the module's `__main__` block.

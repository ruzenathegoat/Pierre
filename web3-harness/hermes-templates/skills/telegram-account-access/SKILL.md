---
name: telegram-account-access
description: Use when logging into or reading the user's Telegram.
---

# Telegram account access (user account, read-only)

Goal: give Pierre a persistent Telegram user session to read channels, without the OTP ever passing through chat.

## Rules
- Never ask for or accept the login code or 2FA password in chat. The user types them into a terminal prompt himself.
- Default to read-only (list dialogs, fetch messages). Do not send, delete, or mark-read unless he asks for that exact action.
- Reply in casual Indonesian, no em dashes.

## Pick the account type first
- A BotFather bot only sees chats it was added to (channels only as admin). It cannot see channels the user merely joined as a member. If the goal is reading his joined channels, say so and use a user-account session (below), not a bot token.
- Before starting any login, check whether one already exists: `ls ~/tgreader` and `hermes sessions list`. An interactive session may already have built `pierre.session`.

## Verify "is it connected" (read-only)
Do not judge by the browser: web.telegram.org in the agent browser stays on the login page even when the Telethon session works. Load `~/tgreader/.env` (never print the values), connect with the session file, and print `is_user_authorized()`, the account name, and counts from `iter_dialogs()` (channels vs groups). Report the counts and the session file permissions.

## Preferred path: Telethon session (not Telegram Web)
1. Venv: `uv venv ~/tgreader/.venv && uv pip install --python ~/tgreader/.venv/bin/python telethon` (system python has no pip; plain `python3 -m venv` gives a pip-less venv).
2. User gets api_id/api_hash himself at https://my.telegram.org (login there needs a code to his Telegram app) under "API development tools".
3. Write ~/tgreader/login.py: prompt api_id, `getpass` api_hash, `TelegramClient(session_path, id, hash).start(phone=...)`, save `.env` and chmod 600 on `.env` and `*.session`. The USER runs it in his own SSH terminal, so the OTP/2FA prompts stay out of chat.
4. After he confirms, build the reader script on the same session file. The session file equals full account access: never commit or share it; revoke via Telegram Settings > Devices.

## Why not the browser
- Telegram Web OTP cannot be supplied from a gateway chat session: `browser_vault_enter_code` returns `prompt_unavailable` there (no UI to prompt the user), and on the /a client it returns `no_code_field`. The code goes to his Telegram app, so Pierre cannot supply it legitimately. Do not drive the phone-number step in the browser first: submitting the number already sends him a live login code that then goes unused.
- If he insists on the browser route, it only works from an interactive CLI/desktop session where the vault prompt can reach him; offer Telethon as the cleaner option.
- QR login rotates about every 30s and the CLI user cannot view screenshots from the VPS browser, so scanning fails in practice. Only offer QR if he can view the image live.
- Long polling loops in browser_exec can drop the CDP connection; call `ensure_real_tab()` / reopen with `new_tab()` afterwards.

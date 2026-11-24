---
name: messaging
description: Send messages to configured platforms via `hermes send`.
version: 1.0.0
author: Hermes Agent + User
license: MIT
metadata:
  hermes:
    tags: [messaging, platforms, telegram, outbound, scripts, cron]
    category: social-media
---

# Messaging — outbound platform messages

Push a message to a configured messaging platform — Telegram, Discord, Slack,
Signal, etc. — from a shell script, cron job, or CI run using the
`hermes send` CLI. It reuses credentials already in `<HERMES_HOME>/.env` and
`config.yaml`, so no LLM, agent loop, or running gateway is needed for
bot-token platforms (Telegram, Discord, Slack, Signal, WhatsApp).

## When to use
- Delivering an alert, report, or run-summary to a chat from a script/cron.
- Shipping a generated file (report, chart) as a Telegram/Slack/Discord
  attachment.

## Workflow (in order)
1. **Confirm the platform is configured.** Look under
   `config.yaml` `platforms.<platform>` (e.g. Telegram `enabled: true` plus a
   `home_channel` with `chat_id`). A bot-token platform is live when
   `<HERMES_HOME>/.env` holds the token (`TELEGRAM_BOT_TOKEN`).
2. **Choose the target.** Form: `<platform>:<chat_id>` (e.g.
   `telegram:9238079416`) or bare `<platform>` for the home channel. List
   existing targets with `hermes send --list`.
3. **Compose the text.** Use the `message` positional argument, `--file PATH`
   for a text body, or pipe stdin: `echo "msg" | hermes send --to
   telegram:<chat_id>`.
4. **Send.** `hermes send --to <target> "<text>"`. Attach files with
   `MEDIA:<path>` embedded in the text; `[[as_document]] MEDIA:<path>` sends
   an image as an uncompressed file. Optional `--subject` prepends a header
   line.
5. **Check the result.** Exit 0 = sent; 1 = delivery/backend error
   (`hermes send: <error>` is printed); 2 = usage error. `--json` prints the
   raw `send_message_tool` result.

## Always-on rules
- Only text goes into the message body. Non-text files are `MEDIA:`
  attachments.
- Messaging tools respect the per-platform allowlist (`TELEGRAM_ALLOWED_USERS`
  / `allowed_chats`); a target outside the allowlist is refused.
- Never embed tokens, credentials, or internal paths in the message.
- Bot-token platforms (Telegram, Slack, Signal, Discord, WhatsApp) send with
  no running gateway; gateway/HTTP platforms that need delivery still route
  through the installed gateway.

## Pitfalls
- Telegram outbound send fails with `Forbidden: bot was blocked by the user`
  until the user taps the bot's **Start** button once. This is a user action,
  not a config error: unblock, then retry — the error always precedes success.
- `--list` may show "no channels discovered yet" even when the platform is
  configured; still send to `<platform>:<chat_id>`, which works directly.
- Sending to a chat whose id is a negative group id (e.g. `-100...`) targets a
  group, not a user.

## References
- `references/telegram.md` — Telegram home-channel shape, chat_id vs user_id,
  attachment rules.

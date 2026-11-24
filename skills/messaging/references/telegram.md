# Telegram (outbound send)

## Home channel (config.yaml)

```yaml
platforms:
  telegram:
    enabled: true
    home_channel:
      platform: telegram
      chat_id: '9238079416'
      name: Jaime Salazar Lahera
      user_id: '9238079416'
```

## Send targets

- `telegram:<chat_id>` — explicit chat (`9238079416` in this profile's case).
- `telegram` — home channel.
- `telegram:<chat_id>:<thread_id>` — a thread inside a chat.

## Allowlist (`TELEGRAM_ALLOWED_USERS` in `<HERMES_HOME>/.env`)

One numeric user id per line (`9238079416`). A send to a non-allowlisted chat
is refused at the gateway before the bot is touched.

## Attachments

- `MEDIA:<path>` — file referenced inside the message text; Telegram fetches
  it as an attachment.
- `[[as_document]] MEDIA:<path>` — image as an uncompressed document.

## Bot must be started

Outbound `sendMessage` returns `Forbidden: bot was blocked by the user`
until the user opens the bot and taps **Start** (sends `/start`).

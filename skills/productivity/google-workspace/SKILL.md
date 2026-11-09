---
name: google-workspace
description: "Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python."
version: 1.2.0
author: Nous Research
license: MIT
platforms: [linux, macos, windows]
required_credential_files:
  - path: google_token.json
    description: Google OAuth2 token (created by setup script)
  - path: google_client_secret.json
    description: Google OAuth2 client credentials (downloaded from Google Cloud Console)
metadata:
  hermes:
    tags: [Google, Gmail, Calendar, Drive, Sheets, Docs, Contacts, Email, OAuth]
    homepage: https://github.com/NousResearch/hermes-agent
    related_skills: [himalaya]
---

# Google Workspace

Gmail, Calendar, Drive, Contacts, Sheets, and Docs — through Hermes-managed OAuth and a thin CLI wrapper. When `gws` is installed, the skill uses it as the execution backend for broader Google Workspace coverage; otherwise it falls back to the bundled Python client implementation.

## Scope policy (this user)

Only authorize the Google services the user explicitly names. Pass `--services` to `setup.py` (Step 3) with exactly the services they need, e.g. `calendar,drive,sheets,docs` — never the `all` default, which grants Gmail, Contacts, and every Workspace scope. The token only ever carries the granted scopes; `AUTHENTICATED (partial)` with gmail/contacts absent is expected and must not be re-authorized away. Always confirm with the user before any Gmail activity, Drive share/delete, or Docs/Sheets write.

## References

- `references/gmail-search-syntax.md` — Gmail search operators (is:unread, from:, newer_than:, etc.)
- `references/daily-brief.md` — daily/morning brief procedure: schedule + conflicts + meeting prep + urgent mail from Gmail and Calendar. Load it when the user asks for a morning brief, meeting preparation, or "what's on my calendar and what email needs attention."
- `references/google-oauth-and-drive-search.md` — OAuth scope filter table, Google Cloud test-user step, Drive search query syntax, folder lifecycle, and calendar time rule.

## Scripts

- `scripts/setup.py` — OAuth2 setup (run once to authorize)
- `scripts/google_api.py` — compatibility wrapper CLI. It prefers `gws` for operations when available, while preserving Hermes' existing JSON output contract.

## First-Time Setup

The setup is fully non-interactive — you drive it step by step so it works
on CLI, Telegram, Discord, or any platform.

Run the setup script with Python from the Hermes environment, not an unrelated
system Python. `--install-deps` syncs Hermes' declared Google extra through PM;
after syncing, restart Hermes and rerun the OAuth command. If Hermes is not
importable, use `hermes setup` first rather than installing packages with pip.

Define a shorthand first:

```bash
GSETUP="python ${HERMES_HOME:-$HOME/.hermes}/skills/productivity/google-workspace/scripts/setup.py"
```

### Step 0: Check if already set up

```bash
$GSETUP --check
```

If it prints `AUTHENTICATED`, skip to Usage — setup is already done.

### Step 1: Triage — ask the user what they need

Before starting OAuth setup, ask the user TWO questions:

**Question 1: "What Google services do you need? Just email, or also
Calendar/Drive/Sheets/Docs?"**

- **Email only** → They don't need this skill at all. Use the `himalaya` skill
  instead — it works with a Gmail App Password (Settings → Security → App
  Passwords) and takes 2 minutes to set up. No Google Cloud project needed.
  Load the himalaya skill and follow its setup instructions.

- **Email + Calendar** → Continue with this skill, but use
  `--services email,calendar` during auth so the consent screen only asks for
  the scopes they actually need.

- **Calendar/Drive/Sheets/Docs only** → Continue with this skill and use a
  narrower `--services` set like `calendar,drive,sheets,docs`.

- **Full Workspace access** → Continue with this skill and use the default
  `all` service set.

**Question 2: "Does your Google account use Advanced Protection (hardware
security keys required to sign in)? If you're not sure, you probably don't
— it's something you would have explicitly enrolled in."**

- **No / Not sure** → Normal setup. Continue below.
- **Yes** → Their Workspace admin must add the OAuth client ID to the org's
  allowed apps list before Step 4 will work. Let them know upfront.

### Step 2: Create OAuth credentials (one-time, ~5 minutes)

Tell the user:

> You need a Google Cloud OAuth client. This is a one-time setup:
>
> 1. Create or select a project:
>    https://console.cloud.google.com/projectselector2/home/dashboard
2. Enable the required APIs from the API Library:
    https://console.cloud.google.com/apis/library
    Enable ONLY the APIs that match the services the user named in Step 1.
    Example: calendar + drive + sheets + docs needs Google Calendar API,
    Google Drive API, Google Sheets API, Google Docs API — do NOT enable
    Gmail/People unless email/Drive-sharing is actually needed.

See `references/google-oauth-and-drive-search.md` for the full scope
filter table.
> 3. Create the OAuth client here:
>    https://console.cloud.google.com/apis/credentials
>    Credentials → Create Credentials → OAuth 2.0 Client ID
> 4. Application type: "Desktop app" → Create
> 5. If the app is still in Testing, add the user's Google account as a test user here:
>    https://console.cloud.google.com/auth/audience
>    Audience → Test users → Add users
> 6. Download the JSON file and tell me the file path
>
> Important Hermes CLI note: if the file path starts with `/`, do NOT send only the bare path as its own message in the CLI, because it can be mistaken for a slash command. Send it in a sentence instead, like:
> `The JSON file path is: ~/Downloads/client_secret_....json`

Once they provide the path:

```bash
$GSETUP --client-secret /path/to/client_secret.json
```

If they paste the raw client ID / client secret values instead of a file path,
write a valid Desktop OAuth JSON file for them yourself, save it somewhere
explicit (for example `~/Downloads/hermes-google-client-secret.json`), then run
`--client-secret` against that file.

### Step 3: Get authorization URL

Use the service set chosen in Step 1. Examples:

```bash
$GSETUP --auth-url --services email,calendar --format json
$GSETUP --auth-url --services calendar,drive,sheets,docs --format json
$GSETUP --auth-url --services all --format json
```

This returns JSON with an `auth_url` field and also saves the exact URL to
`~/.hermes/google_oauth_last_url.txt`.

Agent rules for this step:
- Extract the `auth_url` field and send that exact URL to the user as a single line.
- Tell the user that the browser will likely fail on `http://localhost:1` after approval, and that this is expected.
- Tell them to copy the ENTIRE redirected URL from the browser address bar.
- If the user gets `Error 403: access_denied`, send them directly to `https://console.cloud.google.com/auth/audience` to add themselves as a test user.

### Step 4: Exchange the code

The user will paste back either a URL like `http://localhost:1/?code=4/0A...&scope=...`
or just the code string. Either works. The `--auth-url` step stores a temporary
pending OAuth session locally so `--auth-code` can complete the PKCE exchange
later, even on headless systems:

```bash
$GSETUP --auth-code "THE_URL_OR_CODE_THE_USER_PASTED" --format json
```

If `--auth-code` fails because the code expired, was already used, or came from
an older browser tab, it now returns a fresh `fresh_auth_url`. In that case,
immediately send the new URL to the user and have them retry with the newest
browser redirect only.

### Step 5: Verify

```bash
$GSETUP --check
```

Should print `AUTHENTICATED`. Setup is complete — token refreshes automatically from now on.

### Notes

- Token is stored at `~/.hermes/google_token.json` and auto-refreshes.
- Pending OAuth session state/verifier are stored temporarily at `~/.hermes/google_oauth_pending.json` until exchange completes.
- If `gws` is installed, `google_api.py` points it at the same `~/.hermes/google_token.json` credentials file. Users do not need to run a separate `gws auth login` flow.
- To revoke: `$GSETUP --revoke`

## Usage

All commands go through the API script. Set `GAPI` as a shorthand:

```bash
GAPI="python ${HERMES_HOME:-$HOME/.hermes}/skills/productivity/google-workspace/scripts/google_api.py"
```

### Autonomous execution (cron / background / fresh session)

When running `google_api.py` from an autonomous context — a scheduled cron job, a background terminal process, or any fresh session where `HERMES_HOME` is not exported — set `HERMES_HOME` to the Hermes home **before** invoking the script. The script resolves the token file as `$HERMES_HOME/google_token.json`, and falls back to `~/.hermes/google_token.json` when `HERMES_HOME` is unset or wrong, so a missing or wrong value puts the Drive/Docs call on the wrong credentials.

### Gmail

```bash
# Search (returns JSON array with id, from, subject, date, snippet)
$GAPI gmail search "is:unread" --max 10
$GAPI gmail search "from:boss@company.com newer_than:1d"
$GAPI gmail search "has:attachment filename:pdf newer_than:7d"

# Read full message (returns JSON with body text)
$GAPI gmail get MESSAGE_ID

# Send
$GAPI gmail send --to user@example.com --subject "Hello" --body "Message text"
$GAPI gmail send --to user@example.com --subject "Report" --body "<h1>Q4</h1><p>Details...</p>" --html
$GAPI gmail send --to user@example.com --subject "Hello" --from '"Research Agent" <user@example.com>' --body "Message text"

# Reply (automatically threads and sets In-Reply-To)
$GAPI gmail reply MESSAGE_ID --body "Thanks, that works for me."
$GAPI gmail reply MESSAGE_ID --from '"Support Bot" <user@example.com>' --body "Thanks"

# Labels
$GAPI gmail labels
$GAPI gmail modify MESSAGE_ID --add-labels LABEL_ID
$GAPI gmail modify MESSAGE_ID --remove-labels UNREAD
```

### Calendar

```bash
# List events (defaults to next 7 days)
$GAPI calendar list
$GAPI calendar list --start 2026-03-01T00:00:00Z --end 2026-03-07T23:59:59Z

# Create event (ISO 8601 with timezone required)
$GAPI calendar create --summary "Team Standup" --start 2026-03-01T10:00:00-06:00 --end 2026-03-01T10:30:00-06:00
$GAPI calendar create --summary "Lunch" --start 2026-03-01T12:00:00Z --end 2026-03-01T13:00:00Z --location "Cafe"
$GAPI calendar create --summary "Review" --start 2026-03-01T14:00:00Z --end 2026-03-01T15:00:00Z --attendees "alice@co.com,bob@co.com"

# Delete event
$GAPI calendar delete EVENT_ID
```

### Drive

```bash
# Search existing files
$GAPI drive search "quarterly report" --max 10
$GAPI drive search "mimeType='application/pdf'" --raw-query --max 5

# Get metadata for a single file
$GAPI drive get FILE_ID

# Upload a local file (auto-detects MIME type)
$GAPI drive upload /path/to/report.pdf
$GAPI drive upload /path/to/image.png --name "Logo.png" --parent FOLDER_ID

# Download (binary files download as-is; Google-native files export to a
# sensible default — Docs→pdf, Sheets→csv, Slides→pdf, Drawings→png)
$GAPI drive download FILE_ID
$GAPI drive download DOC_ID --output ~/doc.pdf
$GAPI drive download DOC_ID --export-mime text/plain --output ~/doc.txt

# Create a folder
$GAPI drive create-folder "Reports"
$GAPI drive create-folder "Q4" --parent FOLDER_ID

# Share
$GAPI drive share FILE_ID --email alice@example.com --role reader
$GAPI drive share FILE_ID --email alice@example.com --role writer --notify
$GAPI drive share FILE_ID --type anyone --role reader        # anyone with link
$GAPI drive share FILE_ID --type domain --domain example.com --role reader

# Delete — defaults to trash (reversible). Use --permanent to skip the trash.
$GAPI drive delete FILE_ID
$GAPI drive delete FILE_ID --permanent
```

### Contacts

```bash
$GAPI contacts list --max 20
```

### Sheets

```bash
# Create a new spreadsheet
$GAPI sheets create --title "Q4 Budget"
$GAPI sheets create --title "Inventory" --sheet-name "Stock"

# Read
$GAPI sheets get SHEET_ID "Sheet1!A1:D10"

# Write
$GAPI sheets update SHEET_ID "Sheet1!A1:B2" --values '[["Name","Score"],["Alice","95"]]'

# Append rows
$GAPI sheets append SHEET_ID "Sheet1!A:C" --values '[["new","row","data"]]'
```

### Google Sheets Datetime Handling (Key Findings)

- **Writing datetimes**: Always write datetime values as ISO 8601 strings (e.g., `2026-11-08 0:00:00`) via `sheets update` or `sheets append` with `USER_ENTERED`. Google Sheets parses these as datetime values and displays them in the cell's number format.
- **Never raw serials**: Do NOT write raw Excel serials (e.g., `46333.9475806932`) as cell values — Google Sheets does not recognize these as valid datetime cells. This is the #1 cause of the "Invalid: This value does not match the column type date time" error.
- **Number format is required**: The date picker only works when the cell/column is formatted as a date-time type via `google_api.py sheets batch_update` with `repeatCell` + `userEnteredFormat.numberFormat` (`type: DATE_TIME`, `format: M/D/YYYY H:MM:SS`). Writing the correct value is only half the work — the column must be formatted as date-time type.
- **Valid datetime formats**: ISO 8601 strings like `2026-11-07 22:34:50.681576+00:00` are parsed by Sheets as datetime values. The display format `M/D/YYYY H:MM:SS` (e.g., `11/8/2026 0:00:00`) is applied via number format.
- **Common error**: "Invalid: This value does not match the column type date time" means the column cells are not formatted as date-time type — apply the number format via `batch_update` with `repeatCell`.
- **Google API script**: Use the writable copy at `scripts/productivity/google-workspace/scripts/google_api.py` (the hermetic original at `/opt/hermes/skills/...` is root-owned and unwritable).

### Research Pass Script Configuration

The research script `scripts/research_pass.py` implements the Revolut Research & Holdings workflow:

- **Watchlist**: Reads active tickers (status = true) from the `Watchlist` tab. Columns: ticker, name, sector, notes, status, last_researched.
- **Research Log**: Appends rows to the `Research Log` tab with 5 columns: date, ticker, sentiment, rationale, sources.
- **Orders tab**: Columns are `ticker`, `side`, `recommended_price`, `recommended_timestamp`, `executed_amount`, `executed_timestamp`, `executed_price`, `position` (uuid4), `order_id` (uuid4). The `recommended_price` is the estimated price of the stock/ETF in EUR (output by the model). The `executed_amount`, `executed_timestamp`, and `executed_price` columns are left empty for manual entry by the user. Each new order gets a unique `position` (group BUY/SELL) and `order_id` (uuid4).
- **Sentiment handling**: Every active ticker MUST report a sentiment in the Research Log. If the model output cannot be parsed, write a fallback HOLD row with rationale "Model output could not be parsed. Please review manually." — never silently skip a ticker.
- **Telegram summary**: At the end of every run, the script sends a Telegram message to the home channel (9238079416) with a detailed summary: ticker, sentiment, timestamp, and one-line reason for each BUY/SELL recommendation. If only HOLD recommendations were generated, the message states that no BUY/SELL recommendations were generated.

### Order Writing
When writing a new order, generate a UUID4 for `position` (groups BUY/SELL orders) and a UUID4 for `order_id` (unique per order). The model returns `recommended_price` (current price of the stock/ETF in EUR, positive number). The `executed_amount`, `executed_timestamp`, and `executed_price` columns are left empty for manual entry by the user. Use ISO 8601 datetime strings (NOT serial numbers) for all timestamp columns.

```bash
# Read (a tabbed Doc returns a "tabs" array; single-tab and legacy Docs also return "body")
$GAPI docs get DOC_ID
$GAPI docs get DOC_ID --tab TAB_ID     # read one tab of a tabbed Doc

# Create a new Doc (optionally seeded with body text)
$GAPI docs create --title "Meeting Notes"
$GAPI docs create --title "Draft" --body "First paragraph..."

# Append text to the end of an existing Doc
$GAPI docs append DOC_ID --text "Additional content to append"
$GAPI docs append DOC_ID --tab TAB_ID --text "..."   # --tab required when the Doc has multiple tabs
```

## Output Format

All commands return JSON. Parse with `jq` or read directly. Key fields:

- **Gmail search**: `[{id, threadId, from, to, subject, date, snippet, labels}]`
- **Gmail get**: `{id, threadId, from, to, subject, date, labels, body}`
- **Gmail send/reply**: `{status: "sent", id, threadId}`
- **Calendar list**: `[{id, summary, start, end, location, description, htmlLink}]`
- **Calendar create**: `{status: "created", id, summary, htmlLink}`
- **Drive search**: `[{id, name, mimeType, modifiedTime, webViewLink}]`
- **Drive get**: `{id, name, mimeType, modifiedTime, size, webViewLink, parents, owners}`
- **Drive upload**: `{status: "uploaded", id, name, mimeType, webViewLink}`
- **Drive download**: `{status: "downloaded", id, name, path, mimeType}`
- **Drive create-folder**: `{status: "created", id, name, webViewLink}`
- **Drive share**: `{status: "shared", permissionId, fileId, role, type}`
- **Drive delete**: `{status: "trashed" | "deleted", fileId, permanent}`
- **Contacts list**: `[{name, emails: [...], phones: [...]}]`
- **Sheets get**: `[[cell, cell, ...], ...]`
- **Sheets create**: `{status: "created", spreadsheetId, title, spreadsheetUrl}`
- **Docs create**: `{status: "created", documentId, title, url}`
- **Docs append**: `{status: "appended", documentId, inserted_at, characters}`

## Rules

1. **Never send email, create/delete calendar events, delete Drive files, share files, or modify Docs/Sheets without confirming with the user first.** Show what will be done (recipients, file IDs, content, share role) and ask for approval. For `drive delete`, prefer the default trash (reversible) over `--permanent`.
2. **Check auth before first use** — run `setup.py --check`. If it fails, guide the user through setup.
3. **Use the Gmail search syntax reference** for complex queries — load it with `skill_view("google-workspace", file_path="references/gmail-search-syntax.md")`.
4. **Calendar times must include timezone** — always use ISO 8601 with offset (e.g., `2026-03-01T10:00:00-06:00`) or UTC (`Z`).
6. **Prefix user-created filenames with `[TEST] `** — when the user asks you to
   create a file, name it `[TEST] <name>` (e.g., `Test Document` → `[TEST] Test Document`),
   and keep the document title consistent with the filename.

## Pitfalls
- Verify the installed script's CLI before trusting a SKILL.md command example: run `python scripts/setup.py --help` (or `grep add_argument scripts/setup.py`) and confirm the flag is accepted before passing it — a documented flag a script rejects costs a full auth round trip.
- Creating a Google Doc inside a Drive folder: `docs create` can't set a parent or insert body text, so create the file with the Drive API (`mimeType=application/vnd.google-apps.document`, `parents=[FOLDER_ID]`) and populate it via `docs.documents().batchUpdate({insertText:{location:{index:1}, text}})`; then read text off `documentTab.body` — a fresh doc exposes no top-level `tabs[0].body`.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `NOT_AUTHENTICATED` | Run setup Steps 2-5 above |
| `REFRESH_FAILED` | Token revoked or expired — redo Steps 3-5 |
| `HttpError 403: Insufficient Permission` | Missing API scope — `$GSETUP --revoke` then redo Steps 3-5 |
| `AUTHENTICATED (partial)` or "Token missing scopes" | Partial auth is EXPECTED when `--services` limits the grant to a subset (e.g. `calendar,drive,sheets,docs` excludes gmail+contacts). The token only carries the granted scopes. Do NOT re-authorize to "fix" this. Only treat it as an error if you actually need a scope that is missing. |
| `HttpError 403: Access Not Configured` | API not enabled — user needs to enable it in Google Cloud Console |
| `ModuleNotFoundError` | Run `$GSETUP --install-deps` |
| Advanced Protection blocks auth | Workspace admin must allowlist the OAuth client ID |

## Revoking Access

```bash
$GSETUP --revoke
```

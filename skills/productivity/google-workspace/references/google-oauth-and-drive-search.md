# Google OAuth + Drive search reference

Operations-only depth for the google-workspace skill. Load when (a) authorizing,
(b) querying Drive, or (c) creating/fixing a folder structure.

## Scope filter table (`--services` values)

Each selector maps to OAuth scopes. The token only ever carries the granted
scopes. Use `--services` in the exact order the user names; never pass `all`
unless the user explicitly wants full Workspace access.

| `--services` value | OAuth scopes |
|---|---|
| `email` | gmail.readonly, gmail.send, gmail.modify |
| `calendar` | .../auth/calendar |
| `drive` | .../auth/drive |
| `sheets` | .../auth/spreadsheets |
| `docs` | .../auth/documents |
| `contacts` | .../auth/contacts.readonly |
| `all` | every scope above |

Documented earlier session result: `calendar,drive,sheets,docs` produces a
token with exactly those four scopes — no gmail, no contacts.

## OAuth flow (scripts/setup.py)

| Step | Command | Result |
|---|---|---|
| 0 | `setup.py --check` | `AUTHENTICATED` (exit 0) or `NOT_AUTHENTICATED` (exit 1) |
| 1 | `setup.py --client-secret /path/to/client_secret.json` | stores `google_client_secret.json` in Hermes home |
| 2 | `setup.py --auth-url --services <svc> --format json` | prints the auth URL; saves PKCE state to `google_oauth_pending.json` |
| 3 | `setup.py --auth-code <url-or-code> --format json` | exchanges and writes `google_token.json` |
| 4 | `setup.py --check` | final verification |

Token: `~/.hermes/google_token.json` (auto-refreshes). Pending session:
`~/.hermes/google_oauth_pending.json` (deleted after successful exchange).

## Google Cloud Console checklist (Step 2 recap)

1. Create/select a project → `console.cloud.google.com/projectselector2/home/dashboard`.
2. Enable only the matching APIs in `console.cloud.google.com/apis/library`.
3. Create OAuth 2.0 Client ID (Application type: "Desktop app") →
   `console.cloud.google.com/apis/credentials`.
4. If the app is in **Testing**, add the user as a test user →
   `console.cloud.google.com/auth/audience` → Audience → Test users → Add users.
5. Download the JSON file and pass its path to `--client-secret`.

If you get `Error 403: access_denied` during auth, the app is still in
Testing mode — redo step 4.

## Drive search query syntax (`google_api.py drive search`)

A plain (non-raw) query is wrapped internally in `fullText contains '…'`.
For any Drive API query, pass `--raw-query` so the string is sent as-is:

| Goal | Command |
|---|---|
| Plain text | `drive search "quarterly report"` |
| mimeType (raw) | `drive search "mimeType='application/vnd.google-apps.spreadsheet'" --raw-query` |
| By parent folder | `drive search "parents in 'FOLDER_ID'" --raw-query --max 20` |
| Trashed files | `drive search "trashed=true" --raw-query` |
| By name contains | `drive search "api" --raw-query` |

Drive API queries use `field = 'value'` (e.g. `mimeType='...'`). The wrapped
`fullText contains '...'` form breaks on anything containing an `=` or SQL-like
reserved tokens.

## Folder lifecycle (`google_api.py drive`)

- Create: `drive create-folder "Name"` → prints `{status, id, name, webViewLink}`.
- Nested: `drive create-folder "Name" --parent FOLDER_ID`.
- Delete defaults to trash (reversible). Use `--permanent` to skip the trash.
- Children listed via `drive search "parents in 'FOLDER_ID'" --raw-query`.

## Calendar time

Always ISO 8601 with an offset or `Z` (UTC): `2026-03-01T10:00:00-06:00` or
`2026-03-01T12:00:00Z`. Never pass naive local time.

---
name: notes-index
description: "Notes index: TOC of topics pointing to where each lives."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Notes, Index, Memory pointer, File naming]
---

# Notes Index

Maintain a table-of-contents index of the agent's notes. The index points to where each note topic lives so anything can be found without searching the whole vault.

## When to Use

Use this skill whenever the user asks you to:
- Create or maintain a table-of-contents index of the agent's notes.
- Point to where a note topic lives (a file, a block, or a memory).
- Name a file that is requested as an asset/resource (apply the `[TEST]` prefix only then).
- Pointer the index from memory.

## Always-on rules

- The `[TEST] ` filename prefix applies **only** to asset/resource files requested on request (e.g., `Test Document` -> `[TEST] Test Document`). It does **not** apply to system/internal files: the notes index, MEMORY.md, USER.md, or skill files.
- New topic notes live in `/opt/data/notes/` (one file per topic). Internal/system files live in `/opt/data/memories/` (`MEMORY.md` agent notes, `USER.md` user profile).
- The index is a markdown table with one row per topic and exactly three columns: `#`, `Topic`, `Lives at` (absolute path to the topic file).
- The index filename itself is a system file: keep it clean (no `[TEST]` prefix) and its own `Lives at` cell points to itself.
- Keep a one-line pointer in `/opt/data/memories/MEMORY.md` referencing the index path, so the index is reachable from memory.

## Procedure

1. Add a row to the index table: `#` = short id, `Topic` = topic name, `Lives at` = absolute path where that topic's file lives.
2. Verify every `Lives at` path is absolute and actually exists before committing it.
3. Add the one-line pointer in `/opt/data/memories/MEMORY.md` with the index path.
4. Re-read the index table and confirm the columns render one-per-header (`#`, `Topic`, `Lives at`) before finishing.

## Pitfalls

- A doubled leading pipe (`|| id | ...`) in a markdown table shifts the columns so the id lands under `Topic` instead of `#`. Keep the row starting with exactly `| id | Topic | Lives at |`.
- Do not apply the `[TEST]` prefix to system/internal files; that scope is reserved for asset/resource files only.
- The index is written to the file, not reconstructed from conversation history — treat `/opt/data/notes/NOTES INDEX.md` and MEMORY.md as the record of record for the notes index.

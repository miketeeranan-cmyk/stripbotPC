# stripbot

Stripchat viewer tracker. `stripchat_level_tracker.py` (Selenium) watches a
live viewer list and logs anyone above `LEVEL_THRESHOLD` to a Google Sheet
(`gspread` + `credentials.json`). `dashboard.py` is a Textual TUI wrapper
around the same core — pick a tab, hit Start, watch qualifying viewers land
in a table (`--demo` = fake data, no Selenium/Google needed).

- `python dashboard.py [--demo]` — TUI
- `python stripchat_level_tracker.py` — headless, same logic

## Wiki (`wiki/`, create if absent)

Sheet = raw append-only log (username/level/link/timestamp), never
hand-edited. Wiki = synthesis the sheet can't hold (trajectory, first/last
seen, patterns) — one file per notable user, `wiki/users/<username>.md`.
`index.md`: one line per page (catalog, keep current). `log.md`:
append-only, one line per ingest/query/maintenance action.

- **Ingest** new rows/log output → update/create user page(s), update
  `index.md`, append to `log.md`. Skip pages for single low-signal
  sightings — the sheet already has that row.
- **Query** → read `wiki/` first, not the sheet. Worth-keeping answers get
  filed back into the page.
- **Lint** → check for orphaned pages, stale claims, pages that just
  duplicate the sheet.

Do index/log bookkeeping without being asked; ask before deleting/
overwriting a wiki page.

## Working in this repo

- Selenium selectors (`USER_ROW_SELECTOR`, `USERNAME_SELECTOR`,
  `LEVEL_SELECTOR`) are brittle by design — match the live DOM. If tracking
  stops finding users, check these before assuming a logic bug.
- `credentials.json` is a Google service account key — never print, commit,
  or log its contents.
- Test dashboard changes with `python dashboard.py --demo` (no
  Chrome/Google needed, same UI code paths).

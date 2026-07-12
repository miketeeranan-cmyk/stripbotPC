# stripbotPC

Watches a live Stripchat viewer list and automatically logs users above a
level threshold to a Google Sheet. There are two ways to run it: a headless
CLI tracker (`stripchat_level_tracker.py`, built on Selenium) that does the
watching/logging on its own, and a local Flask web dashboard (`dashboard.py`)
that wraps the same tracking logic with a control panel — start/stop, pick a
sheet, adjust the threshold, and watch a live activity log — so you don't have
to touch the terminal once it's running.

## Requirements

- Python 3
- Google Chrome (for Selenium; not needed in `--demo` mode)
- Packages in `requirements.txt`: Flask, gspread, oauth2client, selenium,
  webdriver-manager, cryptography
- A Google service-account credentials file, named `credentials.json`, placed
  in the project root (gitignored — you supply your own, it's never committed)

## Setup

```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Then:

1. Drop your Google service-account `credentials.json` in the project root.
2. Run `python setup_users.py` once — this sets a master password and creates
   the dashboard login account(s), stored in a gitignored SQLite database
   (`users.db`). Run it again later (master-password-gated) to view passwords,
   reset a user, or change the master password.

## Running

- `python dashboard.py` — real mode; opens a browser dashboard at
  `127.0.0.1:5099`. Needs `credentials.json` and Chrome.
- `python dashboard.py --demo` — demo mode; fake data, no Chrome or Google
  Sheets required. Good for trying out the UI safely.
- `python stripchat_level_tracker.py` — headless CLI, same core tracking
  logic, no dashboard.

Double-click launchers (no terminal needed): `run_dashboard.command` and
`run_tracker.command` on macOS, `run_dashboard.bat` on Windows (dashboard
only — no CLI launcher there).

## Key config

The tunables live at the top of `stripchat_level_tracker.py` — the dashboard
reads them from there rather than duplicating them:

- `SHEET_NAME`, `LEVEL_THRESHOLD`, `CHECK_INTERVAL_SECONDS`
- CSS selectors used to scrape the viewer list: `USER_ROW_SELECTOR`,
  `USERNAME_SELECTOR`, `LEVEL_SELECTOR`, `POPUP_LINK_SELECTOR`

These selectors are brittle by design — if tracking stops finding users, check
here first, since a Stripchat page-structure change is the likely cause.

## Security notes

`credentials.json`, `users.db`, and `.flask_secret` are all gitignored. Never
commit, print, or share their contents — the dashboard login is gated by a
master password (`setup_users.py`) precisely so these stay private.

## Architecture

For the deeper writeup — state model, how `core` and `dashboard.py` share
logic, frontend structure, the login/session design — see
[`CONTEXT.md`](CONTEXT.md).

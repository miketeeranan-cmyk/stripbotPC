# stripbotPC — Architecture

Architecture reference for the Stripchat viewer tracker. For setup, running,
and requirements, see [`README.md`](README.md). `CLAUDE.md` points here for the
details below.

## Architecture (deep dive)

### `core` and shared logic

Selectors/tunables (`LEVEL_THRESHOLD`, `CHECK_INTERVAL_SECONDS`,
`*_SELECTOR`) live at module level in `stripchat_level_tracker.py`;
`dashboard.py` reads them off `core` instead of duplicating. Both entry
points' poll loops must call the same `core` decide/log functions so their
qualify/log logic never drifts apart.

### State model

`load_sheet_state()` caches the sheet once at startup as
`username -> {level, row}` plus the next free row (no per-cycle API calls).
`decide_action()`: new → log; strictly higher level (users can self-adjust
past 99) → delete old row, re-log at bottom, shift cached row numbers;
same/lower → skip, never overwritten.

Profile links only exist in a popup opened by clicking a username, so
`get_profile_link_via_popup` only runs for rows about to be logged. Blank
links retry on later cycles (`pending_link_fixups` in `dashboard.py`, capped
by `LINK_FIXUP_MAX_CYCLES`).

### `dashboard.py`

One global `AppState` (single `threading.RLock`) holds spreadsheet/worksheet,
threshold, driver, stop event, `logged_count`, monitoring flags, and a rolling
`log_entries` buffer (capped at `MAX_LOG_LINES`) — no per-row cache, since the
Sheet itself is the live data view. REST endpoints (`/api/connect`,
`/api/sheets`, `/api/select-sheet`, `/api/switch-sheet`, `/api/start`,
`/api/ready`, `/api/threshold`, `/api/stop`, `/api/quit`) trigger one-shot
actions on background threads; `GET /api/poll?since=<id>` is the one endpoint
the Dashboard screen polls (~1.2s) for everything live — status, uptime, sheet
name, threshold, logged count, new log entries, and `pending_prompt` (the
Ready-modal/browser-error gate). `core`'s own prints (`"Logged: ..."`,
retry/page-structure warnings) go to real stdout, not the browser — only
`_append_log_entry()` calls feed the dashboard's activity log.

Quit exits the whole process (`os._exit(0)`) — no graceful reload, so
relaunching means rerunning `python dashboard.py`. When launched via
`run_dashboard.command`, `DASHBOARD_TERMINAL_TTY` lets
`_close_launcher_terminal()` close that specific Terminal window after
shutdown, via a detached `osascript` process (must be detached or Terminal
prompts to confirm killing it).

### Frontend

`templates/index.html` is one page with sibling `<div>` "screens" (Language →
Connect → Dashboard) and modals (Ready / SwitchSheet / Threshold / Confirm)
toggled by class, driven by `static/js/app.js` (screen/modal manager, REST
calls, poll loop) and `static/js/i18n.js` (`t(lang, key, kwargs)` over
`window.__STRINGS__`, embedded as JSON at page load — server never localizes).
Polling only runs while the Dashboard screen is visible. Activity log is a
table (`#log-table`/`#log-output` tbody), one row per entry: Username / Level /
Link / Time — keep new log-worthy events to that shape, not free text.

### Login / session design

Every route (both real and `--demo` mode — same code paths) is gated by a
session login via `@app.before_request`, checking `session.get("user")`;
unauthenticated `/api/*` calls get a 401 JSON response, everything else
redirects to `/login`. Credentials live in a gitignored SQLite database,
`users.db`, with a `master(id=1, salt, check_token)` singleton row and a
`users(username, hash, enc)` table — the dashboard only ever reads each user's
`hash` (via `_load_users()`) to verify logins. `setup_users.py` is a
master-password-gated admin tool (never run automatically): first run sets a
master password plus the users; later runs require the master password (PBKDF2
→ Fernet key, verified by decrypting `master.check_token`) to view all
passwords, reset one user, or change the master password. `enc` is each
password encrypted under the master key so only the master can view it; needs
the `cryptography` lib (used only by `setup_users.py`, not the dashboard). A
one-time migration in `setup_users.py` imports a pre-database `users.json` into
`users.db` on first run after the switch, then renames it out of the way
(`.migrated`/`.old-format`). The session signing key lives in gitignored
`.flask_secret`, auto-generated on first run. Like `credentials.json`, the
master password, salt, Fernet tokens, hashes, and decrypted passwords may never
be printed/committed/logged or returned from `/api/poll`.

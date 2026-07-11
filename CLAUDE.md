# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Stripchat viewer tracker. `stripchat_level_tracker.py` (Selenium) watches a
live viewer list and logs users above `LEVEL_THRESHOLD` to a Google Sheet
(`gspread` + `credentials.json`) — the sheet itself is the live table of
results. `dashboard.py` is a local Flask *control panel* around it
(start/stop, sheet/threshold controls, activity log): imports the tracker
as `core`, drives it from background threads, opens the browser for you.
Both entry points must call through the same `core` decide/log functions —
don't let their poll loops' qualify/log logic drift apart.

## Running

```
python dashboard.py            # web dashboard, real mode — needs credentials.json + Chrome
python dashboard.py --demo     # web dashboard, demo mode — fake data, no Selenium/Google
python stripchat_level_tracker.py   # headless CLI, same core logic
```

- Dashboard serves on `127.0.0.1:5057` and auto-opens a browser tab.
- Double-click launchers: `run_tracker.command` (macOS, CLI), `run_dashboard.command`
  (macOS, dashboard), `run_dashboard.bat` (Windows, dashboard only — no CLI launcher there).
- Each `Bash` tool call is a fresh shell — `source venv/bin/activate` won't
  persist; use `venv/bin/python` directly or chain source+command in one call.
- Test dashboard changes with `--demo` first — same UI code paths, no Chrome/Sheets setup.

## Architecture

- **`core`** (`stripchat_level_tracker.py`): selectors/tunables
  (`LEVEL_THRESHOLD`, `CHECK_INTERVAL_SECONDS`, `*_SELECTOR`) live at module
  level; `dashboard.py` reads them off `core` instead of duplicating.
- **State model**: `load_sheet_state()` caches the sheet once at startup as
  `username -> {level, row}` + next free row (no per-cycle API calls).
  `decide_action()`: new → log; strictly higher level (users can self-adjust
  past 99) → delete old row, re-log at bottom, shift cached row numbers;
  same/lower → skip, never overwritten.
- **Profile links** only exist in a popup opened by clicking a username, so
  `get_profile_link_via_popup` only runs for rows about to be logged. Blank
  links retry on later cycles (`pending_link_fixups` in `dashboard.py`,
  capped by `LINK_FIXUP_MAX_CYCLES`).
- **`dashboard.py`**: one global `AppState` (one `threading.RLock`) holds
  spreadsheet/worksheet, threshold, driver, stop event, `logged_count`,
  monitoring flags, and a rolling `log_entries` buffer (capped at
  `MAX_LOG_LINES`) — no per-row cache, since the Sheet itself is the live
  data view. REST endpoints (`/api/connect`, `/api/sheets`,
  `/api/select-sheet`, `/api/switch-sheet`, `/api/start`, `/api/ready`,
  `/api/threshold`, `/api/stop`, `/api/quit`) trigger one-shot actions on
  background threads; `GET /api/poll?since=<id>` is the one endpoint the
  Dashboard screen polls (~1.2s) for everything live — status, uptime,
  sheet name, threshold, logged count, new log entries, and
  `pending_prompt` (the Ready-modal/browser-error gate). `core`'s own
  prints (`"Logged: ..."`, retry/page-structure warnings) still just go to
  real stdout, not mirrored into the browser — only `_append_log_entry()`
  calls feed the dashboard's activity log.
- **Frontend**: `templates/index.html` is one page with sibling `<div>`
  "screens" (Language → Connect → Dashboard) and modals (Ready /
  SwitchSheet / Threshold / Confirm) toggled by class, driven by
  `static/js/app.js` (screen/modal manager, REST calls, poll loop) and
  `static/js/i18n.js` (`t(lang, key, kwargs)` over `window.__STRINGS__`,
  embedded as JSON at page load — server never localizes). Polling only
  runs while the Dashboard screen is visible. Activity log is a table
  (`#log-table`/`#log-output` tbody), one row per entry: Username / Level /
  Link / Time — keep new log-worthy events to that shape, not free text.
- **Quit** exits the whole process (`os._exit(0)`) — no graceful reload, so
  relaunching means rerunning `python dashboard.py`. When launched via
  `run_dashboard.command`, `DASHBOARD_TERMINAL_TTY` lets
  `_close_launcher_terminal()` close that specific Terminal window after
  shutdown, via a detached `osascript` process (must be detached or
  Terminal prompts to confirm killing it).
- Selectors (`USER_ROW_SELECTOR`, `USERNAME_SELECTOR`, `LEVEL_SELECTOR`,
  `POPUP_LINK_SELECTOR`) are brittle by design — check first if tracking
  stops finding users.
- `credentials.json` is gitignored — never print/commit/log it, or anything
  appended to `log_entries`/returned from `/api/poll`.

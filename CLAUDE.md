# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Stripchat viewer tracker. `stripchat_level_tracker.py` (Selenium) watches a
live viewer list and logs users above `LEVEL_THRESHOLD` to a Google Sheet
(`gspread` + `credentials.json`). `dashboard.py` is a Textual TUI wrapper:
imports the tracker as `core`, drives it from `@work(thread=True)` workers,
and adds a stylized world-map "Globe" panel (`worldmap.py`). Both entry
points must call through the same `core` decision/logging functions — don't
let their poll loops' qualify/log logic drift apart.

## Running

```
python dashboard.py            # TUI, real mode — needs credentials.json + Chrome
python dashboard.py --demo     # TUI, demo mode — fake data, no Selenium/Google
python stripchat_level_tracker.py   # headless CLI, same core logic
```

- `run_tracker.command` (macOS) / `run_dashboard.bat` (Windows) are
  double-click launchers. Each `Bash` tool call is a fresh shell, so
  `source venv/bin/activate` won't persist across separate calls — use
  `venv/bin/python` directly, or chain source+command in one call.
- Test dashboard changes with `--demo` first — same UI code paths, no
  Chrome/Sheets setup needed.

## Architecture

- **`core`** (`stripchat_level_tracker.py`): selectors/tunables
  (`LEVEL_THRESHOLD`, `CHECK_INTERVAL_SECONDS`, `*_SELECTOR`) live at module
  level; `dashboard.py` reads them off `core` instead of duplicating.
- **State model**: `load_sheet_state()` caches the sheet once at startup as
  `username -> {level, row}` + next free row (avoids per-cycle API calls).
  `decide_action()`: new → log; strictly higher level (users can
  self-adjust past 99) → delete old row, re-log at bottom, shift cached row
  numbers; same/lower → skip, never overwritten.
- **Profile links** only exist in a popup opened by clicking a username, so
  `get_profile_link_via_popup` only runs for rows about to be logged. Blank
  links retry on later cycles (`pending_link_fixups` in `dashboard.py`,
  capped by `LINK_FIXUP_MAX_CYCLES`).
- **`dashboard.py`**: `LanguageScreen` → `ConnectScreen` → `DashboardScreen`,
  with `ReadyModal`/`SwitchSheetModal`/`ConfirmModal` pushed on top later.
  Background work runs in `@work(thread=True)` workers, marshaled back via
  `self.app.call_from_thread(...)`; `core`'s `print()` output feeds the
  Activity log via `_LineForwarder`.
- **i18n**: UI text lives in `STRINGS` (en/zh), looked up via
  `t(lang, key, **kwargs)` — add new text there, not as inline literals.
- **`worldmap.py`**: coarse, deterministic Unicode globe, not real
  cartography. `resolve_country()` matches the active sheet name to a
  country (exact → alias → fuzzy → substring) so the pin tracks whichever
  sheet is selected.
- Selectors (`USER_ROW_SELECTOR`, `USERNAME_SELECTOR`, `LEVEL_SELECTOR`,
  `POPUP_LINK_SELECTOR`) are brittle by design — check first if tracking
  stops finding users.
- `credentials.json` (Google service account key) is gitignored — never
  print, commit, or log its contents.

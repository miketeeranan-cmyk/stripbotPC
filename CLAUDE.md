# CLAUDE.md

Stripchat viewer tracker. `stripchat_level_tracker.py` (Selenium, this is
`core`) watches a live viewer list and logs users above `LEVEL_THRESHOLD` to a
Google Sheet (`gspread` + `credentials.json`). `dashboard.py` is a local Flask
control panel that imports the tracker as `core` and drives it from background
threads. **Both entry points must call the same `core` decide/log functions —
don't let their poll loops' qualify/log logic drift apart.**

Full architecture (state model, REST endpoints, frontend layout, login/DB
design) is in `CONTEXT.md` — read it when the task touches those areas.

## Running

```
python dashboard.py            # web dashboard, real mode — needs credentials.json + Chrome
python dashboard.py --demo     # web dashboard, demo mode — fake data, no Selenium/Google
python stripchat_level_tracker.py   # headless CLI, same core logic
```

- Dashboard serves on `127.0.0.1:5057` and auto-opens a browser tab.
- **Test dashboard changes with `--demo` first** — same UI code paths, no
  Chrome/Sheets setup.
- Each `Bash` call is a fresh shell — `source venv/bin/activate` won't persist;
  use `venv/bin/python` directly or chain source+command in one call.

## Gotchas

- **Selectors** (`USER_ROW_SELECTOR`, `USERNAME_SELECTOR`, `LEVEL_SELECTOR`,
  `POPUP_LINK_SELECTOR`, top of `stripchat_level_tracker.py`) are brittle by
  design — check first if tracking stops finding users.
- **Quit** calls `os._exit(0)` — no graceful reload; relaunch by rerunning
  `python dashboard.py`.
- **Secrets**: `credentials.json`, `users.db`, `.flask_secret` are gitignored.
  Never print/commit/log them or anything appended to `log_entries` /
  returned from `/api/poll` (master password, salt, Fernet tokens, hashes,
  decrypted passwords included).
- **Login gate**: every route (real and `--demo`) is gated by session login
  via `@app.before_request`. See `CONTEXT.md` for the `users.db` /
  `setup_users.py` design.

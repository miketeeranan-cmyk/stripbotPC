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

### Packaging & auto-update (desktop distribution)

The tracker is distributed to a non-technical single operator as a packaged
desktop app, not a hosted service — it needs a real, clickable Chrome window
and a long-lived background poll loop, which rules out serverless/PaaS
hosting (Vercel, Firebase, Cloud Functions, Cloud Run's free tier) at any
price point. Running only "while the operator is at their computer" (not
24/7) removes the need for a server entirely.

`get_app_data_dir()` (`stripchat_level_tracker.py`) is the seam: source runs
resolve to the repo dir unchanged (`BASE_DIR`); a frozen PyInstaller build
resolves to an OS-appropriate per-user writable directory
(`~/Library/Application Support/StripTracker` / `%APPDATA%\StripTracker`),
since a signed `.app` bundle is often read-only. `credentials.json`,
`users.db`, and `.flask_secret` all live there in a frozen build — you (admin)
still hand-provision `credentials.json`/`users.db` once, out-of-band, same as
today, just copied to that path instead of the repo root. `dashboard.py`'s own
`BASE_DIR` const is repurposed as the *read-only bundled resource* dir
(`sys._MEIPASS` when frozen) for `templates/`/`static/`, passed explicitly to
`Flask(...)` — do not conflate the two; app data must stay writable and
resource files must stay bundled.

Two separate PyInstaller builds (`packaging/build.py`):
- **`StripTrackerCore`** — `dashboard.py` + `templates/`/`static/`. This is
  the actual app; it's what gets replaced on every update.
- **`StripTracker`** (from `launcher.py`) — the thing the operator actually
  double-clicks. Installed once (by downloading it — see below); almost
  never rebuilt, since it isn't part of the auto-update payload itself.

`launcher.py` runs on every launch: check the repo's public
`GET /repos/.../releases/latest` API (unauthenticated — the repo is public
specifically so this needs no token), compare the release tag against
`current_version.txt` in the app-data dir, and if newer, download the
platform's zip asset (`StripTrackerCore-mac.zip` / `-windows.zip`), extract
into a fresh `versions/<tag>/` folder, flip `current_version.txt`, and launch
from there. Any failure (offline, GitHub unreachable) is swallowed — an
update check must never block a launch; only a genuine first-run-with-no-
internet (nothing installed at all) surfaces a message. There is no baked-in
`VERSION` file — the pushed git tag *is* the version, compared directly
against each release's `tag_name`.

`.github/workflows/release.yml`: pushing a tag matching `v*.*.*` builds both
`StripTrackerCore` *and* `StripTracker` on a `macos-latest`/`windows-latest`
matrix (`packaging/build.py --core`/`--launcher`, immediately followed by
`packaging/package_release.py --core`/`--launcher` for each — build+package
one target at a time, since PyInstaller's `--clean` can wipe the other
target's `dist/` output) and publishes all four zips as release assets. That
tag push is the entire deploy step: `StripTrackerCore-*.zip` is what
`launcher.py` silently pulls on the operator's next launch, and
`StripTracker-*.zip` is a plain download for a human to grab from the
Releases page in a browser and unzip themselves — no terminal, no Python, on
either OS — to get the launcher installed the first time.

**Packaging gotcha (macOS only):** a `.app` bundle contains symlinks (inside
`Python.framework`) that `shutil.make_archive`'s zip writer silently mangles
on extraction — the frozen interpreter fails at startup with
`ModuleNotFoundError: No module named '_struct'` (or `bad CPU type in
executable`, i.e. a corrupted Mach-O). `packaging/package_release.py` uses
macOS's own `ditto -c -k --keepParent` for the `.app` case instead (Windows
keeps `shutil.make_archive`, which is fine there — no symlinks in a onedir
folder of DLLs). Always test a **real relocated unzip** of any new mac build
(copy the zip elsewhere, unzip, run) before trusting it — a build that runs
fine from its own `dist/` folder can still be silently broken once zipped.

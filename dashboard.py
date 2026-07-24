"""
Stripchat Tracker Dashboard
---------------------------
A local Flask web control panel around stripchat_level_tracker.py.

Pick a Google Sheet tab, hit Start, and watch the activity log for
newly-qualifying viewers -- the sheet itself is the live table (open it in
another tab), this page is just start/stop/threshold/sheet control.

Run:
    python dashboard.py            (real mode — needs credentials.json + Chrome)
    python dashboard.py --demo     (demo mode — fake data, no setup required)

A browser tab to the dashboard opens automatically a moment after the
server starts.
"""

import json
import logging
import os
import random
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
from werkzeug.serving import WSGIRequestHandler

import stripchat_level_tracker as core

# Quiet the terminal: Werkzeug logs every request (including the dashboard's
# own ~1.2s /api/poll heartbeat) at INFO level by default, which floods a
# launcher's Terminal window with noise. Errors still get through.
logging.getLogger("werkzeug").setLevel(logging.ERROR)

DEMO = "--demo" in sys.argv
WINDOWED = getattr(sys, "frozen", False) and sys.platform == "win32"
HOST = "127.0.0.1"
PORT = 5099
MAX_LOG_LINES = 500
# Read-only bundled resources (templates/, static/): next to this file for a
# source run, but inside PyInstaller's extracted temp dir for a frozen build.
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
APP_DATA_DIR = core.get_app_data_dir()
USERS_DB = os.path.join(APP_DATA_DIR, "users.db")
SECRET_KEY_FILE = os.path.join(APP_DATA_DIR, ".flask_secret")

# --------------------------------------------------------------------------
# Login gate -- credentials live only as salted hashes in a gitignored
# SQLite database, users.db (set up via `python setup_users.py`, never
# committed/printed). The session signing key is likewise a gitignored,
# auto-generated file so restarting the dashboard doesn't invalidate every
# open session. Neither file's contents may ever be printed/logged or
# returned from /api/poll.
# --------------------------------------------------------------------------
def _load_users() -> dict:
    if not os.path.isfile(USERS_DB):
        raise SystemExit(
            "No users.db found -- the dashboard has no one to log in as.\n"
            "Run `python setup_users.py` first to create login credentials, "
            "then start the dashboard again."
        )
    conn = sqlite3.connect(USERS_DB)
    # The dashboard only needs the login hashes -- never the master password
    # or the encrypted copies (those are for setup_users.py's viewer).
    users = dict(conn.execute("SELECT username, hash FROM users").fetchall())
    conn.close()
    if not users:
        raise SystemExit(
            "users.db has no usable logins -- run `python setup_users.py` to "
            "(re)create login credentials, then start the dashboard again."
        )
    return users


def _load_or_create_secret_key() -> str:
    if os.path.isfile(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE) as f:
            key = f.read().strip()
        if key:
            return key
    key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, "w") as f:
        f.write(key)
    return key


try:
    USERS = _load_users()
except SystemExit as e:
    # A --windowed build has no console, so this message -- which is meant
    # to be read -- would otherwise vanish with the process. SystemExit
    # isn't caught by a normal try/except Exception (nor by sys.excepthook),
    # so it has to be handled right at this call site.
    if WINDOWED:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, str(e), "StripTracker", 0)
    raise

# --------------------------------------------------------------------------
# i18n — English / Chinese. Sent to the page as JSON; the client's
# static/js/i18n.js does the lookup/formatting. The server never localizes.
# --------------------------------------------------------------------------
STRINGS = {
    "app_title": {"en": "Stripchat User Tracker", "zh": "Stripchat 用户追踪器"},
    "connecting": {"en": "Connecting to Google Sheets...", "zh": "正在连接 Google Sheets..."},
    "demo_mode": {"en": "Demo mode — no Google account needed", "zh": "演示模式 — 无需 Google 账号"},
    "select_sheet": {"en": "Select a sheet/tab to log to:", "zh": "选择要记录到的工作表/标签页："},
    "connect_failed": {"en": "Couldn't connect to Google Sheets.", "zh": "无法连接到 Google Sheets。"},
    "retry": {"en": "Retry", "zh": "重试"},
    "login_title": {"en": "Log in on the browser window", "zh": "请在浏览器窗口中登录"},
    "login_body": {
        "en": "A Chrome window has opened. Log into Stripchat there and get "
        "your stream live, then continue.",
        "zh": "已打开一个 Chrome 窗口。请在其中登录 Stripchat 并开始直播，然后继续。",
    },
    "ready": {"en": "Ready!", "zh": "准备好了！"},
    "cancel": {"en": "Cancel", "zh": "取消"},
    "switch_sheet_title": {"en": "Switch sheet/tab", "zh": "切换工作表/标签页"},
    "switch_navigate_title": {"en": "Switch to \"{sheet}\"", "zh": "切换到 \"{sheet}\""},
    "switch_navigate_body": {
        "en": "Now targeting \"{sheet}\". Manually navigate to the right channel "
        "in the browser, then press Ready when set.",
        "zh": "已切换到 \"{sheet}\"。请在浏览器中手动切换到正确的频道，准备好后按“准备好了”。",
    },
    "confirm_title": {"en": "Are you sure?", "zh": "确定吗？"},
    "yes": {"en": "Yes", "zh": "是"},
    "no": {"en": "No", "zh": "否"},
    "quit_confirm": {
        "en": "Monitoring is running. Stop it and quit?",
        "zh": "监控正在运行。要停止并退出吗？",
    },
    "quit_confirm_idle": {"en": "Quit the dashboard?", "zh": "要退出仪表盘吗？"},
    "start_btn": {"en": "Start", "zh": "开始"},
    "stop_btn": {"en": "Stop", "zh": "停止"},
    "switch_sheet_btn": {"en": "Switch Sheet", "zh": "切换工作表"},
    "threshold_btn": {"en": "Set Threshold", "zh": "设置阈值"},
    "threshold_modal_title": {"en": "Set level threshold", "zh": "设置等级阈值"},
    "threshold_modal_body": {
        "en": "Only viewers at or above this level get logged. Takes effect "
        "on the next poll cycle -- already-logged users are unaffected.",
        "zh": "只有达到或高于此等级的观众才会被记录。将在下一次轮询时生效——"
        "已记录的用户不受影响。",
    },
    "invalid_threshold": {
        "en": "Enter a whole number of 1 or higher.",
        "zh": "请输入大于等于 1 的整数。",
    },
    "apply_btn": {"en": "Apply", "zh": "应用"},
    "quit_btn": {"en": "Quit", "zh": "退出"},
    "stat_logged": {"en": "Logged", "zh": "已记录"},
    "stat_threshold": {"en": "Threshold", "zh": "等级阈值"},
    "stat_poll": {"en": "Poll", "zh": "轮询间隔"},
    "stat_uptime": {"en": "Uptime", "zh": "运行时间"},
    "status_live": {"en": "LIVE", "zh": "运行中"},
    "status_busy": {"en": "CONNECTING…", "zh": "连接中…"},
    "status_idle": {"en": "STOPPED", "zh": "已停止"},
    "error_title": {"en": "Error", "zh": "错误"},
    "browser_start_failed": {
        "en": "Couldn't start the browser: {error}",
        "zh": "无法启动浏览器：{error}",
    },
    "lang_prompt": {"en": "Choose your language", "zh": "选择语言"},
    "lang_english": {"en": "English", "zh": "English"},
    "lang_chinese": {"en": "中文 (Chinese)", "zh": "中文 (Chinese)"},
    "lang_btn": {"en": "中文", "zh": "ENG"},
    "activity_log": {"en": "Activity Log", "zh": "活动日志"},
    "link_label": {"en": "Link", "zh": "链接"},
    "field_username": {"en": "Username", "zh": "用户名"},
    "field_level": {"en": "Level", "zh": "等级"},
    "field_time": {"en": "Time", "zh": "时间"},
    "prev_btn": {"en": "Prev", "zh": "上一页"},
    "next_btn": {"en": "Next", "zh": "下一页"},
    "page_of": {"en": "Page {x} of {y}", "zh": "第 {x} / {y} 页"},
}


# --------------------------------------------------------------------------
# Demo data generator (used with --demo, no Google/Selenium needed at all)
# --------------------------------------------------------------------------
_DEMO_ADJ = ["velvet", "crimson", "lunar", "quiet", "electric", "amber", "wild", "neon"]
_DEMO_NOUN = ["fox", "star", "raven", "wolf", "tiger", "storm", "comet", "lotus"]


def _demo_username():
    return f"{random.choice(_DEMO_ADJ)}_{random.choice(_DEMO_NOUN)}{random.randint(10, 999)}"


# --------------------------------------------------------------------------
# Global app state — one process, one operator. Guarded by `lock` since
# request handlers and the background monitor/demo-loop thread all touch it.
# The dashboard is a control panel, not a data view -- the Google Sheet is
# already the live table, so there's no per-row cache here, just a running
# count and a rolling activity-log buffer that the page polls.
# --------------------------------------------------------------------------
class AppState:
    def __init__(self):
        self.lock = threading.RLock()
        self.spreadsheet = None
        self.worksheet = None
        self.sheet_name = ""
        self.threshold = core.LEVEL_THRESHOLD
        self.driver = None
        self.stop_event = None
        self.monitoring = False
        self.starting = False
        self.stopping = False
        self.needs_channel_confirm = False
        self.start_time = None
        self.quit_after_stop = False
        # Keyed by sheet name, so switching sheets shows each sheet's own
        # running count/log instead of a single count shared across all of
        # them -- collected data for a sheet you're not currently on stays
        # tallied but hidden, and reappears when you switch back to it.
        self.sheet_counts = {}  # sheet_name -> int
        # sheet_name -> [{"id", "username", "level", "link", "timestamp"}, ...], newest last
        self.sheet_logs = {}
        self.log_next_id = 1
        # None, or {"type": "ready_login"|"ready_switch"|"browser_error", ...}
        self.pending_prompt = None
        self.close_timer = None  # threading.Timer pending a delayed quit, or None


state = AppState()

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = _load_or_create_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# No SESSION_COOKIE_SECURE -- this app is plain http on 127.0.0.1, never TLS.
# Flask's default "permanent" session lifetime is 31 days, which would
# silently log the operator out on its own -- stretch it out so a login
# only ever ends via explicit Logout, not the clock.
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=3650)


@app.before_request
def _require_login():
    """Gate every route behind a logged-in session, except the login page
    itself and static assets. API calls get a 401 JSON response (so app.js
    can redirect client-side); page loads get a straight redirect."""
    # Any request at all -- a page load, a poll tick -- is a sign the app is
    # still alive, so cancel a pending tab-close quit (see /api/tab-closing).
    # This is what lets a refresh's immediate re-GET of "/" cancel the timer
    # before it fires, while an actual tab close leaves nothing to cancel it.
    with state.lock:
        if state.close_timer:
            state.close_timer.cancel()
            state.close_timer = None
    if request.endpoint in ("login", "static"):
        return None
    if not session.get("user"):
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error="auth"), 401
        return redirect(url_for("login"))
    return None


def _append_log_entry(username: str, level: int, link: str) -> None:
    """Record one simple activity-log entry: timestamp, name, level, link.
    This is the dashboard's only user-facing log -- deliberately not a dump
    of core's print() diagnostics (those still go to the real terminal, same
    as before, just no longer mirrored into the browser)."""
    entry = {
        "id": None,
        "username": username,
        "level": level,
        "link": link or "",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    with state.lock:
        entry["id"] = state.log_next_id
        state.log_next_id += 1
        sheet_log = state.sheet_logs.setdefault(state.sheet_name, [])
        sheet_log.append(entry)
        if len(sheet_log) > MAX_LOG_LINES:
            state.sheet_logs[state.sheet_name] = sheet_log[-MAX_LOG_LINES:]


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template(
        "index.html",
        strings=STRINGS,
        demo=DEMO,
        threshold=core.LEVEL_THRESHOLD,
        poll_interval=core.CHECK_INTERVAL_SECONDS,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=False)

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    # Deliberately generic: never reveal whether the username or the
    # password was the wrong part.
    if username in USERS and check_password_hash(USERS[username], password):
        session["user"] = username
        session.permanent = True
        return redirect(url_for("index"))

    time.sleep(0.5)  # slow down brute-force guessing
    return render_template("login.html", error=True), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# REST: connect / sheet selection
# --------------------------------------------------------------------------
@app.route("/api/connect", methods=["POST"])
def api_connect():
    if DEMO:
        time.sleep(0.6)
        return jsonify(ok=True, sheets=["Demo Sheet A", "Demo Sheet B", "Test"])
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds_path = os.path.join(APP_DATA_DIR, "credentials.json")
        if not os.path.isfile(creds_path):
            return jsonify(
                ok=False,
                error=(
                    "No credentials.json found. Place your Google service-account "
                    f"JSON file at:\n{creds_path}\nthen try again."
                ),
            )
        creds = core.ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
        client = core.gspread.authorize(creds)
        spreadsheet = client.open_by_key(core.SHEET_ID)
        # Clean up any duplicate rows across every tab as soon as we connect --
        # before the operator has even picked a tab, let alone pressed Start.
        # load_sheet_state() also runs this at monitor start (covers tab
        # switches and the plain CLI), so this is a second, earlier pass.
        core.dedupe_sheet_rows(spreadsheet)
        names = [ws.title for ws in spreadsheet.worksheets()]
        with state.lock:
            state.spreadsheet = spreadsheet
        return jsonify(ok=True, sheets=names)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/api/sheets")
def api_sheets():
    if DEMO:
        return jsonify(ok=True, sheets=["Demo Sheet A", "Demo Sheet B", "Test"])
    with state.lock:
        spreadsheet = state.spreadsheet
    if spreadsheet is None:
        return jsonify(ok=False, error="not connected"), 400
    names = [ws.title for ws in spreadsheet.worksheets()]
    return jsonify(ok=True, sheets=names)


@app.route("/api/select-sheet", methods=["POST"])
def api_select_sheet():
    data = request.get_json(force=True) or {}
    sheet_name = str(data.get("sheet_name", ""))
    with state.lock:
        state.worksheet = None if DEMO else state.spreadsheet.worksheet(sheet_name)
        state.sheet_name = sheet_name
    return jsonify(ok=True)


@app.route("/api/switch-sheet", methods=["POST"])
def api_switch_sheet():
    data = request.get_json(force=True) or {}
    sheet_name = str(data.get("sheet_name", ""))
    with state.lock:
        if state.monitoring:
            return jsonify(ok=False, error="monitoring")
        state.worksheet = None if DEMO else state.spreadsheet.worksheet(sheet_name)
        state.sheet_name = sheet_name
        # A browser session already open, pointed at whatever channel matched
        # the old sheet -- don't let Start silently begin counting against
        # the new sheet until the user confirms via the Ready/Cancel gate.
        state.needs_channel_confirm = state.driver is not None
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# REST: start / ready / stop / threshold / quit
# --------------------------------------------------------------------------
@app.route("/api/start", methods=["POST"])
def api_start():
    with state.lock:
        if state.monitoring or state.starting:
            return jsonify(ok=False, error="already running")
        state.starting = True
        driver = state.driver
        needs_confirm = state.needs_channel_confirm
    if DEMO:
        _begin_monitoring()
    else:
        if driver is None:
            threading.Thread(target=_launch_browser, daemon=True).start()
        elif needs_confirm:
            with state.lock:
                state.pending_prompt = {"type": "ready_switch", "sheet_name": state.sheet_name}
        else:
            _begin_monitoring()
    return jsonify(ok=True)


def _launch_browser():
    try:
        driver = core.start_browser()
        with state.lock:
            state.driver = driver
            state.pending_prompt = {"type": "ready_login"}
    except Exception as e:
        with state.lock:
            state.starting = False
            state.pending_prompt = {"type": "browser_error", "message": str(e)}


@app.route("/api/ready", methods=["POST"])
def api_ready():
    data = request.get_json(force=True) or {}
    kind = data.get("kind")
    confirm = bool(data.get("confirm"))
    with state.lock:
        state.pending_prompt = None
    if kind == "browser_error":
        return jsonify(ok=True)
    if confirm:
        if kind == "ready_switch":
            with state.lock:
                state.needs_channel_confirm = False
        _begin_monitoring()
    else:
        if kind == "ready_login":
            with state.lock:
                driver = state.driver
                state.driver = None
                state.starting = False
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
        else:
            # Cancelling the "navigate to the right channel" gate: leave
            # needs_channel_confirm set so the next Start asks again -- only
            # a confirm clears it.
            with state.lock:
                state.starting = False
    return jsonify(ok=True)


def _begin_monitoring():
    with state.lock:
        state.monitoring = True
        state.starting = False
        state.stop_event = threading.Event()
        state.start_time = time.time()
        stop_event = state.stop_event
        driver = state.driver
        sheet = state.worksheet
    if DEMO:
        threading.Thread(target=_run_demo_loop, args=(stop_event,), daemon=True).start()
    else:
        threading.Thread(target=_run_monitor_loop, args=(driver, sheet, stop_event), daemon=True).start()


@app.route("/api/stop", methods=["POST"])
def api_stop():
    with state.lock:
        if not state.monitoring or not state.stop_event:
            return jsonify(ok=False, error="not monitoring")
        state.stopping = True
        state.stop_event.set()
    return jsonify(ok=True)


@app.route("/api/threshold", methods=["POST"])
def api_threshold():
    data = request.get_json(force=True) or {}
    raw = str(data.get("value", "")).strip()
    if not raw.isdigit() or int(raw) < 1:
        return jsonify(ok=False, error="invalid")
    value = int(raw)
    with state.lock:
        state.threshold = value
    return jsonify(ok=True, threshold=value)


def _quit_gracefully():
    """If monitoring is live, let the current loop iteration finish (same
    stop-then-quit path Stop uses) instead of yanking the driver out from
    under an in-flight Selenium call; otherwise quit immediately."""
    with state.lock:
        monitoring = state.monitoring
        if monitoring:
            state.quit_after_stop = True
            state.stopping = True
            stop_event = state.stop_event
    if monitoring:
        if stop_event:
            stop_event.set()
    else:
        threading.Thread(target=_quit_driver_and_exit, daemon=True).start()


@app.route("/api/quit", methods=["POST"])
def api_quit():
    _quit_gracefully()
    return jsonify(ok=True)


@app.route("/api/tab-closing", methods=["POST"])
def api_tab_closing():
    """Sent via navigator.sendBeacon on pagehide, which fires for both a
    real tab close and a page refresh -- there's no reliable way to tell
    those apart client-side. So this doesn't quit immediately: it arms a
    short delayed quit, and _require_login cancels it on the very next
    request. A refresh's own re-GET of "/" (or resumed polling) arrives
    well within the window and cancels it; an actual close leaves nothing
    to cancel it, so the delayed quit goes through."""
    with state.lock:
        if state.close_timer:
            state.close_timer.cancel()
        state.close_timer = threading.Timer(3.0, _quit_gracefully)
        state.close_timer.daemon = True
        state.close_timer.start()
    return jsonify(ok=True)


def _close_launcher_terminal():
    """If launched via run_dashboard.command, that script exports
    DASHBOARD_TERMINAL_TTY so Quit can close its own Terminal window
    afterwards. This runs as a fully detached process (new session, no
    controlling terminal) so it isn't itself counted as "still running" in
    that window -- otherwise Terminal prompts to confirm terminating it
    alongside bash. Force-killing the launcher shell (DASHBOARD_LAUNCHER_PID)
    first guarantees nothing is left "running" in that tab by the time the
    close request arrives -- without this, bash can still be alive when the
    delayed osascript below fires, which makes Terminal show a confirmation
    dialog instead of just closing the window."""
    if sys.platform != "darwin":
        return
    tty_path = os.environ.get("DASHBOARD_TERMINAL_TTY")
    if not tty_path:
        return
    launcher_pid = os.environ.get("DASHBOARD_LAUNCHER_PID")
    if launcher_pid and launcher_pid.isdigit():
        try:
            os.kill(int(launcher_pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    script = f'''
    delay 1
    tell application "Terminal"
        repeat with w in windows
            repeat with t in tabs of w
                if tty of t is "{tty_path}" then
                    close w
                end if
            end repeat
        end repeat
    end tell
    '''
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _quit_driver_and_exit():
    with state.lock:
        driver = state.driver
        state.driver = None
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    _close_launcher_terminal()
    time.sleep(0.3)  # let the HTTP response reach the browser before the process dies
    os._exit(0)


# --------------------------------------------------------------------------
# REST: the one endpoint the dashboard screen polls for everything live
# --------------------------------------------------------------------------
@app.route("/api/poll")
def api_poll():
    since = request.args.get("since", default=0, type=int)
    with state.lock:
        if state.monitoring and not state.stopping:
            status = "live"
        elif state.starting or state.stopping:
            status = "busy"
        else:
            status = "idle"
        current_log = state.sheet_logs.get(state.sheet_name, [])
        new_entries = [entry for entry in current_log if entry["id"] > since]
        next_since = current_log[-1]["id"] if current_log else since
        payload = dict(
            state=status,
            start_time=state.start_time,
            sheet_name=state.sheet_name,
            threshold=state.threshold,
            logged_count=state.sheet_counts.get(state.sheet_name, 0),
            demo=DEMO,
            monitoring=state.monitoring,
            prompt=state.pending_prompt,
            log=new_entries,
            next_since=next_since,
        )
    return jsonify(payload)


# --------------------------------------------------------------------------
# Monitor loops (background threads)
# --------------------------------------------------------------------------
def _record_new_user():
    with state.lock:
        state.sheet_counts[state.sheet_name] = state.sheet_counts.get(state.sheet_name, 0) + 1


def _on_monitoring_stopped():
    with state.lock:
        state.monitoring = False
        state.stopping = False
        # Deliberately keep state.driver around -- the browser session
        # persists across Stop so the next Start can reuse it.
        state.start_time = None
        quit_after_stop = state.quit_after_stop
    if quit_after_stop:
        _quit_driver_and_exit()


def _run_monitor_loop(driver, sheet, stop_event: threading.Event) -> None:
    try:
        logged_state, next_row, other_tab_usernames = core.load_sheet_state(sheet)
        pending_link_fixups = {}
        while not stop_event.is_set():
            # Re-read each cycle so a threshold change from the Threshold
            # modal applies to the very next poll without needing a restart.
            threshold = state.threshold
            try:
                rows = driver.find_elements(core.By.CSS_SELECTOR, core.USER_ROW_SELECTOR)
                for row in rows:
                    if stop_event.is_set():
                        break
                    try:
                        username, level = core.parse_user_row(row)

                        action = core.decide_action(
                            logged_state,
                            username,
                            level,
                            threshold=threshold,
                            other_tab_usernames=other_tab_usernames,
                        )

                        if action == "new":
                            profile_link = core.get_profile_link_via_popup(driver, row, username)
                            next_row = core.apply_new_user(
                                sheet, logged_state, next_row, username, level, profile_link
                            )
                            new_row = next_row - 1
                            _record_new_user()
                            _append_log_entry(username, level, profile_link)
                            if not profile_link:
                                pending_link_fixups[username] = (new_row, 0)

                        elif action == "update":
                            profile_link = core.get_profile_link_via_popup(driver, row, username)
                            old_row = logged_state[username]["row"]
                            next_row = core.apply_update_user(
                                sheet, logged_state, next_row, username, level, profile_link
                            )
                            _append_log_entry(username, level, profile_link)
                            for uname, (row_number, cycles_tried) in list(pending_link_fixups.items()):
                                if row_number > old_row:
                                    pending_link_fixups[uname] = (row_number - 1, cycles_tried)
                            pending_link_fixups.pop(username, None)

                        elif username in pending_link_fixups:
                            row_number, cycles_tried = pending_link_fixups[username]
                            profile_link = core.get_profile_link_via_popup(driver, row, username)
                            if profile_link:
                                sheet.update(range_name=f"E{row_number}", values=[[profile_link]])
                                del pending_link_fixups[username]
                            else:
                                cycles_tried += 1
                                if cycles_tried >= core.LINK_FIXUP_MAX_CYCLES:
                                    del pending_link_fixups[username]
                                else:
                                    pending_link_fixups[username] = (row_number, cycles_tried)
                    except Exception:
                        continue
            except Exception as e:
                print(f"Page structure issue, retrying: {e}")

            stop_event.wait(core.CHECK_INTERVAL_SECONDS)
    finally:
        # Deliberately not quitting the driver here -- the browser session
        # stays open across Stop so the next Start reuses it. It's only
        # closed on app Quit.
        _on_monitoring_stopped()


def _run_demo_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        wait = random.uniform(2, 4.5)
        if stop_event.wait(wait):
            break
        username = _demo_username()
        level = random.randint(state.threshold, state.threshold + 40)
        link = f"https://stripchat.com/{username}"
        _append_log_entry(username, level, link)
        with state.lock:
            state.sheet_counts[state.sheet_name] = state.sheet_counts.get(state.sheet_name, 0) + 1
    _on_monitoring_stopped()


class _NoReverseDNSHandler(WSGIRequestHandler):
    def address_string(self):
        # Base implementation does a reverse-DNS lookup (getfqdn) on every
        # request just to build the access-log line -- on a machine with
        # slow/unreachable DNS (VPN, corporate resolver) that can stall
        # every request indefinitely, making the whole app look hung. We
        # never use the client hostname, so skip the lookup entirely.
        return self.client_address[0]


def _serve():
    try:
        app.run(
            host=HOST,
            port=PORT,
            debug=False,
            use_reloader=False,
            threaded=WINDOWED,
            request_handler=_NoReverseDNSHandler,
        )
    except Exception:
        # This runs in a daemon thread -- an uncaught exception here would
        # otherwise vanish with no trace (no console in --windowed builds,
        # and this thread is outside the try/except around window creation),
        # leaving the app looking like a plain blank window with no clue why.
        if WINDOWED:
            import traceback

            try:
                with open(os.path.join(APP_DATA_DIR, "crash.log"), "a") as f:
                    f.write(f"\n--- {datetime.now().isoformat()} (server thread) ---\n")
                    f.write(traceback.format_exc())
            except Exception:
                pass
        else:
            raise


def _wait_for_server(timeout=15):
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection((HOST, PORT), timeout=0.25).close()
            return
        except OSError:
            time.sleep(0.1)


if __name__ == "__main__":
    if WINDOWED:
        # --windowed has no console, so any exception here would otherwise
        # vanish silently (the window just never appears). Log it to
        # app-data instead so a failure is diagnosable after the fact.
        try:
            import webview  # only ever imported on the frozen Windows build

            threading.Thread(target=_serve, daemon=True).start()
            _wait_for_server()
            window = webview.create_window("StripTracker", f"http://{HOST}:{PORT}")
            # *_ tolerates whatever args this pywebview version's closed event passes
            window.events.closed += lambda *_: _quit_gracefully()
            # pywebview defaults to private_mode=True (cookies/local storage
            # wiped on every close, like an incognito window) -- that alone
            # was silently overriding the Flask session's own persistence.
            # storage_path is pinned into APP_DATA_DIR (not the frozen exe's
            # own folder) so login also survives auto-update swapping in a
            # fresh versions/<tag>/ folder.
            webview.start(
                private_mode=False,
                storage_path=os.path.join(APP_DATA_DIR, "webview_data"),
            )
        except Exception:
            import traceback

            tb = traceback.format_exc()
            try:
                with open(os.path.join(APP_DATA_DIR, "crash.log"), "a") as f:
                    f.write(f"\n--- {datetime.now().isoformat()} ---\n")
                    f.write(tb)
            except Exception:
                pass
            # If a console is attached (temporary diagnostic build), print +
            # pause so the window doesn't vanish before it can be read. In a
            # normal --windowed build there's no stdin, so input() fails
            # immediately and this is a no-op.
            try:
                print(tb)
                input("StripTracker crashed -- press Enter to close this window...")
            except Exception:
                pass
        os._exit(0)  # no graceful shutdown, same as Quit
    else:
        threading.Thread(
            target=lambda: (_wait_for_server(), webbrowser.open(f"http://{HOST}:{PORT}")),
            daemon=True,
        ).start()
        _serve()

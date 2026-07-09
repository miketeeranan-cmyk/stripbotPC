"""
Stripchat Tracker Dashboard
---------------------------
A terminal UI wrapper around stripchat_level_tracker.py.

Pick a Google Sheet tab, hit Start, and watch newly-qualifying viewers land
in the table (and as a toast popup) in real time, without ever leaving the
terminal.

Run:
    python dashboard.py            (real mode — needs credentials.json + Chrome)
    python dashboard.py --demo     (demo mode — fake data, no setup required)
"""

import sys
import threading
import time
from datetime import datetime

from rich.text import Text

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.render import measure
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    LoadingIndicator,
    OptionList,
    RichLog,
    Static,
)
from textual.widgets.option_list import Option

import stripchat_level_tracker as core
import worldmap

DEMO = "--demo" in sys.argv


# --------------------------------------------------------------------------
# i18n — English / Chinese. `t(lang, key, **kw)` looks up STRINGS[key][lang]
# and `.format(**kw)`s it. Screens read the active language off `self.app.lang`.
# --------------------------------------------------------------------------
STRINGS = {
    "app_title": {"en": "◆ STRIPCHAT TRACKER", "zh": "◆ STRIPCHAT 追踪器"},
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
    "start_btn": {"en": "▶  Start", "zh": "▶  开始"},
    "stop_btn": {"en": "■  Stop", "zh": "■  停止"},
    "switch_sheet_btn": {"en": "Switch Sheet", "zh": "切换工作表"},
    "quit_btn": {"en": "Quit", "zh": "退出"},
    "stat_logged": {"en": "Logged", "zh": "已记录"},
    "stat_threshold": {"en": "Threshold", "zh": "等级阈值"},
    "stat_poll": {"en": "Poll", "zh": "轮询间隔"},
    "stat_uptime": {"en": "Uptime", "zh": "运行时间"},
    "status_live": {"en": "●  LIVE", "zh": "●  运行中"},
    "status_busy": {"en": "●  CONNECTING…", "zh": "●  连接中…"},
    "status_idle": {"en": "○  STOPPED", "zh": "○  已停止"},
    "globe_title": {"en": "🌐  GLOBE", "zh": "🌐  地球"},
    "col_time": {"en": "Time", "zh": "时间"},
    "col_username": {"en": "Username", "zh": "用户名"},
    "col_level": {"en": "Level", "zh": "等级"},
    "col_row": {"en": "Row", "zh": "行"},
    "col_link": {"en": "Link", "zh": "链接"},
    "link_open": {"en": "open", "zh": "打开"},
    "error_title": {"en": "Error", "zh": "错误"},
    "browser_start_failed": {
        "en": "Couldn't start the browser: {error}",
        "zh": "无法启动浏览器：{error}",
    },
    "bind_start": {"en": "Start", "zh": "开始"},
    "bind_stop": {"en": "Stop", "zh": "停止"},
    "bind_toggle_log": {"en": "Toggle log", "zh": "切换日志"},
    "bind_quit": {"en": "Quit", "zh": "退出"},
    "lang_prompt": {"en": "Choose your language", "zh": "选择语言"},
    "lang_english": {"en": "English", "zh": "English"},
    "lang_chinese": {"en": "中文 (Chinese)", "zh": "中文 (Chinese)"},
    "lang_btn": {"en": "中文", "zh": "English"},
    "bind_toggle_lang": {"en": "Language", "zh": "语言"},
}


def t(lang: str, key: str, **kw) -> str:
    text = STRINGS[key].get(lang, STRINGS[key]["en"])
    return text.format(**kw) if kw else text


# --------------------------------------------------------------------------
# Line-buffered stdout forwarder: lets us reuse core's existing print()-based
# debug/status output (popup retry messages, "Logged: ..." lines, page-load
# warnings) as content for the dashboard's Activity log, instead of losing it
# or letting it corrupt the TUI's screen rendering.
# --------------------------------------------------------------------------
class _LineForwarder:
    def __init__(self, on_line):
        self._on_line = on_line
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._on_line(line)
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False


# --------------------------------------------------------------------------
# Demo data generator (used with --demo, no Google/Selenium needed at all)
# --------------------------------------------------------------------------
import random

_DEMO_ADJ = ["velvet", "crimson", "lunar", "quiet", "electric", "amber", "wild", "neon"]
_DEMO_NOUN = ["fox", "star", "raven", "wolf", "tiger", "storm", "comet", "lotus"]


def _demo_username():
    return f"{random.choice(_DEMO_ADJ)}_{random.choice(_DEMO_NOUN)}{random.randint(10, 999)}"


# --------------------------------------------------------------------------
# Language screen — pick English or Chinese before anything else
# --------------------------------------------------------------------------
class LanguageScreen(Screen):
    def compose(self) -> ComposeResult:
        with Vertical(id="lang-card"):
            yield Static("◆ STRIPCHAT TRACKER", id="lang-title")
            yield Static("Choose your language / 选择语言", id="lang-subtitle")
            with Center():
                yield OptionList(id="lang-list")

    def on_mount(self) -> None:
        option_list = self.query_one("#lang-list", OptionList)
        option_list.add_option(Option("English", id="en"))
        option_list.add_option(Option("中文 (Chinese)", id="zh"))
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.app.lang = str(event.option.id)
        self.app.push_screen(ConnectScreen())


# --------------------------------------------------------------------------
# Connect screen — authorize + pick a worksheet tab
# --------------------------------------------------------------------------
class ConnectScreen(Screen):
    def compose(self) -> ComposeResult:
        lang = self.app.lang
        with Vertical(id="connect-card"):
            yield Static(t(lang, "app_title"), id="connect-title")
            yield Static(
                t(lang, "connecting") if not DEMO else t(lang, "demo_mode"),
                id="connect-subtitle",
            )
            yield LoadingIndicator()
            yield OptionList(id="sheet-list")
            yield Static("", id="connect-error")
            yield Button(t(lang, "retry"), id="retry-btn", variant="warning")

    def on_mount(self) -> None:
        self.query_one("#sheet-list", OptionList).display = False
        self.query_one("#retry-btn", Button).display = False
        self.connect()

    @work(thread=True)
    def connect(self) -> None:
        if DEMO:
            time.sleep(0.6)
            names = ["Demo Sheet A", "Demo Sheet B", "Test"]
            self.app.call_from_thread(self._on_connected, None, names)
            return
        try:
            scope = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = core.ServiceAccountCredentials.from_json_keyfile_name(
                "credentials.json", scope
            )
            client = core.gspread.authorize(creds)
            spreadsheet = client.open(core.SHEET_NAME)
            names = [ws.title for ws in spreadsheet.worksheets()]
            self.app.call_from_thread(self._on_connected, spreadsheet, names)
        except Exception as e:
            self.app.call_from_thread(self._on_error, str(e))

    def _on_connected(self, spreadsheet, names) -> None:
        self.app.spreadsheet = spreadsheet
        self.query_one(LoadingIndicator).display = False
        self.query_one("#connect-subtitle", Static).update(
            t(self.app.lang, "select_sheet")
        )
        option_list = self.query_one("#sheet-list", OptionList)
        option_list.clear_options()
        for name in names:
            option_list.add_option(Option(name, id=name))
        option_list.display = True
        option_list.focus()

    def _on_error(self, message: str) -> None:
        self.query_one(LoadingIndicator).display = False
        self.query_one("#connect-subtitle", Static).update(t(self.app.lang, "connect_failed"))
        error = self.query_one("#connect-error", Static)
        error.update(message)
        error.add_class("visible")
        self.query_one("#retry-btn", Button).display = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "retry-btn":
            self.query_one("#retry-btn", Button).display = False
            self.query_one("#connect-error", Static).remove_class("visible")
            self.query_one(LoadingIndicator).display = True
            self.query_one("#connect-subtitle", Static).update(t(self.app.lang, "connecting"))
            self.connect()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        sheet_name = str(event.option.id)
        if DEMO:
            self.app.sheet_name = sheet_name
            self.app.worksheet = None
        else:
            self.app.worksheet = self.app.spreadsheet.worksheet(sheet_name)
            self.app.sheet_name = sheet_name
        self.app.push_screen(DashboardScreen())


# --------------------------------------------------------------------------
# Modal: generic "pause and confirm" gate -- used both for the initial manual
# login and for the "go navigate to the right channel" step after switching
# sheets, so both flows share one Ready/Cancel affordance.
# --------------------------------------------------------------------------
class ReadyModal(ModalScreen):
    def __init__(self, title: str, body: str, on_confirm, on_cancel):
        super().__init__()
        self._title = title
        self._body = body
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel

    def compose(self) -> ComposeResult:
        lang = self.app.lang
        with Vertical(id="login-card"):
            yield Static(self._title, classes="modal-title")
            yield Static(self._body)
            with Horizontal(id="login-buttons"):
                yield Button(t(lang, "ready"), id="confirm-btn", variant="success")
                yield Button(t(lang, "cancel"), id="cancel-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self.dismiss()
            self._on_confirm()
        else:
            self.dismiss()
            self._on_cancel()


# --------------------------------------------------------------------------
# Modal: switch sheet/tab while stopped. Always dismissable (Cancel button +
# Escape) so it can never sit as a dead-end scrim over the dashboard.
# --------------------------------------------------------------------------
class SwitchSheetModal(ModalScreen):
    BINDINGS = [Binding("escape", "cancel_switch", "Cancel")]

    def compose(self) -> ComposeResult:
        lang = self.app.lang
        with Vertical(id="switch-card"):
            yield Static(t(lang, "switch_sheet_title"), classes="modal-title")
            yield OptionList(id="switch-list")
            with Horizontal(id="switch-buttons"):
                yield Button(t(lang, "cancel"), id="switch-cancel-btn", variant="error")

    def on_mount(self) -> None:
        option_list = self.query_one("#switch-list", OptionList)
        if DEMO:
            names = ["Demo Sheet A", "Demo Sheet B", "Test"]
        else:
            names = [ws.title for ws in self.app.spreadsheet.worksheets()]
        for name in names:
            option_list.add_option(Option(name, id=name))
        option_list.focus()

    def action_cancel_switch(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "switch-cancel-btn":
            self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id))


# --------------------------------------------------------------------------
# Modal: generic confirm (used for Quit while running)
# --------------------------------------------------------------------------
class ConfirmModal(ModalScreen):
    def __init__(self, message: str):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        lang = self.app.lang
        with Vertical(id="confirm-card"):
            yield Static(t(lang, "confirm_title"), classes="modal-title")
            yield Static(self._message)
            with Horizontal(id="confirm-buttons"):
                yield Button(t(lang, "yes"), id="yes-btn", variant="error")
                yield Button(t(lang, "no"), id="no-btn", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes-btn")


# --------------------------------------------------------------------------
# Main dashboard screen
# --------------------------------------------------------------------------
class DashboardScreen(Screen):
    BINDINGS = [
        Binding("s", "start", "Start / 开始"),
        Binding("x", "stop", "Stop / 停止"),
        Binding("l", "toggle_log", "Toggle log / 日志"),
        Binding("t", "toggle_lang", "Language / 语言"),
        Binding("q", "quit_app", "Quit / 退出"),
    ]

    def __init__(self):
        super().__init__()
        self.driver = None
        self.stop_event = None
        self.monitoring = False
        self.logged_count = 0
        self.start_time = None
        self._uptime_timer = None
        self._old_stdout = None
        self._column_keys = None
        self._status_state = "idle"
        self._quit_after_stop = False
        # Cached table rows per sheet name, so switching away and back doesn't
        # lose what's already been logged this session.
        self._sheet_rows = {}
        # Set when Switch Sheet picks a sheet while a browser session is
        # already open -- next Start gates on a Ready/Cancel confirmation
        # instead of silently resuming on the (possibly wrong) channel.
        self._needs_channel_confirm = False

    def compose(self) -> ComposeResult:
        lang = self.app.lang
        with Horizontal(id="topbar"):
            yield Static(t(lang, "app_title"), id="title")
            yield Static("", id="status-pill", classes="status-idle")
            yield Static("", id="sheet-badge")
        with Horizontal(id="stats-row"):
            yield Static(self._stat(t(lang, "stat_logged"), "0"), id="stat-users", classes="stat-card")
            yield Static(self._stat(t(lang, "stat_threshold"), f"Lv {core.LEVEL_THRESHOLD}+"), id="stat-threshold", classes="stat-card")
            yield Static(self._stat(t(lang, "stat_poll"), f"{core.CHECK_INTERVAL_SECONDS}s"), id="stat-interval", classes="stat-card")
            yield Static(self._stat(t(lang, "stat_uptime"), "00:00"), id="stat-uptime", classes="stat-card")
        with Horizontal(id="controls"):
            yield Button(t(lang, "start_btn"), id="start-btn", variant="success")
            yield Button(t(lang, "stop_btn"), id="stop-btn", variant="error", disabled=True)
            yield Button(t(lang, "switch_sheet_btn"), id="switch-btn")
            yield Button(t(lang, "lang_btn"), id="lang-btn")
            yield Button(t(lang, "quit_btn"), id="quit-btn")
        with Horizontal(id="main-area"):
            with Vertical(id="table-wrap"):
                yield DataTable(id="table")
            with Vertical(id="globe-panel"):
                with Horizontal(id="globe-header"):
                    yield Static(t(lang, "globe_title"), id="globe-title")
                yield Static(id="globe-map")
                yield Static(id="globe-info")
        with Vertical(id="log-panel"):
            yield RichLog(id="log", wrap=True, markup=True, highlight=False)
        yield Footer()

    @staticmethod
    def _stat(label: str, value: str) -> str:
        return f"[dim]{label}[/dim]\n[bold]{value}[/bold]"

    def on_mount(self) -> None:
        lang = self.app.lang
        self.query_one("#sheet-badge", Static).update(f"{self.app.sheet_name}")
        self._set_status("idle")
        table = self.query_one("#table", DataTable)
        self._column_keys = table.add_columns(
            t(lang, "col_time"),
            t(lang, "col_username"),
            t(lang, "col_level"),
            t(lang, "col_row"),
            t(lang, "col_link"),
        )
        table.cursor_type = "row"
        table.zebra_stripes = True
        self._uptime_timer = self.set_interval(1, self._tick_uptime, pause=True)
        self._render_globe(self.app.sheet_name)

    def _set_status(self, state: str) -> None:
        self._status_state = state
        lang = self.app.lang
        pill = self.query_one("#status-pill", Static)
        pill.remove_class("status-idle", "status-live", "status-busy")
        if state == "live":
            pill.update(t(lang, "status_live"))
            pill.add_class("status-live")
        elif state == "busy":
            pill.update(t(lang, "status_busy"))
            pill.add_class("status-busy")
        else:
            pill.update(t(lang, "status_idle"))
            pill.add_class("status-idle")

    def _tick_uptime(self) -> None:
        if not self.start_time:
            return
        elapsed = int(time.time() - self.start_time)
        mm, ss = divmod(elapsed, 60)
        self.query_one("#stat-uptime", Static).update(
            self._stat(t(self.app.lang, "stat_uptime"), f"{mm:02d}:{ss:02d}")
        )

    def append_log(self, line: str) -> None:
        self.query_one("#log", RichLog).write(line)

    def _render_globe(self, country: str) -> None:
        self.query_one("#globe-map", Static).update(worldmap.render_map(country))
        self.query_one("#globe-info", Static).update(worldmap.country_info(country, lang=self.app.lang))

    # ---------------- button / key actions ----------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            self.action_start()
        elif event.button.id == "stop-btn":
            self.action_stop()
        elif event.button.id == "switch-btn":
            self.action_switch_sheet()
        elif event.button.id == "lang-btn":
            self.action_toggle_lang()
        elif event.button.id == "quit-btn":
            self.action_quit_app()

    def action_toggle_lang(self) -> None:
        self.app.lang = "zh" if self.app.lang == "en" else "en"
        self._refresh_language()

    def _refresh_language(self) -> None:
        lang = self.app.lang

        self.query_one("#title", Static).update(t(lang, "app_title"))
        self.query_one("#stat-users", Static).update(
            self._stat(t(lang, "stat_logged"), str(self.logged_count))
        )
        self.query_one("#stat-threshold", Static).update(
            self._stat(t(lang, "stat_threshold"), f"Lv {core.LEVEL_THRESHOLD}+")
        )
        self.query_one("#stat-interval", Static).update(
            self._stat(t(lang, "stat_poll"), f"{core.CHECK_INTERVAL_SECONDS}s")
        )
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            mm, ss = divmod(elapsed, 60)
            uptime_value = f"{mm:02d}:{ss:02d}"
        else:
            uptime_value = "00:00"
        self.query_one("#stat-uptime", Static).update(
            self._stat(t(lang, "stat_uptime"), uptime_value)
        )

        self.query_one("#start-btn", Button).label = t(lang, "start_btn")
        self.query_one("#stop-btn", Button).label = t(lang, "stop_btn")
        self.query_one("#switch-btn", Button).label = t(lang, "switch_sheet_btn")
        self.query_one("#lang-btn", Button).label = t(lang, "lang_btn")
        self.query_one("#quit-btn", Button).label = t(lang, "quit_btn")

        self._set_status(self._status_state)
        self.query_one("#globe-title", Static).update(t(lang, "globe_title"))
        self._render_globe(self.app.sheet_name)

        if self._column_keys:
            table = self.query_one("#table", DataTable)
            new_labels = [
                t(lang, "col_time"),
                t(lang, "col_username"),
                t(lang, "col_level"),
                t(lang, "col_row"),
                t(lang, "col_link"),
            ]
            for key, label in zip(self._column_keys, new_labels):
                column = table.columns[key]
                label_text = Text.from_markup(label)
                column.label = label_text
                content_width = measure(table.app.console, label_text, 1)
                column.content_width = content_width
                if column.auto_width:
                    column.width = content_width
            table._require_update_dimensions = True
            table.refresh()

    def action_start(self) -> None:
        if self.monitoring:
            return
        self.query_one("#start-btn", Button).disabled = True
        self.query_one("#switch-btn", Button).disabled = True
        self._set_status("busy")
        if DEMO:
            self._begin_monitoring()
        else:
            self._old_stdout = sys.stdout
            sys.stdout = _LineForwarder(lambda line: self.app.call_from_thread(self.append_log, line))
            if self.driver is None:
                # No browser session yet -- open one, then gate on the
                # initial manual-login Ready/Cancel modal.
                self._launch_browser()
            elif self._needs_channel_confirm:
                # Sheet was switched since the browser was last used -- make
                # sure the user has navigated to the right channel before
                # counting starts on the new sheet.
                self._show_channel_confirm_modal()
            else:
                # Browser session already open and still pointed at the right
                # channel -- reuse it instead of opening another window.
                self._begin_monitoring()

    @work(thread=True)
    def _launch_browser(self) -> None:
        try:
            driver = core.start_browser()
            self.app.call_from_thread(self._show_login_modal, driver)
        except Exception as e:
            self.app.call_from_thread(
                self._on_fatal_error,
                t(self.app.lang, "browser_start_failed", error=e),
            )

    def _show_login_modal(self, driver) -> None:
        self.driver = driver
        lang = self.app.lang
        self.app.push_screen(
            ReadyModal(
                t(lang, "login_title"),
                t(lang, "login_body"),
                on_confirm=self._begin_monitoring,
                on_cancel=self._cancel_launch,
            )
        )

    def _cancel_launch(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self._restore_stdout()
        self.query_one("#start-btn", Button).disabled = False
        self.query_one("#switch-btn", Button).disabled = False
        self._set_status("idle")

    def _show_channel_confirm_modal(self) -> None:
        lang = self.app.lang
        sheet_name = self.app.sheet_name
        self.app.push_screen(
            ReadyModal(
                t(lang, "switch_navigate_title", sheet=sheet_name),
                t(lang, "switch_navigate_body", sheet=sheet_name),
                on_confirm=self._confirm_channel_and_begin,
                on_cancel=self._cancel_channel_confirm,
            )
        )

    def _confirm_channel_and_begin(self) -> None:
        self._needs_channel_confirm = False
        self._begin_monitoring()

    def _cancel_channel_confirm(self) -> None:
        # Leave _needs_channel_confirm set so the next Start asks again --
        # only Ready clears it. Just abort this Start attempt.
        self._restore_stdout()
        self.query_one("#start-btn", Button).disabled = False
        self.query_one("#switch-btn", Button).disabled = False
        self._set_status("idle")

    def _begin_monitoring(self) -> None:
        self.monitoring = True
        self.stop_event = threading.Event()
        self.start_time = time.time()
        self.logged_count = 0
        self._uptime_timer.resume()
        self._set_status("live")
        self.query_one("#stop-btn", Button).disabled = False
        self.query_one("#stat-users", Static).update(self._stat("Logged", "0"))
        if DEMO:
            self._run_demo_loop(self.stop_event)
        else:
            self._run_monitor_loop(self.driver, self.app.worksheet, self.stop_event)

    @work(thread=True)
    def _run_monitor_loop(self, driver, sheet, stop_event: threading.Event) -> None:
        try:
            logged_usernames, next_row = core.load_sheet_state(sheet)
            pending_link_fixups = {}
            while not stop_event.is_set():
                try:
                    rows = driver.find_elements(core.By.CSS_SELECTOR, core.USER_ROW_SELECTOR)
                    for row in rows:
                        if stop_event.is_set():
                            break
                        try:
                            username = row.find_element(
                                core.By.CSS_SELECTOR, core.USERNAME_SELECTOR
                            ).text.strip()
                            level_digits = "".join(
                                filter(
                                    str.isdigit,
                                    row.find_element(core.By.CSS_SELECTOR, core.LEVEL_SELECTOR).text.strip(),
                                )
                            )
                            if not level_digits:
                                continue
                            level = int(level_digits)

                            if level >= core.LEVEL_THRESHOLD and username not in logged_usernames:
                                profile_link = core.get_profile_link_via_popup(driver, row, username)
                                core.log_user(sheet, username, level, profile_link, next_row)
                                logged_usernames.add(username)
                                self.app.call_from_thread(
                                    self._on_new_user,
                                    username,
                                    level,
                                    profile_link,
                                    next_row,
                                )
                                if not profile_link:
                                    pending_link_fixups[username] = (next_row, 0)
                                next_row += 1

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
            # stays open across Stop so the next Start reuses it (see
            # action_start). It's only closed on app Quit.
            self.app.call_from_thread(self._on_monitoring_stopped)

    @work(thread=True)
    def _run_demo_loop(self, stop_event: threading.Event) -> None:
        row = 2
        while not stop_event.is_set():
            wait = random.uniform(2, 4.5)
            if stop_event.wait(wait):
                break
            username = _demo_username()
            level = random.randint(core.LEVEL_THRESHOLD, core.LEVEL_THRESHOLD + 40)
            link = f"https://stripchat.com/{username}"
            self.app.call_from_thread(self._on_new_user, username, level, link, row)
            row += 1
        self.app.call_from_thread(self._on_monitoring_stopped)

    def _on_new_user(self, username: str, level: int, link: str, row_number: int) -> None:
        lang = self.app.lang
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._sheet_rows.setdefault(self.app.sheet_name, []).append(
            (timestamp, username, str(level), str(row_number), link)
        )
        table = self.query_one("#table", DataTable)
        link_cell = f"[link={link}]{t(lang, 'link_open')}[/link]" if link else "[dim]—[/dim]"
        table.add_row(timestamp, username, str(level), str(row_number), link_cell)
        table.move_cursor(row=table.row_count - 1)
        self.logged_count += 1
        self.query_one("#stat-users", Static).update(
            self._stat(t(lang, "stat_logged"), str(self.logged_count))
        )

    def _redraw_table_for_sheet(self, sheet_name: str) -> None:
        lang = self.app.lang
        table = self.query_one("#table", DataTable)
        table.clear()
        rows = self._sheet_rows.get(sheet_name, [])
        for timestamp, username, level_str, row_number_str, link in rows:
            link_cell = f"[link={link}]{t(lang, 'link_open')}[/link]" if link else "[dim]—[/dim]"
            table.add_row(timestamp, username, level_str, row_number_str, link_cell)
        if table.row_count:
            table.move_cursor(row=table.row_count - 1)
        self.logged_count = len(rows)
        self.query_one("#stat-users", Static).update(
            self._stat(t(lang, "stat_logged"), str(self.logged_count))
        )

    def action_stop(self) -> None:
        if not self.monitoring or not self.stop_event:
            return
        self.stop_event.set()
        self.query_one("#stop-btn", Button).disabled = True
        self._set_status("busy")

    def _on_monitoring_stopped(self) -> None:
        self.monitoring = False
        # Deliberately keep self.driver around -- the browser session persists
        # across Stop so the next Start can reuse it (see action_start).
        self.start_time = None
        self._uptime_timer.pause()
        self._restore_stdout()
        self._set_status("idle")
        self.query_one("#start-btn", Button).disabled = False
        self.query_one("#stop-btn", Button).disabled = True
        self.query_one("#switch-btn", Button).disabled = False
        if self._quit_after_stop:
            self._quit_driver_and_exit()

    def _restore_stdout(self) -> None:
        if self._old_stdout is not None:
            sys.stdout = self._old_stdout
            self._old_stdout = None

    def _on_fatal_error(self, message: str) -> None:
        self._restore_stdout()
        self.query_one("#start-btn", Button).disabled = False
        self.query_one("#switch-btn", Button).disabled = False
        self._set_status("idle")
        self.app.notify(message, title=t(self.app.lang, "error_title"), severity="error", timeout=10)

    def action_toggle_log(self) -> None:
        panel = self.query_one("#log-panel")
        panel.toggle_class("visible")

    def action_switch_sheet(self) -> None:
        # Only reachable before Start / after Stop -- the button is disabled
        # while monitoring is live, this is just a safety net.
        if self.monitoring:
            return
        self.app.push_screen(SwitchSheetModal(), self._on_switch_sheet_picked)

    def _on_switch_sheet_picked(self, sheet_name) -> None:
        if not sheet_name:
            return  # picker was cancelled -- leave the current sheet as-is
        worksheet = None if DEMO else self.app.spreadsheet.worksheet(sheet_name)
        self._commit_sheet_switch(sheet_name, worksheet)
        if self.driver is not None:
            # A browser session is already open, pointed at whatever channel
            # matched the old sheet -- don't let Start silently begin
            # counting against the new sheet until the user has manually
            # navigated to the right channel and confirmed via Start's
            # Ready/Cancel gate (see action_start).
            self._needs_channel_confirm = True

    def _commit_sheet_switch(self, sheet_name: str, worksheet) -> None:
        self.app.worksheet = worksheet
        self.app.sheet_name = sheet_name
        self.query_one("#sheet-badge", Static).update(sheet_name)
        self._render_globe(sheet_name)
        # Swap the visible table for this sheet's cached rows (empty if it
        # hasn't been visited yet this session) without losing the other
        # sheets' data -- switching back later restores it.
        self._redraw_table_for_sheet(sheet_name)

    def action_quit_app(self) -> None:
        if self.monitoring:

            def handle_result(confirmed) -> None:
                if confirmed:
                    self._quit_after_stop = True
                    self.action_stop()

            self.app.push_screen(
                ConfirmModal(t(self.app.lang, "quit_confirm")), handle_result
            )
        else:
            self._quit_driver_and_exit()

    def _quit_driver_and_exit(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self.app.exit()


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
class TrackerApp(App):
    CSS_PATH = "dashboard.tcss"
    TITLE = "Stripchat Tracker"
    ENABLE_COMMAND_PALETTE = False

    def __init__(self):
        super().__init__()
        self.lang = "en"
        self.spreadsheet = None
        self.worksheet = None
        self.sheet_name = ""

    def on_mount(self) -> None:
        self.push_screen(LanguageScreen())


if __name__ == "__main__":
    TrackerApp().run()

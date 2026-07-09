"""
Stripchat High-Level User Tracker
----------------------------------
Watches your live dashboard, detects users above a level threshold,
and logs them to a Google Sheet in real time.

BEFORE RUNNING:
1. Put your Google service account file in this folder, named credentials.json
2. Fill in SHEET_NAME below with your actual Google Sheet name
3. Fill in the CSS selectors in the "SELECTORS TO FILL IN" section —
   get these by right-clicking elements on your dashboard and choosing "Inspect"
4. Fill in your Stripchat login email/password (or log in manually when the browser opens)
"""

import time
from datetime import datetime

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ---------------- CONFIG ----------------
SHEET_NAME = "stripchat tracker"
LEVEL_THRESHOLD = 30
CHECK_INTERVAL_SECONDS = 5
DASHBOARD_URL = "https://stripchat.com"  # your live/dashboard page
SITE_BASE_URL = "https://stripchat.com"  # used to build full profile links from the relative href
# Domain to write into the sheet's link column -- lets you keep browsing on .ooo
# while the saved links always use .com (or whatever domain you set here).
OUTPUT_LINK_DOMAIN = "https://stripchat.com"

# ---------------- SELECTORS (filled in from your dashboard's HTML) ----------------
# Each user row in the viewer list
USER_ROW_SELECTOR = "div.users-list li"
# Username text inside a row
USERNAME_SELECTOR = "span.user-levels-username-text"
# Level number is inside an SVG <text> tag inside the badge
LEVEL_SELECTOR = "span.user-level-badge svg text"
# Clicking a username opens a popup card; the profile link only exists inside THAT popup,
# never in the plain row. This selector targets the link inside the popup once it's open.
POPUP_LINK_SELECTOR = "div.user-info-popup-header a.user-levels-username-link"
# Max time to wait for the popup to render / close after a click (seconds). These are
# ceilings, not fixed delays -- WebDriverWait returns as soon as the element shows up,
# so a fast-rendering popup doesn't cost the full timeout.
POPUP_OPEN_TIMEOUT_SECONDS = 2.5
POPUP_CLOSE_TIMEOUT_SECONDS = 1.0
# If the popup link is missing/blank on the first try, retry this many extra times
# before giving up and logging with a blank link.
POPUP_LINK_MAX_ATTEMPTS = 3
# If a user is logged with a blank profile link, keep retrying the popup click on
# later poll cycles (while they're still qualifying) for up to this many cycles
# before giving up on filling in the link.
LINK_FIXUP_MAX_CYCLES = 5

# ---------------- GOOGLE SHEETS SETUP ----------------
def choose_worksheet(spreadsheet):
    """Ask the user which tab/worksheet to log to, showing the real tab names
    from the spreadsheet so a typo can't silently point at the wrong tab."""
    worksheets = spreadsheet.worksheets()
    names = [ws.title for ws in worksheets]

    print("Available sheets/tabs:")
    for name in names:
        print(f"  - {name}")

    while True:
        choice = input("Type the sheet/tab name to log to: ").strip()
        # Case-insensitive match so "china" still hits "China"
        for name in names:
            if name.lower() == choice.lower():
                return spreadsheet.worksheet(name)
        print(f"'{choice}' isn't one of the tabs above. Try again.")


def connect_to_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open(SHEET_NAME)
    sheet = choose_worksheet(spreadsheet)
    return sheet


def load_sheet_state(sheet):
    """
    Read column A exactly once at startup and cache it in memory: as a set for instant
    "already logged?" membership checks, and its length to know which row to write next.
    This replaces re-fetching the whole column from the Sheets API on every qualifying
    row of every poll cycle -- that round-trip was the biggest source of lag, and if it
    ever hiccuped/rate-limited it also risked double-logging or silently missing a user
    for that cycle.
    """
    existing_usernames = sheet.col_values(1)
    return set(existing_usernames), len(existing_usernames) + 1


def to_output_domain(url):
    """Rewrite a captured profile URL to use OUTPUT_LINK_DOMAIN instead of whatever
    domain you're actually browsing on (e.g. stripchat.ooo -> stripchat.com)."""
    if not url:
        return url
    path = url.split("://", 1)[-1]  # strip scheme
    path = path.split("/", 1)[-1] if "/" in path else ""  # strip domain, keep "/user/xxx"
    return f"{OUTPUT_LINK_DOMAIN}/{path}"


def log_user(sheet, username, level, profile_link, row_number):
    """Write directly to A:E of a specific, known row number -- no ambiguity about
    where "the table" starts, unlike append_row. The row number is tracked locally
    by the caller (see `next_row` in monitor()) instead of re-reading column A on
    every log, which saves another Sheets API round-trip per new user found."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.update(
        range_name=f"A{row_number}:E{row_number}",
        values=[[username, level, timestamp, "", profile_link]],
    )
    print(f"Logged: {username} (Level {level}) -> {profile_link} at row {row_number}, {timestamp}")


def get_profile_link_via_popup(driver, row, username):
    """
    The profile link only exists inside the popup card that appears after clicking
    a username -- it's not present in the plain row markup. This clicks the username,
    waits (up to POPUP_OPEN_TIMEOUT_SECONDS) for the popup to actually render, reads
    the href, then presses Escape and waits for it to actually close before moving on.

    Using WebDriverWait instead of a fixed sleep means we don't block for longer than
    necessary when the popup renders quickly, and don't give up too soon when the page
    is briefly slow -- which is what was causing blank links in the sheet before.

    Re-finds the username element from `row` on each attempt (rather than reusing a
    handle from an earlier DOM read) so a retry doesn't fail with a stale-element error
    if the list re-rendered in between, and verifies the popup's own username text
    matches before trusting its link, in case a previous popup hadn't fully closed.
    Returns "" if every attempt fails (still lets the caller log username/level).
    """
    href = ""
    for attempt in range(POPUP_LINK_MAX_ATTEMPTS):
        try:
            username_element = row.find_element(By.CSS_SELECTOR, USERNAME_SELECTOR)
            username_element.click()
            link_el = WebDriverWait(driver, POPUP_OPEN_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, POPUP_LINK_SELECTOR))
            )
            popup_username = link_el.text.strip()
            candidate = link_el.get_attribute("href")
            if candidate and (not popup_username or popup_username == username):
                href = to_output_domain(candidate)
        except Exception:
            pass
        finally:
            # Close the popup so it doesn't cover the next row's click target, and
            # actually wait for it to be gone rather than guessing at a fixed delay.
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                WebDriverWait(driver, POPUP_CLOSE_TIMEOUT_SECONDS).until_not(
                    EC.presence_of_element_located((By.CSS_SELECTOR, POPUP_LINK_SELECTOR))
                )
            except Exception:
                pass
        if href:
            break
    return href


# ---------------- BROWSER SETUP ----------------
def start_browser():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    # Keep the window open so you can manually log in the first time
    options.add_experimental_option("detach", True)
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    driver.get(DASHBOARD_URL)
    return driver


# ---------------- MAIN MONITOR LOOP ----------------
def monitor(driver, sheet):
    print("Log into Stripchat manually in the opened browser window.")
    input("Once you're logged in and your stream is live, press Enter here to start monitoring...")

    # Cache column A once instead of hitting the Sheets API on every qualifying row of
    # every cycle -- see load_sheet_state() for why.
    logged_usernames, next_row = load_sheet_state(sheet)

    print(f"Monitoring for users level {LEVEL_THRESHOLD}+... (Ctrl+C to stop)")

    while True:
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, USER_ROW_SELECTOR)
            print(f"[debug] found {len(rows)} row(s) matching USER_ROW_SELECTOR")  # DEBUG

            for i, row in enumerate(rows):
                try:
                    username_element = row.find_element(By.CSS_SELECTOR, USERNAME_SELECTOR)
                    username = username_element.text.strip()
                    level_text = row.find_element(By.CSS_SELECTOR, LEVEL_SELECTOR).text.strip()
                    level = int("".join(filter(str.isdigit, level_text)))

                    print(f"[debug] row {i}: {username} | level {level}")  # DEBUG

                    if level >= LEVEL_THRESHOLD and username not in logged_usernames:
                        # Only click into the popup for users we're actually about to log —
                        # clicking every single row every cycle would be slow and disruptive.
                        profile_link = get_profile_link_via_popup(driver, row, username)
                        log_user(sheet, username, level, profile_link, next_row)
                        logged_usernames.add(username)
                        next_row += 1

                except Exception as row_err:
                    # Row didn't match expected structure (e.g. no level badge), skip it
                    print(f"[debug] row {i} skipped: {row_err}")  # DEBUG
                    continue

        except Exception as e:
            print(f"Page structure issue, retrying: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    sheet = connect_to_sheet()
    driver = start_browser()
    try:
        monitor(driver, sheet)
    except KeyboardInterrupt:
        print("\nStopped monitoring.")

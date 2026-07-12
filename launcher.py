"""
StripTracker Launcher
----------------------
The thing the operator actually double-clicks. It never contains the app's
real logic -- that lives in the "core" build (dashboard.py, packaged as
StripTrackerCore) which gets replaced wholesale on every update. This file
should change as rarely as possible, since updating it means reinstalling
by hand rather than through the auto-update path it implements.

On every launch:
  1. Check the GitHub repo's latest release (public, unauthenticated API).
  2. If newer than what's installed, download + unzip it into a fresh
     versions/<tag>/ folder under the app-data dir, and point "current" at it.
  3. Launch the core app from "current".

Any failure in steps 1-2 (offline, GitHub unreachable, bad release) is
swallowed silently -- an update check must never block or crash a launch.
Only a genuine first-run-with-no-internet (nothing installed yet AND the
check failed) surfaces a message, since there's nothing to launch at all.
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
import zipfile
from tkinter import ttk

REPO = "miketeeranan-cmyk/stripbotPC"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
CORE_BUILD_NAME = "StripTrackerCore"
KEEP_PRIOR_VERSIONS = 1  # how many old versions to keep around for rollback


def app_data_dir() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    path = os.path.join(base, "StripTracker")
    os.makedirs(path, exist_ok=True)
    return path


def versions_dir() -> str:
    path = os.path.join(app_data_dir(), "versions")
    os.makedirs(path, exist_ok=True)
    return path


def _current_version_file() -> str:
    return os.path.join(app_data_dir(), "current_version.txt")


def read_current_version():
    path = _current_version_file()
    if os.path.isfile(path):
        with open(path) as f:
            tag = f.read().strip()
        return tag or None
    return None


def write_current_version(tag: str) -> None:
    with open(_current_version_file(), "w") as f:
        f.write(tag)


def asset_name() -> str:
    return f"{CORE_BUILD_NAME}-mac.zip" if sys.platform == "darwin" else f"{CORE_BUILD_NAME}-windows.zip"


def fetch_latest_release() -> dict:
    req = urllib.request.Request(
        LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.load(resp)


def download_asset(url: str, dest_path: str, progress_cb=None) -> None:
    req = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest_path, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb(done / total if total else None)


def install_version(tag: str, zip_path: str) -> str:
    target = os.path.join(versions_dir(), tag)
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target)
    if sys.platform == "darwin":
        # zipfile.extractall() preserves neither symlinks nor the executable
        # bit -- it would silently corrupt the .app bundle's
        # Python.framework symlinks on every single update (the same class
        # of bug ditto was already needed for on the packaging side, see
        # packaging/package_release.py). ditto is the extraction
        # counterpart that handles both correctly.
        subprocess.run(["ditto", "-x", "-k", zip_path, target], check=True)
    else:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(target)
    return target


def prune_old_versions(keep_tag: str) -> None:
    others = [d for d in os.listdir(versions_dir()) if d != keep_tag]
    others.sort(key=lambda d: os.path.getmtime(os.path.join(versions_dir(), d)), reverse=True)
    for stale in others[KEEP_PRIOR_VERSIONS:]:
        shutil.rmtree(os.path.join(versions_dir(), stale), ignore_errors=True)


def check_for_update():
    """Returns (tag, asset) if a newer release is available, else None.
    None covers both "already up to date" and "check failed" identically --
    either way the caller should just launch whatever's already installed."""
    try:
        current = read_current_version()
        release = fetch_latest_release()
        tag = release["tag_name"]
        if tag == current and os.path.isdir(os.path.join(versions_dir(), tag)):
            return None
        asset = next((a for a in release.get("assets", []) if a["name"] == asset_name()), None)
        return (tag, asset) if asset else None
    except Exception:
        return None  # offline / GitHub unreachable / bad release -- launch whatever's there


def apply_update(tag: str, asset: dict, progress_cb=None) -> bool:
    """Downloads + installs the given release. current_version.txt is only
    rewritten after a fully successful install, so a failed/interrupted
    update never corrupts a working install."""
    try:
        tmp_zip = os.path.join(app_data_dir(), "_download.zip")
        download_asset(asset["browser_download_url"], tmp_zip, progress_cb=progress_cb)
        install_version(tag, tmp_zip)
        os.remove(tmp_zip)
        write_current_version(tag)
        try:
            prune_old_versions(tag)  # disk hygiene only -- must not undo a successful update
        except Exception:
            pass
        return True
    except Exception:
        return False


def find_executable(version_dir: str):
    if not os.path.isdir(version_dir):
        return None
    if sys.platform == "darwin":
        for name in os.listdir(version_dir):
            if name.endswith(".app"):
                return os.path.join(version_dir, name)
        return None
    exe = os.path.join(version_dir, CORE_BUILD_NAME, f"{CORE_BUILD_NAME}.exe")
    return exe if os.path.isfile(exe) else None


def launch_current() -> bool:
    tag = read_current_version()
    if not tag:
        return False
    target = find_executable(os.path.join(versions_dir(), tag))
    if not target:
        return False
    if sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen([target])
    return True


def _tell_operator_no_internet() -> None:
    message = (
        "Couldn't start StripTracker -- no internet connection was found and "
        "no version is installed yet. Connect to the internet and try again."
    )
    if sys.platform == "darwin":
        safe = message.replace('"', "'")
        subprocess.run(["osascript", "-e", f'display alert "StripTracker" message "{safe}"'])
    elif sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "StripTracker", 0)
    else:
        print(message, file=sys.stderr)


def run_update_ui() -> None:
    """Small window: checks for an update, and either closes itself straight
    through (nothing new / check failed) or shows an Update Now button that
    reveals a real progress bar once clicked. Always returns with the window
    gone, ready for the caller to launch whatever's now installed. The
    window can't be closed while a download/install is in progress, so the
    caller never launches while that work is still mid-flight."""
    events = queue.Queue()
    updating = False
    indeterminate = False

    root = tk.Tk()
    root.title("StripTracker")
    root.geometry("320x110")
    root.resizable(False, False)
    root.eval("tk::PlaceWindow . center")
    root.protocol("WM_DELETE_WINDOW", lambda: None if updating else root.destroy())

    label = tk.Label(root, text="Checking for updates…", font=("Segoe UI", 11))
    label.pack(pady=(20, 8))
    button = tk.Button(root, text="Update Now")
    bar = ttk.Progressbar(root, length=260, mode="determinate", maximum=1.0)

    def start_check():
        threading.Thread(
            target=lambda: events.put(("checked", check_for_update())), daemon=True
        ).start()

    def start_apply(tag, asset):
        nonlocal updating
        updating = True
        label.config(text=f"Downloading update {tag}…")
        button.pack_forget()
        bar.pack(pady=8)

        def worker():
            ok = apply_update(tag, asset, progress_cb=lambda f: events.put(("progress", f)))
            events.put(("done", ok))

        threading.Thread(target=worker, daemon=True).start()

    def finish(message=None):
        nonlocal updating
        updating = False
        if message is None:
            root.destroy()
            return
        label.config(text=message)
        bar.pack_forget()
        root.after(1200, root.destroy)

    _NO_EVENT = object()  # distinct from a legitimate ("progress", None) indeterminate payload

    def poll():
        nonlocal indeterminate
        latest_progress = _NO_EVENT
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == "checked":
                    if payload is None:
                        finish()
                        return
                    tag, asset = payload
                    label.config(text=f"Update available: {tag}")
                    button.config(command=lambda: start_apply(tag, asset))
                    button.pack(pady=8)
                elif kind == "progress":
                    latest_progress = payload
                elif kind == "done":
                    finish(None if payload else "Update failed — launching current version…")
                    return
        except queue.Empty:
            pass
        if latest_progress is not _NO_EVENT:
            if latest_progress is None:
                if not indeterminate:
                    indeterminate = True
                    bar.config(mode="indeterminate")
                    bar.start(15)
            else:
                if indeterminate:
                    indeterminate = False
                    bar.stop()
                    bar.config(mode="determinate")
                bar["value"] = min(1.0, latest_progress)
        root.after(100, poll)

    start_check()
    root.after(100, poll)
    root.mainloop()


def main() -> None:
    run_update_ui()
    if not launch_current():
        _tell_operator_no_internet()
        sys.exit(1)


if __name__ == "__main__":
    main()

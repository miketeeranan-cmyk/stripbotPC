"""
Zip packaging/build.py output into the release asset names launcher.py (for
--core) and a human downloading from the Releases page (for --launcher)
expect:
    StripTrackerCore-mac.zip / StripTrackerCore-windows.zip
    StripTracker-mac.zip     / StripTracker-windows.zip

The zip's top-level entry must be exactly the app bundle/folder (not a
nested extra directory) -- launcher.py's find_executable() relies on that
shape for --core, and it keeps a human's unzip-and-double-click experience
identical for --launcher.

Run after the matching `python packaging/build.py --core` / `--launcher`.

Usage:
    python packaging/package_release.py --core
    python packaging/package_release.py --launcher
"""

import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(REPO_ROOT, "dist")

BUILDS = {
    "--core": "StripTrackerCore",
    "--launcher": "StripTracker",
}


def _missing_build_error(build_name: str) -> SystemExit:
    flag = "--core" if build_name == "StripTrackerCore" else "--launcher"
    return SystemExit(f"Build output not found for {build_name} -- run `python packaging/build.py {flag}` first")


def package(build_name: str):
    if sys.platform == "darwin":
        src = os.path.join(DIST, f"{build_name}.app")
        if not os.path.exists(src):
            raise _missing_build_error(build_name)
        out_zip = os.path.join(REPO_ROOT, f"{build_name}-mac.zip")
        if os.path.exists(out_zip):
            os.remove(out_zip)
        # macOS .app bundles contain symlinks (Python.framework internals) --
        # shutil.make_archive's zip writer silently mangles those on
        # extraction (broke the frozen interpreter's dynamic loader, e.g.
        # "No module named '_struct'"). ditto is Apple's own tool for
        # zipping bundles and preserves them correctly; --keepParent keeps
        # the .app itself (not just its contents) as the zip's top-level
        # entry, matching what find_executable() / a human's unzip expects.
        subprocess.run(["ditto", "-c", "-k", "--keepParent", src, out_zip], check=True)
        print(f"Wrote {out_zip}")
    elif sys.platform == "win32":
        src = os.path.join(DIST, build_name)
        if not os.path.exists(src):
            raise _missing_build_error(build_name)
        out_base = os.path.join(REPO_ROOT, f"{build_name}-windows")
        archive = shutil.make_archive(out_base, "zip", root_dir=DIST, base_dir=os.path.basename(src))
        print(f"Wrote {archive}")
    else:
        raise SystemExit(f"Unsupported platform for release packaging: {sys.platform}")


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit("Usage: python packaging/package_release.py --core|--launcher")
    for flag in args:
        if flag not in BUILDS:
            raise SystemExit(f"Unknown flag {flag!r} -- expected --core and/or --launcher")
        package(BUILDS[flag])


if __name__ == "__main__":
    main()

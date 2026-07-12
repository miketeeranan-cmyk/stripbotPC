"""
Zip the packaging/build.py --core output into the release asset name
launcher.py expects: StripTrackerCore-mac.zip / StripTrackerCore-windows.zip.

The zip's top-level entry must be exactly the app bundle/folder (not a
nested extra directory), since launcher.py's find_executable() looks for it
right at the root of the extracted version directory.

Run after `python packaging/build.py --core`.
"""

import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(REPO_ROOT, "dist")


def main():
    if sys.platform == "darwin":
        src = os.path.join(DIST, "StripTrackerCore.app")
        out_base = os.path.join(REPO_ROOT, "StripTrackerCore-mac")
    elif sys.platform == "win32":
        src = os.path.join(DIST, "StripTrackerCore")
        out_base = os.path.join(REPO_ROOT, "StripTrackerCore-windows")
    else:
        raise SystemExit(f"Unsupported platform for release packaging: {sys.platform}")

    if not os.path.exists(src):
        raise SystemExit(
            f"Expected build output not found: {src} -- run "
            "`python packaging/build.py --core` first"
        )

    archive = shutil.make_archive(out_base, "zip", root_dir=DIST, base_dir=os.path.basename(src))
    print(f"Wrote {archive}")


if __name__ == "__main__":
    main()

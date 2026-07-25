#!/usr/bin/env python
"""Build the single-file ``dist/CursorAssist.exe``.

Usage (from the repo root)::

    py tools/build_exe.py

Installs nothing behind your back — it only checks that PyInstaller is present
and tells you the one command to run if it isn't.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "CursorAssist.spec"


def main() -> int:
    if not sys.platform.startswith("win"):
        print("CursorAssist is a Windows tool; build it on Windows.",
              file=sys.stderr)
        return 2
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run:\n\n"
              "    py -m pip install pyinstaller\n", file=sys.stderr)
        return 1

    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC),
           "--noconfirm", "--clean", "--distpath", str(ROOT / "dist"),
           "--workpath", str(ROOT / "build")]
    print("$ " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    exe = ROOT / "dist" / "CursorAssist.exe"
    if not exe.exists():
        print("Build reported success but the exe is missing.", file=sys.stderr)
        return 1
    print(f"\nBuilt {exe}  ({exe.stat().st_size / 1e6:.1f} MB)")
    print("Send that single file — it needs no Python install on the far end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

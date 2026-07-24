"""Start Cursor Assist as a windowless background process.

Why this exists
---------------
Running ``py -m cursor_assist`` keeps a console window open the whole time. This
launcher instead runs the app under ``pythonw.exe`` (the windowless Python
interpreter), so **no console window** stays open -- you still get the
always-on-top control panel, just without the black terminal behind it.

The instance name
-----------------
As requested, each launch gets a randomly generated instance name. To make that
name actually show up as the *process* name in Task Manager, we copy
``pythonw.exe`` to ``.runtime/<random-name>.exe`` and launch through that copy.

This is deliberately transparent, not stealthy:
  * the chosen name and PID are written to ``.runtime/instance.json``;
  * the app still shows its visible control-panel window;
  * ``stop_hidden.py`` cleanly stops it and deletes the copy.

Nothing here hides the tool, disables logging, or persists at boot. To have it
start automatically at login, see the optional section in INSTALL.md.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = APP_ROOT / ".runtime"
STATE_FILE = RUNTIME_DIR / "instance.json"
RUN_TARGET = APP_ROOT / "run.py"

# Windows process-creation flags (from the Win32 API).
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def _random_name(length: int = 16) -> str:
    """A random identifier that is a valid filename and starts with a letter."""
    first = secrets.choice(string.ascii_lowercase)
    rest = "".join(
        secrets.choice(string.ascii_lowercase + string.digits)
        for _ in range(length - 1)
    )
    return first + rest


def _find_pythonw() -> Path:
    """Locate pythonw.exe (the windowless interpreter)."""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    if candidate.exists():
        return candidate
    found = shutil.which("pythonw")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "Could not find pythonw.exe next to the Python interpreter. Make sure "
        "the standard python.org Windows build is installed."
    )


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID is currently running (Windows)."""
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == STILL_ACTIVE
        return False
    finally:
        kernel32.CloseHandle(handle)


def _existing_instance() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if isinstance(data.get("pid"), int) and _pid_alive(data["pid"]):
        return data
    return None


def main() -> int:
    if not sys.platform.startswith("win"):
        print("Background mode uses Windows APIs and only runs on Windows.",
              file=sys.stderr)
        return 2

    running = _existing_instance()
    if running:
        print("Cursor Assist already appears to be running in the background:")
        print(f"  name: {running.get('name')}")
        print(f"  pid:  {running.get('pid')}")
        print("Stop it first with:  py background\\stop_hidden.py")
        return 1

    RUNTIME_DIR.mkdir(exist_ok=True)
    pythonw = _find_pythonw()

    name = _random_name()
    launcher = RUNTIME_DIR / f"{name}.exe"
    shutil.copy2(pythonw, launcher)

    # Launch fully detached: no console window, survives this script exiting.
    proc = subprocess.Popen(
        [str(launcher), str(RUN_TARGET)],
        cwd=str(APP_ROOT),
        creationflags=(
            DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        ),
        close_fds=True,
    )

    state = {
        "name": name,
        "process_exe": str(launcher),
        "pid": proc.pid,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    print("Cursor Assist started in the background (no console window).")
    print(f"  instance name : {name}")
    print(f"  process (PID) : {name}.exe  ({proc.pid})")
    print(f"  state file    : {STATE_FILE}")
    print("The always-on-top control panel should now be visible.")
    print("To stop it later:  py background\\stop_hidden.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

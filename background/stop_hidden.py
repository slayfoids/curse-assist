"""Stop the windowless background instance started by ``start_hidden.py``.

Reads ``.runtime/instance.json``, terminates the recorded process, and deletes
the randomly named interpreter copy so nothing is left lying around.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = APP_ROOT / ".runtime"
STATE_FILE = RUNTIME_DIR / "instance.json"

CREATE_NO_WINDOW = 0x08000000


def _taskkill(pid: int) -> bool:
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"],
        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
    )
    return result.returncode == 0


def main() -> int:
    if not STATE_FILE.exists():
        print("No background instance recorded (.runtime/instance.json missing).")
        return 0

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"Could not read state file: {exc}", file=sys.stderr)
        return 1

    pid = state.get("pid")
    name = state.get("name", "?")
    if isinstance(pid, int):
        if _taskkill(pid):
            print(f"Stopped background instance '{name}' (PID {pid}).")
        else:
            print(f"Instance '{name}' (PID {pid}) was not running.")
    else:
        print("State file had no valid PID; nothing to kill.")

    # Give the OS a moment to release the file handle, then clean up the copy.
    exe = state.get("process_exe")
    if exe:
        exe_path = Path(exe)
        for _ in range(10):
            try:
                if exe_path.exists():
                    exe_path.unlink()
                break
            except OSError:
                time.sleep(0.2)

    try:
        STATE_FILE.unlink()
    except OSError:
        pass

    print("Cleaned up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

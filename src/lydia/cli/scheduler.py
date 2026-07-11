"""macOS launchd scheduling for `lydia briefing run --notify`.

launchd, not cron: cron is deprecated on macOS and won't fire while the Mac
is asleep at the scheduled time the way launchd catches up on wake.
`runner` is injectable so tests never invoke the real `launchctl`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

PLIST_LABEL = "com.lydia.briefing"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
LOG_PATH = Path.home() / ".lydia" / "briefing.log"

Runner = Callable[..., subprocess.CompletedProcess]


class ScheduleError(Exception):
    """Could not enable/disable the scheduled briefing."""


def _parse_time(time_str: str) -> tuple[int, int]:
    parts = time_str.split(":")
    try:
        if len(parts) != 2:
            raise ValueError
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        raise ScheduleError(f"Invalid time '{time_str}'; expected 24-hour HH:MM, e.g. 08:00.") from None
    return hour, minute


def _plist_contents(lydia_path: str, hour: int, minute: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>Label</key>
\t<string>{PLIST_LABEL}</string>
\t<key>ProgramArguments</key>
\t<array>
\t\t<string>{lydia_path}</string>
\t\t<string>briefing</string>
\t\t<string>run</string>
\t\t<string>--notify</string>
\t</array>
\t<key>StartCalendarInterval</key>
\t<dict>
\t\t<key>Hour</key>
\t\t<integer>{hour}</integer>
\t\t<key>Minute</key>
\t\t<integer>{minute}</integer>
\t</dict>
\t<key>StandardOutPath</key>
\t<string>{LOG_PATH}</string>
\t<key>StandardErrorPath</key>
\t<string>{LOG_PATH}</string>
</dict>
</plist>
"""


def _find_lydia_executable() -> str:
    path = shutil.which("lydia")
    if not path:
        raise ScheduleError("Could not find `lydia` on PATH. Pass an explicit lydia_path.")
    return path


def enable(
    time_str: str,
    lydia_path: str | None = None,
    runner: Runner = subprocess.run,
) -> Path:
    """Write the launchd plist for the given time and load it. Returns the plist path."""
    hour, minute = _parse_time(time_str)
    resolved_path = lydia_path or _find_lydia_executable()
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_plist_contents(resolved_path, hour, minute), encoding="utf-8")
    result = runner(["launchctl", "load", str(PLIST_PATH)], capture_output=True, text=True)
    if result.returncode != 0:
        raise ScheduleError(f"launchctl load failed: {(result.stderr or result.stdout).strip()}")
    return PLIST_PATH


def disable(runner: Runner = subprocess.run) -> None:
    if not PLIST_PATH.is_file():
        return
    runner(["launchctl", "unload", str(PLIST_PATH)], capture_output=True, text=True)
    PLIST_PATH.unlink()


def is_enabled() -> bool:
    return PLIST_PATH.is_file()

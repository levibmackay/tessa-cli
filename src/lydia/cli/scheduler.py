"""OS-native scheduling for `lydia briefing run --notify`.

Two backends, selected by `platform.system()`:

- macOS: `launchd`, via a plist in `~/Library/LaunchAgents` and `launchctl`.
  Not cron: cron is deprecated on macOS and won't fire while the Mac is
  asleep at the scheduled time the way launchd catches up on wake.
- Linux: a `systemd --user` service + timer unit pair in
  `~/.config/systemd/user/`, enabled via `systemctl --user`. This runs
  whether or not a login session is active, same as launchd on macOS,
  without needing root (`--user`, not the system manager).

Any other platform (Windows, or a Linux without systemd) raises
`ScheduleError` with a clear message instead of a raw subprocess crash.

`runner` is injectable on every function that shells out so tests never
invoke the real `launchctl`/`systemctl`.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Callable

PLIST_LABEL = "com.lydia.briefing"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"

SYSTEMD_UNIT_NAME = "lydia-briefing"
SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
SYSTEMD_SERVICE_PATH = SYSTEMD_USER_DIR / f"{SYSTEMD_UNIT_NAME}.service"
SYSTEMD_TIMER_PATH = SYSTEMD_USER_DIR / f"{SYSTEMD_UNIT_NAME}.timer"

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


def _find_lydia_executable() -> str:
    path = shutil.which("lydia")
    if not path:
        raise ScheduleError("Could not find `lydia` on PATH. Pass an explicit lydia_path.")
    return path


def _backend(system: str | None = None) -> str:
    """Which scheduling backend applies to the current machine.

    Returns "launchd", "systemd", or raises ScheduleError for anything
    else (Windows, or a Linux without systemd on PATH).
    """
    system = system or platform.system()
    if system == "Darwin":
        return "launchd"
    if system == "Linux":
        if shutil.which("systemctl") is None:
            raise ScheduleError(
                "Scheduled briefings need systemd on Linux, but `systemctl` isn't on PATH."
            )
        return "systemd"
    raise ScheduleError(
        f"Scheduled briefings aren't supported on {system or 'this platform'} yet — "
        "only macOS (launchd) and Linux (systemd) are."
    )


# -- launchd (macOS) ----------------------------------------------------


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


def _enable_launchd(lydia_path: str, hour: int, minute: int, runner: Runner) -> Path:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_plist_contents(lydia_path, hour, minute), encoding="utf-8")
    result = runner(["launchctl", "load", str(PLIST_PATH)], capture_output=True, text=True)
    if result.returncode != 0:
        raise ScheduleError(f"launchctl load failed: {(result.stderr or result.stdout).strip()}")
    return PLIST_PATH


def _disable_launchd(runner: Runner) -> None:
    if not PLIST_PATH.is_file():
        return
    runner(["launchctl", "unload", str(PLIST_PATH)], capture_output=True, text=True)
    PLIST_PATH.unlink()


# -- systemd --user (Linux) ----------------------------------------------


def _systemd_service_contents(lydia_path: str) -> str:
    return f"""[Unit]
Description=Lydia daily briefing

[Service]
Type=oneshot
ExecStart={lydia_path} briefing run --notify
StandardOutput=append:{LOG_PATH}
StandardError=append:{LOG_PATH}
"""


def _systemd_timer_contents(hour: int, minute: int) -> str:
    return f"""[Unit]
Description=Run the Lydia daily briefing on a schedule

[Timer]
OnCalendar=*-*-* {hour:02d}:{minute:02d}:00
Persistent=true

[Install]
WantedBy=timers.target
"""


def _enable_systemd(lydia_path: str, hour: int, minute: int, runner: Runner) -> Path:
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYSTEMD_SERVICE_PATH.write_text(_systemd_service_contents(lydia_path), encoding="utf-8")
    SYSTEMD_TIMER_PATH.write_text(_systemd_timer_contents(hour, minute), encoding="utf-8")

    reload_result = runner(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
    if reload_result.returncode != 0:
        raise ScheduleError(
            f"systemctl --user daemon-reload failed: {(reload_result.stderr or reload_result.stdout).strip()}"
        )
    enable_result = runner(
        ["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT_NAME}.timer"],
        capture_output=True, text=True,
    )
    if enable_result.returncode != 0:
        raise ScheduleError(
            f"systemctl --user enable failed: {(enable_result.stderr or enable_result.stdout).strip()}"
        )
    return SYSTEMD_TIMER_PATH


def _disable_systemd(runner: Runner) -> None:
    if not SYSTEMD_TIMER_PATH.is_file():
        return
    runner(
        ["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT_NAME}.timer"],
        capture_output=True, text=True,
    )
    SYSTEMD_TIMER_PATH.unlink(missing_ok=True)
    SYSTEMD_SERVICE_PATH.unlink(missing_ok=True)


# -- public API -----------------------------------------------------------


def enable(
    time_str: str,
    lydia_path: str | None = None,
    runner: Runner = subprocess.run,
) -> Path:
    """Schedule the daily briefing for the given time. Returns the unit/plist path."""
    hour, minute = _parse_time(time_str)
    resolved_path = lydia_path or _find_lydia_executable()
    backend = _backend()
    if backend == "launchd":
        return _enable_launchd(resolved_path, hour, minute, runner)
    return _enable_systemd(resolved_path, hour, minute, runner)


def disable(runner: Runner = subprocess.run) -> None:
    system = platform.system()
    if system == "Darwin":
        _disable_launchd(runner)
        return
    if system == "Linux" and shutil.which("systemctl") is not None:
        _disable_systemd(runner)
        return
    # Nothing to disable on a platform that could never have enabled it.


def is_enabled() -> bool:
    return PLIST_PATH.is_file() or SYSTEMD_TIMER_PATH.is_file()

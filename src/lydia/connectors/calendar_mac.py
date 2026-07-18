"""Read upcoming events from macOS Calendar.

AppleScript via osascript: ships with macOS, no dependency, read-only. macOS
shows a one-time automation permission prompt for Calendar on first use. The
`whose` query is not fast, but a personal calendar over a few days is fine.
"""

from __future__ import annotations

import subprocess

from lydia.connectors.base import ConnectorError

_SCRIPT = """
set d1 to current date
set d2 to d1 + ({days} * days)
set out to ""
tell application "Calendar"
    repeat with c in calendars
        repeat with e in (every event of c whose start date is greater than or equal to d1 and start date is less than or equal to d2)
            set out to out & (summary of e) & "|" & ((start date of e) as string) & "|" & (location of e) & linefeed
        end repeat
    end repeat
end tell
return out
"""


def get_events(days: int = 2, runner=subprocess.run) -> str:
    days = max(1, min(int(days), 14))
    script = _SCRIPT.format(days=days)
    result = runner(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ConnectorError(
            "Calendar lookup failed: " + (result.stderr or "osascript error").strip()
            + " (if this mentions authorization, grant Calendar access in "
            "System Settings > Privacy & Security > Automation)"
        )
    lines = []
    for raw in result.stdout.splitlines():
        parts = raw.split("|")
        if len(parts) < 2 or not parts[0].strip():
            continue
        summary, start = parts[0].strip(), parts[1].strip()
        where = parts[2].strip() if len(parts) > 2 and parts[2].strip() not in ("", "missing value") else ""
        lines.append(f"- {summary} — {start}" + (f" ({where})" if where else ""))
    if not lines:
        return f"No events in the next {days} day(s)."
    return f"Events in the next {days} day(s):\n" + "\n".join(lines)

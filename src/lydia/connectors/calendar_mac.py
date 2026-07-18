"""Read upcoming events from macOS Calendar.

EventKit via JXA (osascript -l JavaScript): ships with macOS, no dependency,
read-only, and queries in milliseconds — the AppleScript `whose` query this
replaced could take minutes over iCloud/subscribed calendars. macOS shows a
one-time Calendar permission prompt for the invoking app on first use.
"""

from __future__ import annotations

import subprocess

from lydia.connectors.base import ConnectorError

_SCRIPT = """
ObjC.import("EventKit");
const store = $.EKEventStore.alloc.init;
const status = $.EKEventStore.authorizationStatusForEntityType($.EKEntityTypeEvent);
if (status === 1 || status === 2) throw new Error("calendar access denied");
const start = $.NSDate.date;
const end = $.NSDate.dateWithTimeIntervalSinceNow({days} * 86400);
const pred = store.predicateForEventsWithStartDateEndDateCalendars(start, end, $());
const events = ObjC.unwrap(store.eventsMatchingPredicate(pred)) || [];
const fmt = $.NSDateFormatter.alloc.init;
fmt.dateFormat = "EEE MMM d h:mm a";
const lines = events.map(e => {
  const title = e.title.js || "(untitled)";
  const when = fmt.stringFromDate(e.startDate).js || "";
  const where = e.location.js || "";
  return title + "|" + when + "|" + where;
});
lines.join("\\n");
"""


def get_events(days: int = 2, runner=subprocess.run) -> str:
    days = max(1, min(int(days), 14))
    script = _SCRIPT.replace("{days}", str(days))
    result = runner(["osascript", "-l", "JavaScript", "-e", script],
                    capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ConnectorError(
            "Calendar lookup failed: " + (result.stderr or "osascript error").strip()
            + " (if this mentions access or authorization, grant Calendar access in "
            "System Settings > Privacy & Security > Calendars)"
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
        return (f"No events in the next {days} day(s). (If your real calendar lives in "
                "Google/Outlook, add that account in System Settings > Internet Accounts "
                "with Calendars enabled so macOS Calendar syncs it.)")
    return f"Events in the next {days} day(s):\n" + "\n".join(lines)

"""Outlook / Microsoft 365 connector — read-only inbox summary via Microsoft Graph.

`transport` is injectable (an `httpx.BaseTransport`) for tests, same
pattern as the Canvas connector.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from lydia.connectors import ConnectorError

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


@dataclass
class EmailSummary:
    sender: str
    subject: str
    snippet: str
    unread: bool


def get_recent_emails(
    access_token: str,
    max_results: int = 10,
    transport: httpx.BaseTransport | None = None,
) -> list[EmailSummary]:
    params = {
        "$top": max_results,
        "$select": "from,subject,bodyPreview,isRead",
        "$orderby": "receivedDateTime desc",
    }
    try:
        with httpx.Client(
            base_url=GRAPH_BASE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
            transport=transport,
        ) as client:
            response = client.get("/me/messages", params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Outlook request failed: {exc}") from exc

    summaries: list[EmailSummary] = []
    for item in data.get("value", []):
        from_field = (item.get("from") or {}).get("emailAddress", {})
        sender = from_field.get("name") or from_field.get("address") or "unknown"
        summaries.append(EmailSummary(
            sender=sender,
            subject=item.get("subject") or "(no subject)",
            snippet=item.get("bodyPreview", ""),
            unread=not item.get("isRead", True),
        ))
    return summaries


def format_emails(summaries: list[EmailSummary]) -> str:
    if not summaries:
        return "No recent email."
    lines = []
    for s in summaries:
        flag = "UNREAD" if s.unread else "read"
        lines.append(f"- [{flag}] {s.sender}: {s.subject} — {s.snippet}")
    return "\n".join(lines)

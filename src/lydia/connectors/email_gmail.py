"""Gmail connector — read-only inbox summary via a stored OAuth credential.

`load_credentials`/`service_factory` are injectable so tests can supply
fakes instead of performing a real OAuth refresh or network call.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build as _build_gmail_service
from googleapiclient.errors import HttpError

from lydia.connectors import ConnectorError

SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)


@dataclass
class EmailSummary:
    sender: str
    subject: str
    snippet: str
    unread: bool


def _load_credentials(credentials_json: str) -> Credentials:
    creds = Credentials.from_authorized_user_info(json.loads(credentials_json), scopes=list(SCOPES))
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
    return creds


def get_recent_emails(
    credentials_json: str,
    max_results: int = 10,
    load_credentials: Callable[[str], Any] = _load_credentials,
    service_factory: Callable[..., Any] = _build_gmail_service,
) -> list[EmailSummary]:
    """The most recent inbox messages, flagged unread/read."""
    try:
        creds = load_credentials(credentials_json)
        service = service_factory("gmail", "v1", credentials=creds)
        listing = service.users().messages().list(
            userId="me", labelIds=["INBOX"], maxResults=max_results,
        ).execute()
        summaries: list[EmailSummary] = []
        for ref in listing.get("messages", []):
            msg = service.users().messages().get(
                userId="me", id=ref["id"], format="metadata",
                metadataHeaders=["From", "Subject"],
            ).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            summaries.append(EmailSummary(
                sender=headers.get("From", "unknown"),
                subject=headers.get("Subject", "(no subject)"),
                snippet=msg.get("snippet", ""),
                unread="UNREAD" in msg.get("labelIds", []),
            ))
        return summaries
    except HttpError as exc:
        raise ConnectorError(f"Gmail request failed: {exc}") from exc


def format_emails(summaries: list[EmailSummary]) -> str:
    if not summaries:
        return "No recent email."
    lines = []
    for s in summaries:
        flag = "UNREAD" if s.unread else "read"
        lines.append(f"- [{flag}] {s.sender}: {s.subject} — {s.snippet}")
    return "\n".join(lines)

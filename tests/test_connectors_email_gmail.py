"""Tests for the Gmail connector using a fake googleapiclient-shaped service."""

import pytest
from googleapiclient.errors import HttpError

from lydia.connectors import ConnectorError
from lydia.connectors.email_gmail import format_emails, get_recent_emails


class _FakeExecutable:
    def __init__(self, result: object) -> None:
        self._result = result

    def execute(self) -> object:
        return self._result


class _FakeMessages:
    def __init__(self, listing: dict, by_id: dict) -> None:
        self._listing = listing
        self._by_id = by_id

    def list(self, userId: str, labelIds: list[str], maxResults: int) -> _FakeExecutable:
        return _FakeExecutable(self._listing)

    def get(self, userId: str, id: str, format: str, metadataHeaders: list[str]) -> _FakeExecutable:
        return _FakeExecutable(self._by_id[id])


class _FakeUsers:
    def __init__(self, listing: dict, by_id: dict) -> None:
        self._messages = _FakeMessages(listing, by_id)

    def messages(self) -> _FakeMessages:
        return self._messages


class _FakeService:
    def __init__(self, listing: dict, by_id: dict) -> None:
        self._users = _FakeUsers(listing, by_id)

    def users(self) -> _FakeUsers:
        return self._users


def _headers(from_: str, subject: str) -> list[dict]:
    return [{"name": "From", "value": from_}, {"name": "Subject", "value": subject}]


def test_get_recent_emails_maps_messages() -> None:
    listing = {"messages": [{"id": "1"}, {"id": "2"}]}
    by_id = {
        "1": {"snippet": "hi there", "labelIds": ["INBOX", "UNREAD"],
              "payload": {"headers": _headers("a@example.com", "Hello")}},
        "2": {"snippet": "fyi", "labelIds": ["INBOX"],
              "payload": {"headers": _headers("b@example.com", "FYI")}},
    }
    summaries = get_recent_emails(
        "fake-credentials-json",
        load_credentials=lambda blob: None,
        service_factory=lambda *a, **k: _FakeService(listing, by_id),
    )
    assert len(summaries) == 2
    assert summaries[0].sender == "a@example.com"
    assert summaries[0].subject == "Hello"
    assert summaries[0].unread is True
    assert summaries[1].unread is False


def test_http_error_raises_connector_error() -> None:
    class _BrokenService:
        def users(self):
            raise HttpError(resp=type("R", (), {"status": 401, "reason": "unauthorized"})(), content=b"{}")

    with pytest.raises(ConnectorError):
        get_recent_emails(
            "fake-credentials-json",
            load_credentials=lambda blob: None,
            service_factory=lambda *a, **k: _BrokenService(),
        )


def test_format_emails_empty() -> None:
    assert format_emails([]) == "No recent email."


def test_format_emails_flags_unread() -> None:
    listing = {"messages": [{"id": "1"}]}
    by_id = {"1": {"snippet": "s", "labelIds": ["INBOX", "UNREAD"],
                   "payload": {"headers": _headers("a@example.com", "Subj")}}}
    summaries = get_recent_emails(
        "fake-credentials-json",
        load_credentials=lambda blob: None,
        service_factory=lambda *a, **k: _FakeService(listing, by_id),
    )
    assert "[UNREAD]" in format_emails(summaries)

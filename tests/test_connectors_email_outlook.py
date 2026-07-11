"""Tests for the Outlook connector using httpx.MockTransport (no real Graph API needed)."""

import httpx
import pytest

from lydia.connectors import ConnectorError
from lydia.connectors.email_outlook import format_emails, get_recent_emails


def test_get_recent_emails_maps_graph_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/me/messages"
        return httpx.Response(200, json={"value": [
            {"from": {"emailAddress": {"name": "Prof Smith", "address": "smith@school.edu"}},
             "subject": "Assignment posted", "bodyPreview": "See the new assignment...", "isRead": False},
            {"from": {"emailAddress": {"address": "noreply@school.edu"}},
             "subject": "Newsletter", "bodyPreview": "This week...", "isRead": True},
        ]})

    summaries = get_recent_emails("fake-token", transport=httpx.MockTransport(handler))
    assert len(summaries) == 2
    assert summaries[0].sender == "Prof Smith"
    assert summaries[0].unread is True
    assert summaries[1].sender == "noreply@school.edu"  # falls back to address, no name
    assert summaries[1].unread is False


def test_auth_header_sent() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"value": []})

    get_recent_emails("secret-token", transport=httpx.MockTransport(handler))
    assert captured["auth"] == "Bearer secret-token"


def test_http_error_raises_connector_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "InvalidAuthenticationToken"}})

    with pytest.raises(ConnectorError):
        get_recent_emails("bad-token", transport=httpx.MockTransport(handler))


def test_format_emails_empty() -> None:
    assert format_emails([]) == "No recent email."

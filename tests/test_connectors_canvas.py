"""Tests for the Canvas connector using httpx.MockTransport (no real Canvas needed)."""

import httpx
import pytest

from lydia.connectors import ConnectorError
from lydia.connectors.canvas import format_assignments, get_upcoming_assignments


def make_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_get_upcoming_assignments_across_courses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/courses":
            return httpx.Response(200, json=[
                {"id": 1, "name": "Data Structures"},
                {"id": 2, "name": "Algorithms"},
            ])
        if request.url.path == "/api/v1/courses/1/assignments":
            return httpx.Response(200, json=[
                {"name": "HW3", "due_at": "2026-07-15T23:59:00Z", "html_url": "http://x/1"},
            ])
        if request.url.path == "/api/v1/courses/2/assignments":
            return httpx.Response(200, json=[
                {"name": "Project 2", "due_at": "2026-07-12T23:59:00Z", "html_url": "http://x/2"},
            ])
        raise AssertionError(f"unexpected path {request.url.path}")

    assignments = get_upcoming_assignments(
        "https://school.instructure.com", "tok", transport=make_transport(handler),
    )
    assert [a.name for a in assignments] == ["Project 2", "HW3"]  # sorted by due date
    assert assignments[0].course_name == "Algorithms"


def test_auth_header_sent() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        if request.url.path == "/api/v1/courses":
            return httpx.Response(200, json=[])
        raise AssertionError("should not reach assignments endpoint with no courses")

    get_upcoming_assignments("https://school.instructure.com", "secret-token", transport=make_transport(handler))
    assert captured["auth"] == "Bearer secret-token"


def test_http_error_raises_connector_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errors": [{"message": "not authorized"}]})

    with pytest.raises(ConnectorError):
        get_upcoming_assignments("https://school.instructure.com", "bad-token", transport=make_transport(handler))


def test_format_assignments_empty() -> None:
    assert format_assignments([]) == "No upcoming assignments."

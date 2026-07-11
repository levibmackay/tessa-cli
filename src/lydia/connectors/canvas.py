"""Canvas LMS connector — upcoming assignments, read-only via a personal access token.

`transport` is injectable (an `httpx.BaseTransport`) so tests can supply an
`httpx.MockTransport` instead of hitting a real Canvas instance, mirroring
the pattern already used for the Ollama client tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from lydia.connectors import ConnectorError


@dataclass
class Assignment:
    course_name: str
    name: str
    due_at: str | None
    html_url: str


def _get_json(client: httpx.Client, path: str, params: dict | None = None) -> object:
    try:
        response = client.get(path, params=params)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Canvas request to {path} failed: {exc}") from exc
    return response.json()


def get_upcoming_assignments(
    base_url: str,
    token: str,
    transport: httpx.BaseTransport | None = None,
) -> list[Assignment]:
    """Assignments due soon, across all of the user's active courses."""
    with httpx.Client(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
        transport=transport,
    ) as client:
        courses = _get_json(client, "/api/v1/courses", params={"enrollment_state": "active", "per_page": 50})
        assignments: list[Assignment] = []
        for course in courses:
            course_id = course.get("id")
            if course_id is None:
                continue
            course_name = course.get("name") or course.get("course_code") or f"Course {course_id}"
            items = _get_json(
                client, f"/api/v1/courses/{course_id}/assignments",
                params={"bucket": "upcoming", "per_page": 50},
            )
            for item in items:
                assignments.append(Assignment(
                    course_name=course_name,
                    name=item.get("name") or "Untitled assignment",
                    due_at=item.get("due_at"),
                    html_url=item.get("html_url", ""),
                ))
    assignments.sort(key=lambda a: a.due_at or "9999")
    return assignments


def format_assignments(assignments: list[Assignment]) -> str:
    if not assignments:
        return "No upcoming assignments."
    lines = []
    for a in assignments:
        due = a.due_at or "no due date"
        lines.append(f"- [{a.course_name}] {a.name} (due {due})")
    return "\n".join(lines)

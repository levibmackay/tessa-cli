"""Automation recipes: dataclasses, validation, (de)serialization.

A recipe is one JSON file at ~/.lydia/automations/<name>.json (see store.py).
Kept UI-free and I/O-free so it's trivially unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

# Only safe-risk connector tools may appear as steps — an automation must
# never be able to edit files or run shell commands (that's the deferred
# "unattended coding" spec, not this one).
ALLOWED_STEP_TOOLS = {"check_email", "check_canvas", "check_stocks", "check_news"}
EVENT_SOURCES = {"email", "canvas"}
EMAIL_ACCOUNTS = {"personal", "school"}
# A model step ends its reply with this exact marker to suppress an
# `if_important` notification. String check, not a second model call.
NOTHING_TO_REPORT = "NOTHING_TO_REPORT"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class AutomationError(Exception):
    """A recipe is malformed or could not be loaded/saved."""


@dataclass
class Trigger:
    type: str  # "schedule" | "interval" | "event"
    time: str | None = None        # schedule: 24h "HH:MM", local time
    minutes: int | None = None     # interval
    source: str | None = None      # event: one of EVENT_SOURCES
    account: str | None = None     # event+email: "personal" | "school"
    condition: str | None = None   # event: English, evaluated by the model


@dataclass
class Step:
    kind: str  # "connector" | "model"
    tool: str | None = None                      # connector
    args: dict[str, Any] = field(default_factory=dict)  # connector
    instructions: str | None = None              # model


@dataclass
class Notify:
    channel: str = "ntfy"  # "ntfy" | "mac" | "none"
    when: str = "always"   # "always" | "if_important"


@dataclass
class Automation:
    name: str
    description: str
    trigger: Trigger
    steps: list[Step]
    notify: Notify = field(default_factory=Notify)
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Automation":
        try:
            return cls(
                name=data["name"],
                description=data.get("description", ""),
                trigger=Trigger(**data["trigger"]),
                steps=[Step(**s) for s in data["steps"]],
                notify=Notify(**data.get("notify", {})),
                enabled=bool(data.get("enabled", True)),
            )
        except (KeyError, TypeError) as exc:
            raise AutomationError(f"Malformed automation: {exc}") from exc


def validate(auto: Automation) -> list[str]:
    """Every problem with the recipe, as human/model-readable strings."""
    errors: list[str] = []
    if not _NAME_RE.match(auto.name or ""):
        errors.append("name must be a lowercase-kebab slug, e.g. 'morning-briefing'")

    t = auto.trigger
    if t.type == "schedule":
        if not (t.time and _TIME_RE.match(t.time)):
            errors.append("schedule trigger needs a 24-hour time 'HH:MM', e.g. '08:00'")
    elif t.type == "interval":
        if not (isinstance(t.minutes, int) and t.minutes >= 5):
            errors.append("interval trigger needs integer minutes >= 5")
    elif t.type == "event":
        if t.source not in EVENT_SOURCES:
            errors.append(f"event source must be one of: {', '.join(sorted(EVENT_SOURCES))}")
        if t.source == "email" and t.account not in EMAIL_ACCOUNTS:
            errors.append("event source 'email' needs account 'personal' or 'school'")
        if not (t.condition and t.condition.strip()):
            errors.append("event trigger needs an English condition, e.g. 'from my professor'")
    else:
        errors.append("trigger type must be 'schedule', 'interval', or 'event'")

    if not auto.steps:
        errors.append("at least one step is required")
    for i, step in enumerate(auto.steps, 1):
        if step.kind == "connector":
            if step.tool not in ALLOWED_STEP_TOOLS:
                errors.append(
                    f"step {i}: tool '{step.tool}' is not allowed; "
                    f"choose from {', '.join(sorted(ALLOWED_STEP_TOOLS))}"
                )
        elif step.kind == "model":
            if not (step.instructions and step.instructions.strip()):
                errors.append(f"step {i}: model step needs non-empty instructions")
        else:
            errors.append(f"step {i}: kind must be 'connector' or 'model'")

    if auto.notify.channel not in {"ntfy", "mac", "none"}:
        errors.append("notify channel must be 'ntfy', 'mac', or 'none'")
    if auto.notify.when not in {"always", "if_important"}:
        errors.append("notify when must be 'always' or 'if_important'")
    if auto.notify.when == "if_important" and not any(s.kind == "model" for s in auto.steps):
        errors.append("notify 'if_important' requires at least one model step "
                      "(nothing else can emit the NOTHING_TO_REPORT marker)")
    return errors


def describe(auto: Automation) -> str:
    """Human-readable echo shown before saving, e.g. by `lydia automate`."""
    t = auto.trigger
    if t.type == "schedule":
        when = f"Every day at {t.time}"
    elif t.type == "interval":
        when = f"Every {t.minutes} minutes"
    else:
        where = f"{t.source} ({t.account})" if t.account else t.source
        when = f"When new {where} items match: \"{t.condition}\""
    parts = []
    for step in auto.steps:
        if step.kind == "connector":
            parts.append(step.tool or "?")
        else:
            text = (step.instructions or "").strip()
            parts.append(f"model: {text[:60]}" + ("…" if len(text) > 60 else ""))
    if auto.notify.channel == "ntfy":
        dest = "push to phone (ntfy)"
    elif auto.notify.channel == "mac":
        dest = "Mac notification"
    else:
        dest = "no notification"
    if auto.notify.when == "if_important":
        dest += ", only if important"
    return f"[{auto.name}] {when}: {' → '.join(parts)} → {dest}"

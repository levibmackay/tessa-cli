"""Execute automations: due-ness, steps, event polling, the heartbeat tick.

The tick is invoked by launchd every ~5 minutes (`lydia automations tick`).
Model/client/now/handlers are all injected so everything here is testable
with fakes. Layering: never import cli/ — notifications go through
connectors/ntfy.py or osascript directly, confirm callbacks always decline
(only safe-risk tools are reachable, so confirm is never actually called).
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from lydia.agent.tools import ToolContext, build_registry
from lydia.automations import store
from lydia.automations.model import (
    ALLOWED_STEP_TOOLS, Automation, AutomationError, NOTHING_TO_REPORT, Trigger,
)
from lydia.automations.parser import complete
from lydia.config.settings import LydiaConfig
from lydia.llm.protocol import ModelClient
from lydia.llm.types import Message

logger = logging.getLogger(__name__)

FAILURE_NOTICE_INTERVAL_HOURS = 6

MODEL_STEP_SYSTEM_PROMPT = (
    "You are Lydia, running an unattended scheduled automation for your user. "
    "Work ONLY from the data sections provided — never invent information. "
    "Be concise: the result may be sent as a phone notification."
)
IF_IMPORTANT_SUFFIX = (
    " If there is nothing worth notifying the user about, end your reply with "
    f"the exact word {NOTHING_TO_REPORT}."
)
CONDITION_PROMPT = (
    "Below are NEW items. Decide whether ANY of them matches this condition: "
    "{condition}\n\nItems:\n{items}\n\nReply with exactly MATCH or NO_MATCH."
)


def _connector_handlers() -> dict[str, Callable]:
    return {spec.name: spec.handler for spec in build_registry()
            if spec.name in ALLOWED_STEP_TOOLS}


def _ctx(config: LydiaConfig) -> ToolContext:
    return ToolContext(root=Path.home(), config=config, confirm=lambda _r: False)


def is_due(auto: Automation, state_entry: dict, now: datetime) -> bool:
    t = auto.trigger
    last_raw = state_entry.get("last_run")
    last = datetime.fromisoformat(last_raw) if last_raw else None
    if t.type == "schedule":
        hour, minute = (int(p) for p in t.time.split(":"))
        if (now.hour, now.minute) < (hour, minute):
            return False
        return last is None or last.date() < now.date()
    if t.type == "interval":
        return last is None or (now - last) >= timedelta(minutes=t.minutes)
    return False  # events are polled every tick, not "due"


def execute(auto: Automation, config: LydiaConfig, client: ModelClient, model: str,
            extra_sections: list[tuple[str, str]] | None = None,
            handlers: dict | None = None) -> str:
    handlers = handlers if handlers is not None else _connector_handlers()
    ctx = _ctx(config)
    sections: list[tuple[str, str]] = list(extra_sections or [])
    result_text = ""
    for step in auto.steps:
        if step.kind == "connector":
            result = handlers[step.tool](step.args, ctx)
            sections.append((step.tool, result.content))
        else:
            system = MODEL_STEP_SYSTEM_PROMPT
            if auto.notify.when == "if_important":
                system += IF_IMPORTANT_SUFFIX
            data = "\n\n".join(f"## {label}\n{content}" for label, content in sections)
            prompt = (f"Data gathered for automation '{auto.name}':\n\n{data}\n\n"
                      f"Instructions: {step.instructions}")
            result_text = complete(client, model, config, [
                Message(role="system", content=system),
                Message(role="user", content=prompt),
            ])
            sections.append(("model", result_text))
    if not result_text:
        result_text = "\n\n".join(f"## {label}\n{content}" for label, content in sections)
    return result_text


def _send_ntfy(title: str, message: str, priority: str = "default") -> None:
    from lydia.config import secrets
    from lydia.connectors import ntfy

    topic = secrets.get_secret(secrets.NTFY_TOPIC)
    if not topic:
        logger.warning("ntfy not configured; run `lydia auth login ntfy`")
        return
    ntfy.send_push(topic, title, message, priority=priority)


def _mac_notify(message: str, subtitle: str) -> None:
    script = (f'display notification {json.dumps(message[:200])} '
              f'with title "Lydia" subtitle {json.dumps(subtitle)}')
    subprocess.run(["osascript", "-e", script], check=False)


def _notify(auto: Automation, result_text: str) -> bool:
    if auto.notify.channel == "none":
        return False
    if auto.notify.when == "if_important" and result_text.strip().endswith(NOTHING_TO_REPORT):
        return False
    body = result_text.replace(NOTHING_TO_REPORT, "").strip()[:1000]
    if auto.notify.channel == "ntfy":
        _send_ntfy(f"Lydia · {auto.name}", body)
    else:
        _mac_notify(body, auto.name)
    return True


def run_one(auto: Automation, config: LydiaConfig, client: ModelClient, model: str,
            now: datetime, state: dict,
            extra_sections: list[tuple[str, str]] | None = None,
            handlers: dict | None = None) -> dict:
    started = now.isoformat()
    result_text = execute(auto, config, client, model,
                          extra_sections=extra_sections, handlers=handlers)
    notified = _notify(auto, result_text)
    entry = state.setdefault(auto.name, {})
    entry["last_run"] = now.isoformat()
    return {"name": auto.name, "started_at": started, "duration_seconds": 0.0,
            "ok": True, "error": None,
            "result_snippet": result_text[:200], "notified": notified}


def poll_new_items(trigger: Trigger, config: LydiaConfig) -> list[tuple[str, str]]:
    """(stable_id, one-line text) for every current item at the event source."""
    from lydia.config import secrets

    if trigger.source == "email" and trigger.account == "personal":
        from lydia.connectors.email_gmail import get_recent_emails

        creds = secrets.get_secret(secrets.GMAIL_REFRESH_TOKEN)
        if not creds:
            raise AutomationError("Gmail isn't connected (`lydia auth login gmail`)")
        return [(s.id, f"[{'UNREAD' if s.unread else 'read'}] {s.sender}: {s.subject} — {s.snippet}")
                for s in get_recent_emails(creds)]
    if trigger.source == "email" and trigger.account == "school":
        from lydia.connectors.auth import outlook_oauth
        from lydia.connectors.email_outlook import get_recent_emails

        token = outlook_oauth.get_access_token()
        return [(s.id, f"[{'UNREAD' if s.unread else 'read'}] {s.sender}: {s.subject} — {s.snippet}")
                for s in get_recent_emails(token)]
    if trigger.source == "canvas":
        from lydia.connectors.canvas import get_upcoming_assignments

        base_url = config.canvas_base_url
        token = secrets.get_secret(secrets.CANVAS_TOKEN)
        if not base_url or not token:
            raise AutomationError("Canvas isn't set up (`lydia auth login canvas`)")
        return [(a.id, f"{a.course_name}: {a.name} (due {a.due_at or 'n/a'})")
                for a in get_upcoming_assignments(base_url, token)]
    raise AutomationError(f"Unknown event source '{trigger.source}'")


def _matches(condition: str, items: list[tuple[str, str]],
             config: LydiaConfig, client: ModelClient, model: str) -> bool:
    listing = "\n".join(f"- {text}" for _id, text in items)
    reply = complete(client, model, config, [
        Message(role="user", content=CONDITION_PROMPT.format(condition=condition, items=listing)),
    ])
    return "MATCH" in reply and "NO_MATCH" not in reply


def _record_failure(auto: Automation, exc: Exception, now: datetime, state: dict) -> dict:
    logger.warning("Automation %s failed: %s", auto.name, exc)
    entry = state.setdefault(auto.name, {})
    entry["last_run"] = now.isoformat()
    last_notice_raw = entry.get("last_failure_notice")
    notice_due = (last_notice_raw is None or
                  now - datetime.fromisoformat(last_notice_raw)
                  >= timedelta(hours=FAILURE_NOTICE_INTERVAL_HOURS))
    if notice_due:
        try:
            _send_ntfy(f"Lydia · {auto.name} failed", str(exc)[:500], priority="high")
            entry["last_failure_notice"] = now.isoformat()
        except Exception:  # noqa: BLE001 - a broken push must not kill the tick
            logger.warning("Failure notice for %s could not be sent", auto.name)
    return {"name": auto.name, "started_at": now.isoformat(), "duration_seconds": 0.0,
            "ok": False, "error": str(exc), "result_snippet": "", "notified": False}


def tick(config: LydiaConfig, client: ModelClient, model: str,
         now: datetime | None = None, handlers: dict | None = None) -> list[dict]:
    now = now or datetime.now()
    if not store.try_acquire_lock():
        logger.info("Another tick is running; skipping")
        return []
    results: list[dict] = []
    try:
        state = store.load_state()
        for auto in store.list_automations():
            if not auto.enabled:
                continue
            try:
                if auto.trigger.type == "event":
                    record = _tick_event(auto, config, client, model, now, state,
                                         handlers=handlers)
                elif is_due(auto, state.get(auto.name, {}), now):
                    record = run_one(auto, config, client, model, now, state,
                                     handlers=handlers)
                else:
                    record = None
            except Exception as exc:  # noqa: BLE001 - one bad automation must not stop the rest
                record = _record_failure(auto, exc, now, state)
            if record is not None:
                results.append(record)
                store.append_run(record)
        store.save_state(state)
    finally:
        store.release_lock()
    return results


def _tick_event(auto: Automation, config: LydiaConfig, client: ModelClient,
                model: str, now: datetime, state: dict,
                handlers: dict | None = None) -> dict | None:
    items = poll_new_items(auto.trigger, config)
    entry = state.setdefault(auto.name, {})
    if "seen_ids" not in entry:
        # First poll ever: seed silently so creating an automation doesn't
        # alert about everything already in the inbox.
        entry["seen_ids"] = [i for i, _t in items][-store.MAX_SEEN_IDS:]
        entry["last_run"] = now.isoformat()
        return None
    seen = set(entry["seen_ids"])
    new = [(i, t) for i, t in items if i not in seen]
    entry["seen_ids"] = (entry["seen_ids"] + [i for i, _t in new])[-store.MAX_SEEN_IDS:]
    entry["last_run"] = now.isoformat()
    if not new:
        return None
    if not _matches(auto.trigger.condition, new, config, client, model):
        return None
    section = ("new items", "\n".join(f"- {t}" for _i, t in new))
    return run_one(auto, config, client, model, now, state, extra_sections=[section],
                   handlers=handlers)

"""Turn an English automation request into a validated recipe via one model turn.

The model only runs at creation time — scheduled runs never re-parse. On
invalid output the validation errors are fed back for exactly one retry
(small local models get JSON wrong sometimes; more than one retry just
burns time on a request that isn't going to work).
"""

from __future__ import annotations

import json

from lydia.automations.model import Automation, AutomationError, validate
from lydia.config.settings import LydiaConfig
from lydia.llm.protocol import ModelClient
from lydia.llm.types import Message

PARSER_SYSTEM_PROMPT = """You convert a user's English request into an automation recipe as JSON.

Reply with ONLY a JSON object — no prose, no markdown fences — in exactly this shape:

{
  "name": "<lowercase-kebab-slug, max 50 chars>",
  "description": "<the user's original request, verbatim>",
  "enabled": true,
  "trigger": <one of:
    {"type": "schedule", "time": "HH:MM"}                              — daily at a fixed 24-hour local time
    {"type": "interval", "minutes": <int >= 5>}                        — repeating
    {"type": "event", "source": "email"|"canvas", "account": "personal"|"school", "condition": "<English>"}
                                                                        — fire only on NEW items matching the condition
  >,
  "steps": [  — executed in order
    {"kind": "connector", "tool": "check_email"|"check_canvas"|"check_stocks"|"check_news", "args": {...}}
    {"kind": "model", "instructions": "<what to do with the gathered data>"}
  ],
  "notify": {"channel": "ntfy"|"mac"|"none", "when": "always"|"if_important"}
}

Rules:
- check_email requires args {"account": "personal"} (Gmail) or {"account": "school"} (Outlook). Other tools take args {}.
- "event" triggers: "account" is only for source "email"; omit it for "canvas".
- If the user wants a summary/briefing/decision, end steps with one "model" step.
- Default notify is {"channel": "ntfy", "when": "always"}. Use "if_important" only when the user says things like "only if", "when something matters".
- "if_important" requires at least one "model" step.

Example — "every morning at 8 check my email and canvas and send me a briefing":
{"name": "morning-briefing", "description": "every morning at 8 check my email and canvas and send me a briefing", "enabled": true,
 "trigger": {"type": "schedule", "time": "08:00"},
 "steps": [{"kind": "connector", "tool": "check_email", "args": {"account": "personal"}},
           {"kind": "connector", "tool": "check_canvas", "args": {}},
           {"kind": "model", "instructions": "Summarize the email and Canvas data into a short morning briefing with a checklist."}],
 "notify": {"channel": "ntfy", "when": "always"}}

Example — "let me know when my professor emails me":
{"name": "professor-email-alert", "description": "let me know when my professor emails me", "enabled": true,
 "trigger": {"type": "event", "source": "email", "account": "school", "condition": "the email is from the user's professor"},
 "steps": [{"kind": "model", "instructions": "Summarize the new matching email(s) in one or two sentences."}],
 "notify": {"channel": "ntfy", "when": "always"}}"""


class AutomationParseError(Exception):
    """The model could not produce a valid recipe from the request."""


def complete(client: ModelClient, model: str, config: LydiaConfig,
             messages: list[Message]) -> str:
    """One silent chat turn: drain the stream, return concatenated content."""
    parts: list[str] = []
    for chunk in client.chat_stream(
        model=model, messages=messages, temperature=0.2,
        num_ctx=config.num_ctx, think=config.think_flag,
        keep_alive=config.keep_alive,
    ):
        if chunk.content:
            parts.append(chunk.content)
    return "".join(parts)


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise json.JSONDecodeError("no JSON object found", raw, 0)
    return json.loads(text[start:end + 1])


def parse_automation(text: str, client: ModelClient, model: str,
                     config: LydiaConfig) -> Automation:
    messages = [
        Message(role="system", content=PARSER_SYSTEM_PROMPT),
        Message(role="user", content=text),
    ]
    raw = complete(client, model, config, messages)
    problem = ""
    for attempt in range(2):
        try:
            auto = Automation.from_dict(_extract_json(raw))
            errors = validate(auto)
            if not errors:
                return auto
            problem = "; ".join(errors)
        except (json.JSONDecodeError, AutomationError) as exc:
            problem = str(exc)
        if attempt == 0:
            messages = messages + [
                Message(role="assistant", content=raw),
                Message(role="user", content=(
                    f"That JSON was invalid: {problem}. "
                    "Reply with ONLY the corrected JSON object.")),
            ]
            raw = complete(client, model, config, messages)
    raise AutomationParseError(
        f"Couldn't turn that into an automation ({problem}). "
        "Try rephrasing — e.g. 'every morning at 8, check my email and send me a summary'.")

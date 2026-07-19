"""src/lydia/voice/assistant.py — the wake → listen → think → speak loop.

Every stage is injected: `frames` (mic), `wake`, `transcriber`, `speak_fn`,
`chime_fn`. cli/main.py wires the real ones; tests wire fakes. Never
imports cli/ (same layering rule as automations/).
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from lydia.agent.loop import run_agent_turn
from lydia.agent.tools import ToolContext, ToolSpec, build_registry
from lydia.config.settings import LydiaConfig
from lydia.llm.client import OllamaError
from lydia.llm.protocol import ModelClient
from lydia.llm.types import Message
from lydia.voice import audio

logger = logging.getLogger(__name__)

VOICE_TOOLS = {
    "check_email", "check_canvas", "check_stocks", "check_news", "notify",
    "check_weather", "check_calendar", "open_app", "find_files", "read_file",
}

VOICE_SYSTEM_PROMPT = (
    "You are Lydia, a spoken voice assistant. The user talked to you out loud "
    "and your reply will be read aloud by text-to-speech. Answer in one to "
    "three short sentences of plain conversational prose — no markdown, no "
    "lists, no code, no emoji. You have tools for live data (email, Canvas, "
    "calendar, weather, stocks, news), for finding and reading the user's "
    "files, and for opening apps or files — use them whenever the request "
    "needs them, without asking permission. Otherwise just answer."
)

_CHIMES = {"wake": "/System/Library/Sounds/Glass.aiff",
           "miss": "/System/Library/Sounds/Basso.aiff"}


def voice_registry() -> list[ToolSpec]:
    return [spec for spec in build_registry() if spec.name in VOICE_TOOLS]


def play_chime(kind: str) -> None:
    subprocess.run(["afplay", _CHIMES[kind]], check=False)


HISTORY_MAX_MESSAGES = 12  # last 6 exchanges


def run_loop(config: LydiaConfig, client: ModelClient, model: str, *,
             frames, wake, transcriber, speak_fn, chime_fn,
             flush_fn=lambda: None, max_turns: int | None = None,
             history_ttl: float = 300.0, now_fn=time.monotonic) -> None:
    registry = voice_registry()
    ctx = ToolContext(root=Path.home(), config=config, confirm=lambda _r: False,
                      client=client)
    turns = 0
    history: list[Message] = []  # rolling context so follow-ups work
    last_turn: float | None = None
    for frame in frames:
        if max_turns is not None and turns >= max_turns:
            return
        if not wake.process(frame):
            continue
        turns += 1
        chime_fn("wake")
        flush_fn()  # drop audio buffered during the chime
        pcm = audio.record_until_silence(lambda: next(frames))
        start = time.perf_counter()
        text = transcriber.transcribe(pcm).strip()
        if not text:
            chime_fn("miss")
            flush_fn()
            continue
        logger.info("Heard (stt %.1fs): %s", time.perf_counter() - start, text)
        now = now_fn()
        if last_turn is not None and now - last_turn > history_ttl:
            history.clear()
        last_turn = now
        history.append(Message(role="user", content=text))
        start = time.perf_counter()
        try:
            reply, _stats = run_agent_turn(
                client=client, model=model,
                temperature=config.temperature, num_ctx=config.num_ctx,
                think=False, keep_alive=config.keep_alive,
                system_prompt=VOICE_SYSTEM_PROMPT,
                messages=list(history),
                registry=registry, ctx=ctx,
            )
        except OllamaError:
            history.pop()
            speak_fn("I can't reach my brain right now.")
            flush_fn()
            continue
        except Exception:  # noqa: BLE001 - the loop must survive anything
            history.pop()
            logger.exception("Voice turn failed")
            speak_fn("Something went wrong with that one.")
            flush_fn()
            continue
        logger.info("Reply (llm %.1fs): %s", time.perf_counter() - start, reply)
        if reply.strip():
            history.append(Message(role="assistant", content=reply))
            del history[:-HISTORY_MAX_MESSAGES]
            speak_fn(reply)
        flush_fn()  # drop audio buffered while Lydia was speaking

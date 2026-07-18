"""src/lydia/voice/assistant.py — the wake → listen → think → speak loop.

Every stage is injected: `frames` (mic), `wake`, `transcriber`, `speak_fn`,
`chime_fn`. cli/main.py wires the real ones; tests wire fakes. Never
imports cli/ (same layering rule as automations/).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from lydia.agent.loop import run_agent_turn
from lydia.agent.tools import ToolContext, ToolSpec, build_registry
from lydia.config.settings import LydiaConfig
from lydia.llm.client import OllamaError
from lydia.llm.protocol import ModelClient
from lydia.llm.types import Message
from lydia.voice import audio

logger = logging.getLogger(__name__)

VOICE_TOOLS = {"check_email", "check_canvas", "check_stocks", "check_news", "notify"}

VOICE_SYSTEM_PROMPT = (
    "You are Lydia, a spoken voice assistant. The user talked to you out loud "
    "and your reply will be read aloud by text-to-speech. Answer in one to "
    "three short sentences of plain conversational prose — no markdown, no "
    "lists, no code, no emoji. Use your tools when the question needs live "
    "data (email, Canvas, stocks, news); otherwise just answer."
)

_CHIMES = {"wake": "/System/Library/Sounds/Glass.aiff",
           "miss": "/System/Library/Sounds/Basso.aiff"}


def voice_registry() -> list[ToolSpec]:
    return [spec for spec in build_registry() if spec.name in VOICE_TOOLS]


def play_chime(kind: str) -> None:
    subprocess.run(["afplay", _CHIMES[kind]], check=False)


def run_loop(config: LydiaConfig, client: ModelClient, model: str, *,
             frames, wake, transcriber, speak_fn, chime_fn,
             max_turns: int | None = None) -> None:
    registry = voice_registry()
    ctx = ToolContext(root=Path.home(), config=config, confirm=lambda _r: False,
                      client=client)
    turns = 0
    for frame in frames:
        if max_turns is not None and turns >= max_turns:
            return
        if not wake.process(frame):
            continue
        turns += 1
        chime_fn("wake")
        pcm = audio.record_until_silence(lambda: next(frames))
        text = transcriber.transcribe(pcm).strip()
        if not text:
            chime_fn("miss")
            continue
        logger.info("Heard: %s", text)
        try:
            reply, _stats = run_agent_turn(
                client=client, model=model,
                temperature=config.temperature, num_ctx=config.num_ctx,
                think=config.think_flag, keep_alive=config.keep_alive,
                system_prompt=VOICE_SYSTEM_PROMPT,
                messages=[Message(role="user", content=text)],
                registry=registry, ctx=ctx,
            )
        except OllamaError:
            speak_fn("I can't reach my brain right now.")
            continue
        except Exception:  # noqa: BLE001 - the loop must survive anything
            logger.exception("Voice turn failed")
            speak_fn("Something went wrong with that one.")
            continue
        if reply.strip():
            speak_fn(reply)

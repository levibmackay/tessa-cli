"""src/lydia/voice/tts.py — speak text aloud via macOS `say`.

Markdown/emoji are stripped first: the model sometimes formats despite the
voice prompt, and `say` reads asterisks aloud ("asterisk asterisk bold").
"""

from __future__ import annotations

import re
import subprocess

_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE = re.compile(r"[*_`#]+")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\U00002190-\U000021FF️]"
)


def strip_for_speech(text: str) -> str:
    text = _CODE_BLOCK.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _BULLET.sub("", text)
    text = _INLINE.sub("", text)
    text = _EMOJI.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def speak(text: str, voice: str | None = None, runner=subprocess.run) -> None:
    clean = strip_for_speech(text)
    if not clean:
        return
    argv = ["say"] + (["-v", voice] if voice else []) + [clean]
    runner(argv, check=False)

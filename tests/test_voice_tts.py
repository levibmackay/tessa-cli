"""tests/test_voice_tts.py"""
from lydia.voice import tts


def test_strip_removes_markdown():
    text = "**Bold** and `code` and [a link](http://x.com) and # Heading\n- item one"
    out = tts.strip_for_speech(text)
    for bad in ("**", "`", "](", "#", "- "):
        assert bad not in out
    assert "Bold" in out and "code" in out and "a link" in out and "item one" in out


def test_strip_drops_code_blocks_and_emoji():
    text = "Before\n```python\nx = 1\n```\nAfter 🎉"
    out = tts.strip_for_speech(text)
    assert "x = 1" not in out and "🎉" not in out
    assert "Before" in out and "After" in out


def test_speak_invokes_say_with_voice():
    calls = []
    tts.speak("hello there", voice="Samantha", runner=lambda argv, **kw: calls.append(argv))
    assert calls == [["say", "-v", "Samantha", "hello there"]]


def test_speak_without_voice_and_empty_text():
    calls = []
    tts.speak("hi", runner=lambda argv, **kw: calls.append(argv))
    assert calls == [["say", "hi"]]
    tts.speak("   ", runner=lambda argv, **kw: calls.append(argv))
    assert len(calls) == 1  # empty after strip: no call

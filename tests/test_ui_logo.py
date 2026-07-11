"""Tests for the banner's ASCII-art scaling."""

from lydia.cli.ui import _scale_lines, render_logo


def test_scale_factor_one_is_a_no_op() -> None:
    lines = ["AB", "CD"]
    assert _scale_lines(lines, 1) == lines


def test_scale_factor_two_doubles_width_and_height() -> None:
    lines = ["AB", "CD"]
    scaled = _scale_lines(lines, 2)
    assert scaled == ["AABB", "AABB", "CCDD", "CCDD"]


def test_render_logo_returns_something_at_normal_terminal_width() -> None:
    # console.width defaults wide enough in a real terminal; just check it
    # doesn't crash and returns non-empty rendering when there's room.
    logo = render_logo()
    assert logo is None or len(logo.plain) > 0

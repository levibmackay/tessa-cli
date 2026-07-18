"""Tests for the macOS Calendar connector (no live osascript calls)."""

import subprocess

import pytest

from lydia.connectors.base import ConnectorError
from lydia.connectors.calendar_mac import get_events

RAW = "CS 452 Lecture|Monday, July 20, 2026 at 10:00:00 AM|Boise State\nDentist|Tuesday, July 21, 2026 at 2:30:00 PM|\n"


def _runner(stdout, returncode=0, stderr=""):
    def run(cmd, **kwargs):
        assert cmd[0] == "osascript"
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
    return run


def test_formats_events():
    out = get_events(days=3, runner=_runner(RAW))
    assert "CS 452 Lecture" in out and "Dentist" in out and "Boise State" in out


def test_no_events_message():
    out = get_events(runner=_runner(""))
    assert "No events" in out


def test_osascript_failure_raises():
    with pytest.raises(ConnectorError, match="Calendar"):
        get_events(runner=_runner("", returncode=1, stderr="Not authorized"))


def test_days_out_of_range_clamped():
    seen = {}
    def run(cmd, **kwargs):
        seen["script"] = cmd[-1]
        return subprocess.CompletedProcess(cmd, 0, "", "")
    get_events(days=99, runner=run)
    assert "14 * 86400" in seen["script"]

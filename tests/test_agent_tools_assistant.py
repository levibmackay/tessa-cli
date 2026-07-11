"""Tests for the personal-assistant tool handlers (check_email/canvas/stocks/news)."""

from pathlib import Path

from lydia.agent.tools import ToolContext, build_registry
from lydia.config.settings import LydiaConfig


def get(name: str):
    return next(t for t in build_registry() if t.name == name)


def ctx(tmp_path: Path, config: LydiaConfig | None = None) -> ToolContext:
    return ToolContext(root=tmp_path, config=config or LydiaConfig(), confirm=lambda req: True)


def test_check_stocks_success(tmp_path, monkeypatch) -> None:
    import lydia.connectors.stocks as stocks_mod

    fake = [stocks_mod.IndexSnapshot(symbol="^GSPC", name="S&P 500", price=100.0, change_pct=1.0)]
    monkeypatch.setattr(stocks_mod, "get_market_summary", lambda: fake)
    result = get("check_stocks").handler({}, ctx(tmp_path))
    assert result.ok
    assert "S&P 500" in result.content


def test_check_stocks_error(tmp_path, monkeypatch) -> None:
    import lydia.connectors.stocks as stocks_mod
    from lydia.connectors import ConnectorError

    def boom() -> None:
        raise ConnectorError("no network")

    monkeypatch.setattr(stocks_mod, "get_market_summary", boom)
    result = get("check_stocks").handler({}, ctx(tmp_path))
    assert not result.ok
    assert "no network" in result.content


def test_check_news_success(tmp_path, monkeypatch) -> None:
    import lydia.connectors.news as news_mod

    fake = [news_mod.NewsItem(title="AI thing", link="http://x", source="Test", published="")]
    monkeypatch.setattr(news_mod, "get_ai_news", lambda: fake)
    result = get("check_news").handler({}, ctx(tmp_path))
    assert result.ok
    assert "AI thing" in result.content


def test_check_canvas_not_configured(tmp_path) -> None:
    result = get("check_canvas").handler({}, ctx(tmp_path, LydiaConfig(canvas_base_url=None)))
    assert not result.ok
    assert "auth login canvas" in result.content


def test_check_canvas_success(tmp_path, monkeypatch) -> None:
    import lydia.config.secrets as secrets_mod
    import lydia.connectors.canvas as canvas_mod

    monkeypatch.setattr(secrets_mod, "get_secret", lambda key: "tok" if key == secrets_mod.CANVAS_TOKEN else None)
    fake = [canvas_mod.Assignment(course_name="CS101", name="HW1", due_at="2026-08-01", html_url="")]
    monkeypatch.setattr(canvas_mod, "get_upcoming_assignments", lambda base_url, token: fake)
    config = LydiaConfig(canvas_base_url="https://school.instructure.com")
    result = get("check_canvas").handler({}, ctx(tmp_path, config))
    assert result.ok
    assert "HW1" in result.content


def test_check_email_unknown_account(tmp_path) -> None:
    result = get("check_email").handler({"account": "work"}, ctx(tmp_path))
    assert not result.ok
    assert "Unknown account" in result.content


def test_check_email_personal_not_logged_in(tmp_path, monkeypatch) -> None:
    import lydia.config.secrets as secrets_mod

    monkeypatch.setattr(secrets_mod, "get_secret", lambda key: None)
    result = get("check_email").handler({"account": "personal"}, ctx(tmp_path))
    assert not result.ok
    assert "auth login gmail" in result.content


def test_check_email_personal_success(tmp_path, monkeypatch) -> None:
    import lydia.config.secrets as secrets_mod
    import lydia.connectors.email_gmail as gmail_mod

    monkeypatch.setattr(secrets_mod, "get_secret", lambda key: "creds-json")
    fake = [gmail_mod.EmailSummary(sender="a@x.com", subject="Hi", snippet="s", unread=True)]
    monkeypatch.setattr(gmail_mod, "get_recent_emails", lambda creds: fake)
    result = get("check_email").handler({"account": "personal"}, ctx(tmp_path))
    assert result.ok
    assert "Hi" in result.content


def test_check_email_school_success(tmp_path, monkeypatch) -> None:
    import lydia.connectors.auth.outlook_oauth as outlook_oauth_mod
    import lydia.connectors.email_outlook as outlook_mod

    monkeypatch.setattr(outlook_oauth_mod, "get_access_token", lambda: "at-123")
    fake = [outlook_mod.EmailSummary(sender="b@school.edu", subject="Assignment", snippet="s", unread=False)]
    monkeypatch.setattr(outlook_mod, "get_recent_emails", lambda token: fake)
    result = get("check_email").handler({"account": "school"}, ctx(tmp_path))
    assert result.ok
    assert "Assignment" in result.content


def test_check_email_school_not_logged_in(tmp_path, monkeypatch) -> None:
    import lydia.connectors.auth.outlook_oauth as outlook_oauth_mod

    def boom() -> str:
        raise outlook_oauth_mod.OutlookAuthError("not logged in")

    monkeypatch.setattr(outlook_oauth_mod, "get_access_token", boom)
    result = get("check_email").handler({"account": "school"}, ctx(tmp_path))
    assert not result.ok

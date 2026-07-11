"""Tests for the AI news RSS connector (parses real feedparser output, no network)."""

import feedparser
import pytest

from lydia.connectors import ConnectorError
from lydia.connectors.news import format_news, get_ai_news

FEED_A = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Feed A</title>
<item><title>GPT-5 released</title><link>http://a.example.com/1</link></item>
<item><title>Another AI story</title><link>http://a.example.com/2</link></item>
</channel></rss>"""

FEED_B_WITH_DUPLICATE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Feed B</title>
<item><title>GPT-5 released</title><link>http://b.example.com/dup</link></item>
<item><title>Something else entirely</title><link>http://b.example.com/3</link></item>
</channel></rss>"""

EMPTY_FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>"""


def test_dedupes_by_title_case_insensitive() -> None:
    feeds = (("urlA", "Feed A"), ("urlB", "Feed B"))

    def fetch(url: str):
        return feedparser.parse(FEED_A if url == "urlA" else FEED_B_WITH_DUPLICATE)

    items = get_ai_news(feeds=feeds, fetch=fetch)
    titles = [i.title for i in items]
    assert titles.count("GPT-5 released") == 1
    assert "Another AI story" in titles
    assert "Something else entirely" in titles
    assert len(items) == 3


def test_one_feed_failing_does_not_block_the_others() -> None:
    feeds = (("urlA", "Feed A"), ("urlBroken", "Broken Feed"))

    def fetch(url: str):
        if url == "urlBroken":
            raise RuntimeError("connection refused")
        return feedparser.parse(FEED_A)

    items = get_ai_news(feeds=feeds, fetch=fetch)
    assert len(items) == 2


def test_all_feeds_failing_raises_connector_error() -> None:
    feeds = (("urlBroken", "Broken Feed"),)

    def fetch(url: str):
        raise RuntimeError("connection refused")

    with pytest.raises(ConnectorError):
        get_ai_news(feeds=feeds, fetch=fetch)


def test_empty_feed_yields_no_items_without_error() -> None:
    feeds = (("urlEmpty", "Empty Feed"),)
    items = get_ai_news(feeds=feeds, fetch=lambda url: feedparser.parse(EMPTY_FEED))
    assert items == []


def test_max_items_caps_results() -> None:
    feeds = (("urlA", "Feed A"),)
    items = get_ai_news(feeds=feeds, fetch=lambda url: feedparser.parse(FEED_A), max_items=1)
    assert len(items) == 1


def test_format_news() -> None:
    feeds = (("urlA", "Feed A"),)
    items = get_ai_news(feeds=feeds, fetch=lambda url: feedparser.parse(FEED_A))
    text = format_news(items)
    assert "[Feed A] GPT-5 released" in text

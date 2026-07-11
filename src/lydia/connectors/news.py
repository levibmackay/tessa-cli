"""AI news summary connector — curated RSS feeds, no API key required.

Deliberately returns raw entries rather than trying to summarize them
itself: summarization is left to the LLM in the briefing loop, which keeps
this connector deterministic and easy to unit test.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import feedparser

from lydia.connectors import ConnectorError

# (feed URL, display name). Extend this list as needed — no config required.
FEEDS: tuple[tuple[str, str], ...] = (
    ("https://techcrunch.com/tag/artificial-intelligence/feed/", "TechCrunch AI"),
    ("https://www.artificialintelligence-news.com/feed/", "AI News"),
    ("https://www.technologyreview.com/topic/artificial-intelligence/feed", "MIT Tech Review AI"),
)

MAX_ITEMS = 15


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: str


def get_ai_news(
    feeds: tuple[tuple[str, str], ...] = FEEDS,
    fetch: Callable[[str], object] = feedparser.parse,
    max_items: int = MAX_ITEMS,
) -> list[NewsItem]:
    """Fetch and dedupe (by title) headlines across all configured feeds.

    One feed failing doesn't block the others.
    """
    items: list[NewsItem] = []
    seen_titles: set[str] = set()
    errors: list[str] = []
    for url, source in feeds:
        try:
            parsed = fetch(url)
            entries = parsed.get("entries", [])
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            continue
        for entry in entries:
            title = (entry.get("title") or "").strip()
            if not title or title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())
            items.append(NewsItem(
                title=title,
                link=entry.get("link", ""),
                source=source,
                published=entry.get("published") or entry.get("updated") or "",
            ))
    if not items and errors:
        raise ConnectorError("Could not fetch any AI news: " + "; ".join(errors))
    return items[:max_items]


def format_news(items: list[NewsItem]) -> str:
    return "\n".join(f"- [{it.source}] {it.title} ({it.link})" for it in items)

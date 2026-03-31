"""RSSフィードソース: ML系ブログの最新記事URLを取得する."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import List
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

# 定番のML/データサイエンス系RSSフィード
DEFAULT_FEEDS = [
    "https://machinelearningmastery.com/feed/",
    "https://towardsdatascience.com/feed",
    "https://www.fast.ai/atom.xml",
    "https://www.analyticsvidhya.com/feed/",
    "https://blog.kaggle.com/feed/",
]


class RSSSource:
    """RSSフィードからML関連記事のURLを発見する。"""

    def __init__(self, feeds: List[str] = None):
        self._feeds = feeds or DEFAULT_FEEDS

    def list_urls(self, limit: int = 20) -> List[str]:
        """全フィードを巡回して記事URLを収集する。"""
        urls: list[str] = []

        for feed_url in self._feeds:
            try:
                feed_urls = self._parse_feed(feed_url)
                urls.extend(feed_urls)
            except Exception as e:
                logger.warning("Failed to fetch RSS feed %s: %s", feed_url, e)
                continue

            if len(urls) >= limit:
                break

        return urls[:limit]

    def _parse_feed(self, feed_url: str) -> List[str]:
        """1つのRSSフィードをパースしてURLリストを返す。"""
        req = Request(feed_url, headers={"User-Agent": "ae-harvest/0.1"})
        try:
            with urlopen(req, timeout=15) as resp:
                data = resp.read().decode("utf-8", errors="replace")
        except (URLError, OSError) as e:
            logger.warning("Cannot reach %s: %s", feed_url, e)
            return []

        urls: list[str] = []
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            return []

        # RSS 2.0: <channel><item><link>
        for item in root.iter("item"):
            link = item.find("link")
            if link is not None and link.text:
                urls.append(link.text.strip())

        # Atom: <entry><link href="...">
        # Atom名前空間を考慮
        for ns in ["", "{http://www.w3.org/2005/Atom}"]:
            for entry in root.iter(f"{ns}entry"):
                link = entry.find(f"{ns}link")
                if link is not None:
                    href = link.get("href")
                    if href:
                        urls.append(href.strip())

        return urls

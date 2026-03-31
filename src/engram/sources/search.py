"""Web検索ソース: DuckDuckGoでKaggle/MLのTips記事を検索する."""

from __future__ import annotations

import json
import logging
import re
from typing import List
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

# 検索クエリのプリセット
DEFAULT_QUERIES = [
    "kaggle competition tips tricks",
    "kaggle winning solution writeup",
    "machine learning best practices tips",
    "feature engineering kaggle",
    "LightGBM XGBoost tuning tips",
    "kaggle gold medal solution",
]

# DuckDuckGo HTML検索からリンクを抽出するパターン
_DDG_LINK_RE = re.compile(r'href="(https?://[^"]+)"')

# 検索結果から除外するドメイン
_EXCLUDE_DOMAINS = [
    "duckduckgo.com",
    "google.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "linkedin.com",
    "reddit.com/r/",  # サブレディットのトップは除外（個別投稿はOK）
]


class WebSearchSource:
    """DuckDuckGoで検索してKaggle/ML関連記事のURLを発見する。認証不要。"""

    def __init__(self, queries: List[str] = None):
        self._queries = queries or DEFAULT_QUERIES

    def list_urls(self, limit: int = 20) -> List[str]:
        """検索クエリを順に実行してURLを収集する。"""
        urls: list[str] = []
        seen: set[str] = set()

        for query in self._queries:
            try:
                results = self._search_ddg_lite(query)
                for url in results:
                    if url not in seen and self._is_relevant(url):
                        seen.add(url)
                        urls.append(url)
            except Exception as e:
                logger.warning("Search failed for '%s': %s", query, e)
                continue

            if len(urls) >= limit:
                break

        return urls[:limit]

    def _search_ddg_lite(self, query: str, max_results: int = 10) -> List[str]:
        """DuckDuckGo Lite（HTMLベース）で検索してURLを返す。API不要。"""
        encoded = quote_plus(query)
        url = f"https://lite.duckduckgo.com/lite/?q={encoded}"

        req = Request(url, headers={
            "User-Agent": "ae-harvest/0.1 (ML tips collector)",
        })

        try:
            with urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except (URLError, OSError) as e:
            logger.warning("DuckDuckGo search failed: %s", e)
            return []

        # HTML内のリンクを抽出
        urls: list[str] = []
        for match in _DDG_LINK_RE.finditer(html):
            link = match.group(1)
            # DuckDuckGo内部リンクを除外
            if not any(excl in link for excl in _EXCLUDE_DOMAINS):
                urls.append(link)

        return urls[:max_results]

    def _is_relevant(self, url: str) -> bool:
        """URLが関連コンテンツかどうか。"""
        for excl in _EXCLUDE_DOMAINS:
            if excl in url:
                return False
        return True

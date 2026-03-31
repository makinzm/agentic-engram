"""ae-harvest のWebソース: 自動的にKaggle/ML記事のURLを発見する."""

from __future__ import annotations

from typing import List

from engram.sources.rss import RSSSource
from engram.sources.awesome import AwesomeListSource
from engram.sources.search import WebSearchSource
from engram.sources.kaggle import KaggleSource

# ソース名 → クラスの対応
SOURCE_REGISTRY = {
    "rss": RSSSource,
    "awesome": AwesomeListSource,
    "search": WebSearchSource,
    "kaggle": KaggleSource,
}

ALL_AUTO_SOURCES = ["rss", "awesome", "search"]  # 認証不要のソース


def discover_urls(source_name: str, limit: int = 20) -> List[str]:
    """指定ソースからURLを自動発見する。"""
    if source_name == "all":
        urls: list[str] = []
        for name in ALL_AUTO_SOURCES:
            src = SOURCE_REGISTRY[name]()
            urls.extend(src.list_urls(limit=limit))
        return urls

    if source_name not in SOURCE_REGISTRY:
        raise ValueError(f"Unknown source: {source_name}. Available: {', '.join(SOURCE_REGISTRY.keys())}, all")

    src = SOURCE_REGISTRY[source_name]()
    return src.list_urls(limit=limit)

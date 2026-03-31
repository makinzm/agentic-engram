"""Awesome Listソース: GitHubのKaggle/ML系まとめREADMEからURLを抽出する."""

from __future__ import annotations

import logging
import re
from typing import List
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

# GitHubのREADME（raw形式）でKaggle/MLのまとめリスト
DEFAULT_AWESOME_URLS = [
    # kaggle-solutions: コンペ解法まとめ
    "https://raw.githubusercontent.com/faridrashidi/kaggle-solutions/master/README.md",
    # awesome-kaggle: Kaggle関連リソース
    "https://raw.githubusercontent.com/krishnakalyan3/awesome-kaggle/master/README.md",
]

# URLを抽出する正規表現（Markdownリンク）
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")

# Kaggle/ML関連のURLフィルタ（ノイズ除去）
_RELEVANT_DOMAINS = [
    "kaggle.com",
    "github.com",
    "medium.com",
    "towardsdatascience.com",
    "analyticsvidhya.com",
    "machinelearningmastery.com",
    "arxiv.org",
    "fast.ai",
    "huggingface.co",
]

# 除外パターン（バッジ画像、アイコンなど）
_EXCLUDE_PATTERNS = [
    r"img\.shields\.io",
    r"badge",
    r"\.png$",
    r"\.jpg$",
    r"\.svg$",
    r"github\.com/[^/]+/?$",  # リポジトリのトップページだけ（READMEがない）
]


class AwesomeListSource:
    """GitHub Awesome ListのREADMEからKaggle/ML関連URLを発見する。"""

    def __init__(self, awesome_urls: List[str] = None):
        self._awesome_urls = awesome_urls or DEFAULT_AWESOME_URLS

    def list_urls(self, limit: int = 20) -> List[str]:
        """Awesome ListのREADMEからURLを抽出する。"""
        urls: list[str] = []
        seen: set[str] = set()

        for awesome_url in self._awesome_urls:
            try:
                extracted = self._extract_urls_from_readme(awesome_url)
                for url in extracted:
                    if url not in seen:
                        seen.add(url)
                        urls.append(url)
            except Exception as e:
                logger.warning("Failed to fetch awesome list %s: %s", awesome_url, e)
                continue

            if len(urls) >= limit:
                break

        return urls[:limit]

    def _extract_urls_from_readme(self, readme_url: str) -> List[str]:
        """README Markdownを取得してURLを抽出する。"""
        req = Request(readme_url, headers={"User-Agent": "ae-harvest/0.1"})
        try:
            with urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except (URLError, OSError) as e:
            logger.warning("Cannot reach %s: %s", readme_url, e)
            return []

        urls: list[str] = []
        for _label, url in _MD_LINK_RE.findall(text):
            if self._is_relevant(url):
                urls.append(url)

        return urls

    def _is_relevant(self, url: str) -> bool:
        """URLがKaggle/ML関連かどうかを判定する。"""
        # 除外パターンに一致するものは除外
        for pat in _EXCLUDE_PATTERNS:
            if re.search(pat, url):
                return False

        # 関連ドメインに含まれていればOK
        for domain in _RELEVANT_DOMAINS:
            if domain in url:
                return True

        return False

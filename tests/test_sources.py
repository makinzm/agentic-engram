"""ae-harvest ソースのテスト."""

import json
from unittest.mock import patch, MagicMock

import pytest

from engram.sources.rss import RSSSource, DEFAULT_FEEDS
from engram.sources.awesome import AwesomeListSource, _MD_LINK_RE
from engram.sources.search import WebSearchSource
from engram.sources.kaggle import KaggleSource
from engram.sources import discover_urls, SOURCE_REGISTRY, ALL_AUTO_SOURCES


# --- RSSSource ---


class TestRSSSource:
    RSS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ML Blog</title>
    <item>
      <title>LightGBM Tips</title>
      <link>https://example.com/lgbm-tips</link>
    </item>
    <item>
      <title>Feature Engineering</title>
      <link>https://example.com/feature-eng</link>
    </item>
  </channel>
</rss>"""

    ATOM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Fast.ai Lesson</title>
    <link href="https://fast.ai/lesson1" />
  </entry>
</feed>"""

    def test_parse_rss_feed(self):
        src = RSSSource(feeds=["https://mock.feed/rss"])
        with patch("engram.sources.rss.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = self.RSS_XML.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            urls = src._parse_feed("https://mock.feed/rss")
            assert "https://example.com/lgbm-tips" in urls
            assert "https://example.com/feature-eng" in urls

    def test_parse_atom_feed(self):
        src = RSSSource(feeds=["https://mock.feed/atom"])
        with patch("engram.sources.rss.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = self.ATOM_XML.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            urls = src._parse_feed("https://mock.feed/atom")
            assert "https://fast.ai/lesson1" in urls

    def test_list_urls_with_limit(self):
        src = RSSSource(feeds=["https://mock.feed/rss"])
        with patch("engram.sources.rss.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = self.RSS_XML.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            urls = src.list_urls(limit=1)
            assert len(urls) == 1

    def test_handles_unreachable_feed(self):
        src = RSSSource(feeds=["https://unreachable.invalid/feed"])
        with patch("engram.sources.rss.urlopen", side_effect=OSError("unreachable")):
            urls = src._parse_feed("https://unreachable.invalid/feed")
            assert urls == []

    def test_default_feeds_defined(self):
        assert len(DEFAULT_FEEDS) > 0


# --- AwesomeListSource ---


class TestAwesomeListSource:
    README_MD = """\
# Awesome Kaggle

## Solutions
- [1st Place LLM Solution](https://www.kaggle.com/competitions/llm/discussion/12345)
- [Feature Engineering Guide](https://towardsdatascience.com/feature-eng-guide)
- [Badge](https://img.shields.io/badge/stars-100-blue.svg)
- [GitHub Repo](https://github.com/user/repo/blob/main/solution.py)
"""

    def test_extracts_relevant_urls(self):
        src = AwesomeListSource(awesome_urls=["https://mock/readme"])
        with patch("engram.sources.awesome.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = self.README_MD.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            urls = src._extract_urls_from_readme("https://mock/readme")
            # kaggle.com と towardsdatascience.com のURLは含まれる
            assert any("kaggle.com" in u for u in urls)
            assert any("towardsdatascience.com" in u for u in urls)
            # badge画像は除外
            assert not any("img.shields.io" in u for u in urls)

    def test_filters_badge_images(self):
        src = AwesomeListSource()
        assert not src._is_relevant("https://img.shields.io/badge/foo")

    def test_md_link_regex(self):
        matches = _MD_LINK_RE.findall("[text](https://example.com)")
        assert len(matches) == 1
        assert matches[0][1] == "https://example.com"

    def test_list_urls_deduplicates(self):
        """同じURLが複数のAwesome Listに出ても重複しない。"""
        readme = "- [A](https://kaggle.com/solution1)\n- [B](https://kaggle.com/solution1)\n"
        src = AwesomeListSource(awesome_urls=["https://mock/readme1"])
        with patch("engram.sources.awesome.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = readme.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            urls = src.list_urls(limit=10)
            assert len(urls) == 1


# --- WebSearchSource ---


class TestWebSearchSource:
    DDG_HTML = """\
<html><body>
<a href="https://machinelearningmastery.com/lgbm-tips">LGBM Tips</a>
<a href="https://towardsdatascience.com/kaggle-guide">Guide</a>
<a href="https://duckduckgo.com/feedback">Feedback</a>
</body></html>"""

    def test_search_extracts_urls(self):
        src = WebSearchSource(queries=["kaggle tips"])
        with patch("engram.sources.search.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = self.DDG_HTML.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            urls = src._search_ddg_lite("kaggle tips")
            assert "https://machinelearningmastery.com/lgbm-tips" in urls
            assert "https://towardsdatascience.com/kaggle-guide" in urls
            # duckduckgo.com の内部リンクは除外
            assert not any("duckduckgo.com" in u for u in urls)

    def test_handles_search_failure(self):
        src = WebSearchSource(queries=["test"])
        with patch("engram.sources.search.urlopen", side_effect=OSError("fail")):
            urls = src._search_ddg_lite("test")
            assert urls == []

    def test_is_relevant_excludes_social_media(self):
        src = WebSearchSource()
        assert not src._is_relevant("https://twitter.com/something")
        assert not src._is_relevant("https://youtube.com/watch?v=xxx")
        assert src._is_relevant("https://machinelearningmastery.com/tips")


# --- KaggleSource ---


class TestKaggleSource:
    def test_no_credentials_returns_empty(self):
        src = KaggleSource()
        src._creds = None
        urls = src.list_urls()
        assert urls == []

    def test_with_mock_api(self):
        src = KaggleSource()
        src._creds = {"username": "test", "key": "abc123"}

        api_response = json.dumps([
            {"ref": "user1/lgbm-notebook"},
            {"ref": "user2/xgboost-tips"},
        ]).encode()

        with patch("engram.sources.kaggle.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = api_response
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            urls = src.list_urls(limit=10)
            assert "https://www.kaggle.com/code/user1/lgbm-notebook" in urls
            assert "https://www.kaggle.com/code/user2/xgboost-tips" in urls

    def test_auth_header_format(self):
        src = KaggleSource()
        src._creds = {"username": "user", "key": "pass"}
        header = src._make_auth_header()
        assert header.startswith("Basic ")


# --- discover_urls ---


class TestDiscoverUrls:
    def test_registry_has_all_sources(self):
        assert "rss" in SOURCE_REGISTRY
        assert "awesome" in SOURCE_REGISTRY
        assert "search" in SOURCE_REGISTRY
        assert "kaggle" in SOURCE_REGISTRY

    def test_all_auto_sources_no_kaggle(self):
        """'all' には認証不要のソースのみ含まれる。"""
        assert "kaggle" not in ALL_AUTO_SOURCES
        assert "rss" in ALL_AUTO_SOURCES
        assert "awesome" in ALL_AUTO_SOURCES
        assert "search" in ALL_AUTO_SOURCES

    def test_invalid_source_raises(self):
        with pytest.raises(ValueError, match="Unknown source"):
            discover_urls("nonexistent")

    def test_discover_with_mock_rss(self):
        rss_xml = """\
<?xml version="1.0"?><rss version="2.0"><channel>
<item><link>https://example.com/tip1</link></item>
</channel></rss>"""
        with patch("engram.sources.rss.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = rss_xml.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            urls = discover_urls("rss", limit=5)
            assert len(urls) > 0

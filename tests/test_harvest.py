"""ae-harvest のテスト."""

import json
import os
import tempfile

import pytest

from engram.cursor import CursorManager
from engram.harvest import (
    url_to_cursor_key,
    url_to_session_id,
    filter_new_urls,
    process_url,
)
from engram.prompts_harvest import build_harvest_prompt, MAX_CONTENT_CHARS


# --- url_to_cursor_key ---


class TestUrlToCursorKey:
    def test_returns_harvest_prefixed_key(self):
        key = url_to_cursor_key("https://example.com/article")
        assert key.startswith("harvest:")

    def test_deterministic(self):
        url = "https://example.com/kaggle-tips"
        assert url_to_cursor_key(url) == url_to_cursor_key(url)

    def test_different_urls_produce_different_keys(self):
        key1 = url_to_cursor_key("https://example.com/a")
        key2 = url_to_cursor_key("https://example.com/b")
        assert key1 != key2


# --- url_to_session_id ---


class TestUrlToSessionId:
    def test_returns_harvest_prefixed_id(self):
        sid = url_to_session_id("https://example.com/article")
        assert sid.startswith("harvest:")

    def test_matches_cursor_key(self):
        """session_idとcursor_keyは同じハッシュベース。"""
        url = "https://example.com/tips"
        assert url_to_session_id(url) == url_to_cursor_key(url)


# --- filter_new_urls ---


class TestFilterNewUrls:
    def test_all_new(self, tmp_cursor_path):
        cm = CursorManager(tmp_cursor_path)
        urls = ["https://a.com", "https://b.com"]
        assert filter_new_urls(urls, cm) == urls

    def test_filters_processed(self, tmp_cursor_path):
        cm = CursorManager(tmp_cursor_path)
        # URLを処理済みにマーク
        key = url_to_cursor_key("https://a.com")
        cm.update_cursor(key, last_read_line=1, last_checked_mtime=1000.0)

        urls = ["https://a.com", "https://b.com"]
        result = filter_new_urls(urls, cm)
        assert result == ["https://b.com"]

    def test_empty_input(self, tmp_cursor_path):
        cm = CursorManager(tmp_cursor_path)
        assert filter_new_urls([], cm) == []


# --- build_harvest_prompt ---


class TestBuildHarvestPrompt:
    def test_returns_system_and_user_messages(self):
        messages = build_harvest_prompt("article content", "https://example.com")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_user_message_contains_url(self):
        messages = build_harvest_prompt("content", "https://example.com/tips")
        assert "https://example.com/tips" in messages[1]["content"]

    def test_user_message_contains_content(self):
        messages = build_harvest_prompt("LightGBM tuning tips", "https://example.com")
        assert "LightGBM tuning tips" in messages[1]["content"]

    def test_truncation(self):
        long_content = "a" * (MAX_CONTENT_CHARS + 1000)
        messages = build_harvest_prompt(long_content, "https://example.com")
        assert "truncated" in messages[1]["content"]
        # 元のコンテンツ全体は含まれない
        assert long_content not in messages[1]["content"]

    def test_system_prompt_mentions_kaggle(self):
        messages = build_harvest_prompt("content", "https://example.com")
        assert "Kaggle" in messages[0]["content"]


# --- process_url ---


class TestProcessUrl:
    def _mock_llm_harvest(self, messages):
        """harvest用LLMモック: 2つのTipsを返す。"""
        return json.dumps(
            [
                {
                    "action": "INSERT",
                    "payload": {
                        "event": "LightGBM num_leaves設定",
                        "context": "テーブルデータコンペ https://example.com",
                        "core_lessons": "num_leaves < 2^max_depth にする",
                        "category": "model-training",
                        "tags": ["LightGBM", "Kaggle"],
                        "related_files": [],
                        "session_id": "will_be_overwritten",
                    },
                    "entities": ["LightGBM"],
                    "relations": [],
                },
                {
                    "action": "INSERT",
                    "payload": {
                        "event": "Target Encoding のリーク防止",
                        "context": "カテゴリ変数処理 https://example.com",
                        "core_lessons": "CVのfoldごとに計算する",
                        "category": "feature-engineering",
                        "tags": ["target-encoding"],
                        "related_files": [],
                        "session_id": "will_be_overwritten",
                    },
                    "entities": ["Target Encoding"],
                    "relations": [],
                },
            ],
            ensure_ascii=False,
        )

    def _mock_llm_skip(self, messages):
        return json.dumps(
            [{"action": "SKIP", "reason": "広告ページのため"}],
            ensure_ascii=False,
        )

    def _mock_fetcher(self, url):
        return "LightGBM tuning tips: set num_leaves < 2^max_depth"

    def test_process_url_inserts_tips(self, tmp_cursor_path, tmp_db_path):
        cm = CursorManager(tmp_cursor_path)
        url = "https://example.com/lgbm-tips"

        result = process_url(
            url,
            cm,
            self._mock_llm_harvest,
            db_path=tmp_db_path,
            fetcher=self._mock_fetcher,
        )

        assert result["inserted"] == 2

        # カーソルが更新されている
        key = url_to_cursor_key(url)
        cursor = cm.get_cursor(key)
        assert cursor["last_read_line"] == 1  # 処理済みマーク

    def test_process_url_skip(self, tmp_cursor_path, tmp_db_path):
        cm = CursorManager(tmp_cursor_path)
        url = "https://example.com/ad-page"

        result = process_url(
            url,
            cm,
            self._mock_llm_skip,
            db_path=tmp_db_path,
            fetcher=self._mock_fetcher,
        )

        assert result["skipped"] == 1
        assert result["inserted"] == 0

    def test_process_url_sets_session_id(self, tmp_cursor_path, tmp_db_path):
        """session_idがURLベースで自動設定されることを確認。"""
        cm = CursorManager(tmp_cursor_path)
        url = "https://example.com/test-session"
        captured_actions = []

        def _capturing_llm(messages):
            response = self._mock_llm_harvest(messages)
            captured_actions.extend(json.loads(response))
            return response

        process_url(
            url,
            cm,
            _capturing_llm,
            db_path=tmp_db_path,
            fetcher=self._mock_fetcher,
        )

        # process_url内でsession_idが上書きされるため、
        # 保存された記憶のsession_idを確認
        expected_sid = url_to_session_id(url)
        from engram.recall import search_memories

        results = search_memories("LightGBM", db_path=tmp_db_path)
        assert len(results) > 0
        assert results[0]["session_id"] == expected_sid

    def test_process_url_already_processed(self, tmp_cursor_path, tmp_db_path):
        """処理済みURLはfilter_new_urlsでスキップされる（process_urlは呼ばれない想定）。"""
        cm = CursorManager(tmp_cursor_path)
        url = "https://example.com/already-done"

        # 先に処理済みにする
        key = url_to_cursor_key(url)
        cm.update_cursor(key, last_read_line=1, last_checked_mtime=1000.0)

        # filter_new_urlsで除外される
        assert filter_new_urls([url], cm) == []

    def test_process_url_fetch_failure(self, tmp_cursor_path, tmp_db_path):
        cm = CursorManager(tmp_cursor_path)

        def _failing_fetcher(url):
            raise RuntimeError("Network error")

        result = process_url(
            "https://example.com/fail",
            cm,
            self._mock_llm_harvest,
            db_path=tmp_db_path,
            fetcher=_failing_fetcher,
        )

        assert result == {}

    def test_process_url_invalid_llm_response(self, tmp_cursor_path, tmp_db_path):
        cm = CursorManager(tmp_cursor_path)

        def _bad_llm(messages):
            return "this is not json"

        result = process_url(
            "https://example.com/bad-llm",
            cm,
            _bad_llm,
            db_path=tmp_db_path,
            fetcher=self._mock_fetcher,
        )

        assert result == {}


# --- CLI (ae-harvest) ---


class TestHarvestCLI:
    def test_read_urls_from_file(self, tmp_path):
        from engram.cli.harvest import _read_urls_from_file

        url_file = tmp_path / "urls.txt"
        url_file.write_text(
            "# コメント行\n"
            "https://example.com/a\n"
            "\n"
            "https://example.com/b\n"
            "# もう一つのコメント\n"
        )

        urls = _read_urls_from_file(str(url_file))
        assert urls == ["https://example.com/a", "https://example.com/b"]

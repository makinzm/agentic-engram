"""ae-harvest コアロジック: Web記事からKaggle/ML Tipsを抽出してRAGに投入する."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from engram.cursor import CursorManager
from engram.prompts_harvest import build_harvest_prompt

logger = logging.getLogger(__name__)


def url_to_cursor_key(url: str) -> str:
    """URLからカーソルキーを生成する。harvest: プレフィックスで ae-miner と衝突しない。"""
    return "harvest:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def url_to_session_id(url: str) -> str:
    """URLからsession_idを生成する。"""
    return "harvest:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def fetch_web_content(url: str) -> str:
    """URLからWeb記事の本文テキストを取得する。

    trafilatura を使用。インストールされていない場合は urllib + 簡易抽出にフォールバック。
    """
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            raise RuntimeError(f"Failed to fetch URL: {url}")
        text = trafilatura.extract(downloaded)
        if text is None:
            raise RuntimeError(f"Failed to extract content from: {url}")
        return text
    except ImportError:
        # trafilatura が無い場合は urllib でフォールバック
        import urllib.request
        from html.parser import HTMLParser

        req = urllib.request.Request(url, headers={"User-Agent": "ae-harvest/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # 簡易的にタグを除去
        class _TagStripper(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts: list[str] = []
                self._skip = False

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style", "nav", "header", "footer"):
                    self._skip = True

            def handle_endtag(self, tag):
                if tag in ("script", "style", "nav", "header", "footer"):
                    self._skip = False

            def handle_data(self, data):
                if not self._skip:
                    self.parts.append(data)

        stripper = _TagStripper()
        stripper.feed(html)
        return " ".join(stripper.parts).strip()


def filter_new_urls(
    urls: List[str],
    cursor_manager: CursorManager,
) -> List[str]:
    """未処理のURLのみをフィルタリングして返す。"""
    new_urls: list[str] = []
    for url in urls:
        key = url_to_cursor_key(url)
        cursor = cursor_manager.get_cursor(key)
        # last_read_line > 0 は処理済みを意味する
        if cursor["last_read_line"] > 0:
            continue
        new_urls.append(url)
    return new_urls


def process_url(
    url: str,
    cursor_manager: CursorManager,
    llm_fn: Callable,
    db_path: str,
    graph_path: Optional[str] = None,
    fetcher: Optional[Callable[[str], str]] = None,
) -> Dict[str, int]:
    """1つのURLを処理する: 取得 → LLM抽出 → 保存 → カーソル更新。

    Returns {"inserted": N, "skipped": N} or empty dict on failure.
    """
    # 1. Webコンテンツ取得
    fetch_fn = fetcher or fetch_web_content
    try:
        content = fetch_fn(url)
    except Exception as e:
        logger.error("Failed to fetch %s: %s", url, e)
        return {}

    if not content or not content.strip():
        logger.warning("Empty content from %s", url)
        return {}

    # 2. LLMプロンプト構築 → 呼び出し
    messages = build_harvest_prompt(content, url)

    try:
        llm_response = llm_fn(messages)
        actions = json.loads(llm_response)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.error("Invalid LLM response for %s: %s", url, e)
        return {}

    if not isinstance(actions, list) or len(actions) == 0:
        return {}

    # 3. session_id を自動付与
    session_id = url_to_session_id(url)
    for action in actions:
        if action.get("action") == "SKIP":
            continue
        payload = action.get("payload", {})
        payload["session_id"] = session_id
        # related_files がなければ空リストに
        if "related_files" not in payload:
            payload["related_files"] = []

    # 4. INSERT/UPDATE を保存
    has_write = any(a.get("action") in ("INSERT", "UPDATE") for a in actions)

    result = {"inserted": 0, "skipped": 0}

    if has_write:
        from engram.save import save_memories

        write_actions = [a for a in actions if a.get("action") in ("INSERT", "UPDATE")]
        try:
            save_result = save_memories(write_actions, db_path=db_path, graph_path=graph_path)
            result["inserted"] = save_result.get("inserted", 0)
        except Exception as e:
            logger.error("save_memories() failed for %s: %s", url, e)
            return {}

    skip_count = sum(1 for a in actions if a.get("action") == "SKIP")
    result["skipped"] = skip_count

    # 5. カーソル更新（処理済みマーク）
    cursor_key = url_to_cursor_key(url)
    cursor_manager.update_cursor(cursor_key, last_read_line=1, last_checked_mtime=time.time())

    return result

"""ae-miner コアロジック: scan_logs, read_diff, process_log, archive_stale_logs."""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from typing import Any, Callable, Dict, List, Optional

from engram.cursor import CursorManager
from engram.prompts import build_extraction_prompt


def scan_logs(log_dir: str, cursor_manager: CursorManager) -> List[Dict[str, Any]]:
    """log_dir 直下の *_log.txt ファイルをスキャンし、処理対象を返す。

    archive/ 配下は除外。mtime が変化したか新規のもののみ返す。
    """
    targets: list[dict] = []

    for entry in os.listdir(log_dir):
        # archive/ サブディレクトリは除外
        full = os.path.join(log_dir, entry)
        if os.path.isdir(full):
            continue
        if not entry.endswith("_log.txt"):
            continue

        current_mtime = os.path.getmtime(full)
        cursor = cursor_manager.get_cursor(entry)

        # last_checked_mtime == 0.0 は「未処理（一度も読んでいない）」を意味する。
        # 未処理ファイルは mtime に関わらず対象に含める。
        if cursor["last_checked_mtime"] != 0.0 and cursor["last_checked_mtime"] == current_mtime:
            continue  # unchanged

        targets.append({
            "filename": entry,
            "filepath": full,
            "mtime": current_mtime,
        })

    return targets


def read_diff(filepath: str, last_read_line: int) -> str:
    """filepath の last_read_line 以降を返す。全既読 or 空なら空文字列。"""
    new_lines: list[str] = []
    with open(filepath, "r") as f:
        for i, line in enumerate(f):
            if i >= last_read_line:
                new_lines.append(line)
    return "".join(new_lines)


def process_log(
    filepath: str,
    cursor_manager: CursorManager,
    llm_fn: Callable,
    db_path: str,
    recall_fn: Optional[Callable] = None,
) -> None:
    """1ファイルを処理する。差分読み取り → LLM → ae-save。"""

    if not os.path.exists(filepath):
        return

    filename = os.path.basename(filepath)
    cursor = cursor_manager.get_cursor(filename)
    last_read_line = cursor["last_read_line"]

    # 差分の読み取り（イテレータでスキップし、メモリ展開を最小化）
    diff_lines: list[str] = []
    total_lines = 0
    with open(filepath, "r") as f:
        for i, line in enumerate(f):
            total_lines = i + 1
            if i >= last_read_line:
                diff_lines.append(line)

    if last_read_line >= total_lines:
        return  # no diff → noop

    diff_text = "".join(diff_lines)

    if not diff_text.strip():
        return

    # 既存記憶の検索
    if recall_fn is None:
        from engram.recall import search_memories
        _recall_fn = lambda q, **kw: search_memories(q, db_path=db_path, **kw)
    else:
        _recall_fn = recall_fn

    # diff_text の先頭部分をクエリとして既存記憶を検索
    query_text = diff_text[:500]
    try:
        existing_memories = _recall_fn(query_text)
    except Exception:
        existing_memories = []

    # プロンプト構築 → LLM呼び出し
    messages = build_extraction_prompt(diff_text, existing_memories)

    try:
        llm_response = llm_fn(messages)
        actions = json.loads(llm_response)
    except (json.JSONDecodeError, TypeError, ValueError):
        # 不正JSON → カーソル更新しない（次回再試行）
        return

    if not isinstance(actions, list) or len(actions) == 0:
        # 空配列 → カーソル更新しない
        return

    # INSERT/UPDATE があるか判定
    has_write = any(a.get("action") in ("INSERT", "UPDATE") for a in actions)
    all_skip = all(a.get("action") == "SKIP" for a in actions)

    current_mtime = os.path.getmtime(filepath)

    if has_write:
        # ae-save に流し込む
        from engram.save import save_memories
        write_actions = [a for a in actions if a.get("action") in ("INSERT", "UPDATE")]
        try:
            save_memories(write_actions, db_path=db_path)
        except Exception as e:
            logging.error("save_memories() の実行中にエラーが発生しました: %s", e)
            return  # 保存失敗 → カーソル更新しない

        cursor_manager.update_cursor(filename, last_read_line=total_lines, last_checked_mtime=current_mtime)
    elif all_skip:
        # SKIP のみ: last_read_line は進めず mtime だけ更新
        cursor_manager.update_cursor(filename, last_read_line=last_read_line, last_checked_mtime=current_mtime)


def archive_stale_logs(
    log_dir: str,
    archive_dir: str,
    cursor_manager: CursorManager,
    ttl_days: int = 7,
) -> None:
    """TTL超過ファイルを archive_dir へ移動し、カーソルを削除する。

    判定基準はファイルの mtime。
    """
    os.makedirs(archive_dir, exist_ok=True)
    threshold = time.time() - (ttl_days * 86400)

    for entry in os.listdir(log_dir):
        full = os.path.join(log_dir, entry)
        if os.path.isdir(full):
            continue
        if not entry.endswith("_log.txt"):
            continue

        file_mtime = os.path.getmtime(full)
        if file_mtime < threshold:
            dest = os.path.join(archive_dir, entry)
            shutil.move(full, dest)
            cursor_manager.remove_cursor(entry)

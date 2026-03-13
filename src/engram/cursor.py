"""CursorManager: cursor.json の状態管理モジュール."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from typing import Dict


class CursorManager:
    """Filebeat方式のカーソル管理。各ログファイルの last_read_line / last_checked_mtime を追跡する。"""

    _DEFAULT_ENTRY = {"last_read_line": 0, "last_checked_mtime": 0.0}

    def __init__(self, cursor_path: str) -> None:
        self._path = cursor_path
        self._data: Dict[str, dict] = {}
        if os.path.exists(cursor_path):
            try:
                with open(cursor_path, "r") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                logging.warning("cursor.json が破損しています。空の状態で初期化します: %s", cursor_path)
                self._data = {}

    # --- public API ---

    def get_cursor(self, filename: str) -> dict:
        if filename in self._data:
            return copy.deepcopy(self._data[filename])
        return dict(self._DEFAULT_ENTRY)

    def update_cursor(
        self, filename: str, last_read_line: int, last_checked_mtime: float
    ) -> None:
        self._data[filename] = {
            "last_read_line": last_read_line,
            "last_checked_mtime": last_checked_mtime,
        }
        self._flush()

    def remove_cursor(self, filename: str) -> None:
        if filename in self._data:
            del self._data[filename]
            self._flush()

    def list_cursors(self) -> dict:
        return copy.deepcopy(self._data)

    # --- internal ---

    def _flush(self) -> None:
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # tempfile に書き出してから os.replace() でアトミックに置換する。
        # 書き込み途中のクラッシュで cursor.json が破損するのを防ぐ。
        fd, tmp_path = tempfile.mkstemp(dir=parent or ".", prefix=".cursor_tmp_")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            os.unlink(tmp_path)
            raise

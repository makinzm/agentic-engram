"""SessionParser Protocol: パーサーの共通インターフェース."""

from __future__ import annotations

from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from engram.cursor import CursorManager

try:
    from typing import Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Protocol, runtime_checkable


@runtime_checkable
class SessionParser(Protocol):
    """セッションログパーサーのプロトコル定義."""

    def scan(self, cursor_manager: CursorManager) -> List[Dict[str, Any]]:
        """処理対象ファイルを返す。各要素は {filename, filepath, mtime}."""
        ...

    def read_diff(self, filepath: str, last_read_line: int) -> tuple:
        """(formatted_text, total_lines) を返す。"""
        ...

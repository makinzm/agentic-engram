"""LanceDB connection, table management, insert_records, get_table."""

from __future__ import annotations

import datetime
import re
import pyarrow as pa
import lancedb
from typing import List, Dict, Any

from engram.embedder import embed_text

_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _validate_id(record_id: str) -> str:
    """Validate that record_id is a SHA-256 hex digest. Returns the id if valid."""
    if not isinstance(record_id, str) or not _ID_PATTERN.match(record_id):
        raise ValueError(
            f"Invalid record_id format: {record_id!r}. "
            "Expected a 64-character lowercase hex string (SHA-256)."
        )
    return record_id

TABLE_NAME = "engram_memories"

ENGRAM_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), 384)),
    pa.field("event", pa.string()),
    pa.field("context", pa.string()),
    pa.field("core_lessons", pa.string()),
    pa.field("category", pa.string()),
    pa.field("tags", pa.list_(pa.string())),
    pa.field("related_files", pa.list_(pa.string())),
    pa.field("session_id", pa.string()),
    pa.field("timestamp", pa.timestamp("s")),
    pa.field("entities_json", pa.string()),
    pa.field("relations_json", pa.string()),
    pa.field("occurrence_count", pa.int32()),
])


def _connect(db_path: str):
    return lancedb.connect(db_path)


def get_table(db_path: str):
    """Get the engram_memories table. Returns LanceDB table object."""
    db = _connect(db_path)
    return db.open_table(TABLE_NAME)


def _ensure_table(db_path: str):
    """Create table if it doesn't exist, return it."""
    db = _connect(db_path)
    try:
        return db.open_table(TABLE_NAME)
    except Exception:
        return db.create_table(TABLE_NAME, schema=ENGRAM_SCHEMA)


def insert_records(records: List[Dict[str, Any]], db_path: str) -> None:
    """Insert records into LanceDB. Auto-generates embeddings if vector field is missing."""
    if not records:
        return

    for rec in records:
        if "vector" not in rec or rec["vector"] is None:
            tags_str = " ".join(rec.get("tags", []) or [])
            text = f"{rec.get('event', '')} {rec.get('context', '')} {rec.get('core_lessons', '')} {tags_str}"
            rec["vector"] = embed_text(text)
        # Truncate timestamp to second precision to match schema timestamp('s')
        if "timestamp" in rec and isinstance(rec["timestamp"], datetime.datetime):
            rec["timestamp"] = rec["timestamp"].replace(microsecond=0)
        # Default occurrence_count to 1 if not provided
        if "occurrence_count" not in rec or rec["occurrence_count"] is None:
            rec["occurrence_count"] = 1

    table = _ensure_table(db_path)
    table.add(records)


def delete_records(ids: List[str], db_path: str) -> None:
    """Delete records by id."""
    table = _ensure_table(db_path)
    for record_id in ids:
        _validate_id(record_id)
        table.delete(f'id = "{record_id}"')


def record_exists(record_id: str, db_path: str) -> bool:
    """Check if a record with the given id exists."""
    _validate_id(record_id)
    try:
        table = get_table(db_path)
    except Exception:
        return False
    result = table.search().where(f'id = "{record_id}"').limit(1).to_arrow()
    return len(result) > 0

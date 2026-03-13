"""Console logic layer for ae-console (Streamlit management UI).

Provides testable functions for memory browsing, stats, and deletion.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List

from engram.db import TABLE_NAME, get_table, record_exists, delete_records

_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def get_all_memories(db_path: str) -> List[Dict[str, Any]]:
    """Return all memories as a list of dicts (without vector field).

    Returns an empty list if the table does not exist.
    """
    try:
        table = get_table(db_path)
    except Exception:
        return []

    df = table.to_pandas()
    if df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        rec = {}
        for col in row.index:
            if col == "vector":
                continue
            val = row[col]
            if hasattr(val, "tolist"):
                val = val.tolist()
            elif hasattr(val, "item"):
                val = val.item()
            rec[col] = val
        records.append(rec)

    return records


def get_stats(db_path: str) -> Dict[str, Any]:
    """Return memory statistics: total count and category distribution.

    Returns {"total": 0, "categories": {}} if the table does not exist or is empty.
    """
    memories = get_all_memories(db_path)
    if not memories:
        return {"total": 0, "categories": {}}

    category_counts = dict(Counter(m.get("category", "unknown") for m in memories))
    return {
        "total": len(memories),
        "categories": category_counts,
    }


def delete_memory(memory_id: str, db_path: str) -> bool:
    """Delete a single memory by ID.

    Returns True if the record existed and was deleted, False otherwise.
    Returns False immediately if memory_id does not match ^[0-9a-f]{64}$.
    """
    if not isinstance(memory_id, str) or not _ID_PATTERN.match(memory_id):
        return False

    try:
        if not record_exists(memory_id, db_path):
            return False
    except Exception:
        return False

    delete_records([memory_id], db_path)
    return True

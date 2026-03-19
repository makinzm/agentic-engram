"""Console logic layer for ae-console (Streamlit management UI).

Provides testable functions for memory browsing, stats, and deletion.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List

from engram.db import TABLE_NAME, get_table, record_exists, delete_records

logger = logging.getLogger(__name__)

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


def get_graph_stats(graph_path: str) -> Dict[str, Any]:
    """Return graph DB statistics. Returns {"available": False} if unavailable."""
    try:
        from engram.graph import is_graph_available
        from engram.graph import get_graph_stats as _get_graph_stats

        if not is_graph_available(graph_path):
            return {"available": False}

        stats = _get_graph_stats(graph_path)
        stats["available"] = True
        return stats
    except ImportError:
        return {"available": False}
    except Exception:
        return {"available": False}


def get_all_entities(graph_path: str) -> List[Dict[str, Any]]:
    """Return all entities sorted by mention_count descending."""
    try:
        from engram.graph import is_graph_available, get_graph_db, get_connection

        if not is_graph_available(graph_path):
            return []

        get_graph_db(graph_path)
        conn = get_connection(graph_path)
        result = conn.execute(
            "MATCH (e:Entity) RETURN e.name, e.mention_count "
            "ORDER BY e.mention_count DESC"
        )
        entities = []
        while result.has_next():
            row = result.get_next()
            entities.append({"name": row[0], "mention_count": row[1]})
        return entities
    except Exception:
        return []


def get_entity_graph(entity_name: str, graph_path: str) -> Dict[str, Any]:
    """Return neighborhood graph data for a given entity (for visualization).

    Returns empty data if graph DB is unavailable.
    """
    empty = {"entity": entity_name, "memories": [], "related_entities": []}
    try:
        from engram.graph import is_graph_available, get_entity_neighborhood

        if not is_graph_available(graph_path):
            return empty

        return get_entity_neighborhood(entity_name, graph_path)
    except ImportError:
        return empty
    except Exception:
        return empty

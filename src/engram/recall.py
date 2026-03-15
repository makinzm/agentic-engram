"""search_memories, format_output."""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Any, Optional

from engram.embedder import embed_text
from engram.db import get_table

logger = logging.getLogger(__name__)

_CATEGORY_PATTERN = re.compile(r"^[0-9A-Za-z_]+$")


def _validate_category(category: str) -> str:
    """Validate that category contains only alphanumerics and underscores."""
    if not isinstance(category, str) or not _CATEGORY_PATTERN.match(category):
        raise ValueError(
            f"Invalid category: {category!r}. "
            "Only alphanumerics and underscores are allowed."
        )
    return category


def _parse_vector_results(raw_results) -> List[Dict[str, Any]]:
    """Convert pandas DataFrame from LanceDB to list of dicts with score."""
    results = []
    for _, row in raw_results.iterrows():
        record = {}
        for col in row.index:
            if col == "vector":
                continue
            if col == "_distance":
                record["score"] = round(max(0.0, min(1.0, 1.0 - row[col])), 6)
                continue
            val = row[col]
            if hasattr(val, "tolist"):
                val = val.tolist()
            elif hasattr(val, "item"):
                val = val.item()
            record[col] = val
        results.append(record)
    return results


def _collect_entities_from_results(results: List[Dict[str, Any]]) -> List[str]:
    """Extract entity names from entities_json fields of search results."""
    entity_names = []
    for r in results:
        entities_json = r.get("entities_json", "[]")
        try:
            entities = json.loads(entities_json) if entities_json else []
            for e in entities:
                if isinstance(e, str) and e not in entity_names:
                    entity_names.append(e)
        except (json.JSONDecodeError, TypeError):
            continue
    return entity_names


def _fetch_record_by_id(memory_id: str, db_path: str) -> Optional[Dict[str, Any]]:
    """Fetch a single record from LanceDB by ID."""
    try:
        table = get_table(db_path)
        result = table.search().where(f'id = "{memory_id}"').limit(1).to_pandas()
        if result.empty:
            return None
        records = _parse_vector_results(result)
        return records[0] if records else None
    except Exception:
        return None


def search_memories(
    query: str,
    db_path: str,
    limit: int = 5,
    category: Optional[str] = None,
    graph_path: Optional[str] = None,
    graph_boost: float = 0.3,
) -> List[Dict[str, Any]]:
    """Search memories by semantic similarity with optional graph boost.

    When graph_path is provided, performs hybrid search:
    1. Vector search (LanceDB cosine similarity)
    2. Extract entities from vector results
    3. Graph traversal to find related memories
    4. Score integration with graph_boost weight
    5. Re-rank by final score

    When graph_path is None, falls back to vector-only search (V1 compatible).
    """
    if category is not None:
        _validate_category(category)

    try:
        table = get_table(db_path)
    except Exception:
        return []

    query_vector = embed_text(query)

    # When using hybrid search, fetch more results for better coverage
    vector_limit = limit * 2 if graph_path is not None else limit

    search_builder = table.search(query_vector).metric("cosine")
    if category is not None:
        search_builder = search_builder.where(f"category = '{category}'")
    search_builder = search_builder.limit(vector_limit)
    raw_results = search_builder.to_pandas()

    if raw_results.empty and graph_path is None:
        return []

    vector_results = _parse_vector_results(raw_results) if not raw_results.empty else []

    # V1 path: no graph
    if graph_path is None:
        vector_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return vector_results[:limit]

    # Hybrid path: integrate graph results
    try:
        from engram.graph import find_related_memories, is_graph_available

        if not is_graph_available(graph_path):
            # Graph not available, fall back to vector-only
            vector_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            return vector_results[:limit]

        # Collect entities from vector search results
        entity_names = _collect_entities_from_results(vector_results)

        if not entity_names:
            # No entities to traverse, return vector results
            vector_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            return vector_results[:limit]

        # Graph traversal: find related memories via entities
        graph_memories = find_related_memories(
            entity_names, graph_path, max_hops=2, limit=limit * 2
        )
        graph_memory_ids = {m["id"] for m in graph_memories}

        # Build result map keyed by memory ID
        result_map: Dict[str, Dict[str, Any]] = {}
        for r in vector_results:
            mid = r.get("id", "")
            r_copy = dict(r)
            vector_score = r_copy.get("score", 0.0)
            # Boost if also found in graph
            if mid in graph_memory_ids:
                r_copy["score"] = round(vector_score + graph_boost, 6)
            result_map[mid] = r_copy

        # Add graph-only hits (not in vector results)
        vector_ids = {r.get("id", "") for r in vector_results}
        for gm in graph_memories:
            mid = gm["id"]
            if mid not in vector_ids:
                # Fetch full record from LanceDB
                full_record = _fetch_record_by_id(mid, db_path)
                if full_record is not None:
                    full_record["score"] = round(graph_boost * 0.5, 6)
                    result_map[mid] = full_record

        # Re-rank by final score descending
        final_results = list(result_map.values())
        final_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return final_results[:limit]

    except ImportError:
        logger.warning("kuzu not available, falling back to vector-only search")
        vector_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return vector_results[:limit]
    except Exception as e:
        logger.warning("Graph search failed, falling back to vector-only: %s", e)
        vector_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return vector_results[:limit]


def format_output(results: List[Dict[str, Any]], fmt: str = "markdown") -> str:
    """Format search results as JSON or Markdown."""
    if fmt == "json":
        # Convert any non-serializable types
        serializable = []
        for r in results:
            item = {}
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    item[k] = v.isoformat()
                else:
                    item[k] = v
            serializable.append(item)
        return json.dumps(serializable, ensure_ascii=False, indent=2)

    # Markdown format
    lines = []
    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        lines.append(f"## Memory {i} (score: {score:.4f})")
        lines.append("")
        lines.append(f"- **event**: {r.get('event', '')}")
        lines.append(f"- **context**: {r.get('context', '')}")
        lines.append(f"- **core_lessons**: {r.get('core_lessons', '')}")
        lines.append(f"- **category**: {r.get('category', '')}")
        tags = r.get("tags", [])
        if isinstance(tags, list):
            lines.append(f"- **tags**: {', '.join(str(t) for t in tags)}")
        else:
            lines.append(f"- **tags**: {tags}")
        files = r.get("related_files", [])
        if isinstance(files, list):
            lines.append(f"- **related_files**: {', '.join(str(f) for f in files)}")
        else:
            lines.append(f"- **related_files**: {files}")
        lines.append("")

    return "\n".join(lines)

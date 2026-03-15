"""save_memories, generate_memory_id, SaveValidationError."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

from engram.db import insert_records, delete_records, record_exists, _ensure_table
from engram.embedder import embed_text


class SaveValidationError(Exception):
    """Validation error with error_code attribute."""

    def __init__(self, message: str, error_code: str):
        super().__init__(message)
        self.error_code = error_code


VALID_ACTIONS = {"INSERT", "UPDATE", "SKIP"}
REQUIRED_PAYLOAD_FIELDS = {"event", "context", "core_lessons", "category", "tags", "related_files", "session_id"}


def generate_memory_id(session_id: str, event: str) -> str:
    """Generate a deterministic ID from session_id + first 20 chars of event."""
    key = session_id + event[:20]
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _validate_item(item: Dict[str, Any]) -> None:
    """Validate a single payload item."""
    if "action" not in item:
        raise SaveValidationError("Missing 'action' field", "INVALID_SCHEMA")

    action = item["action"]
    if action not in VALID_ACTIONS:
        raise SaveValidationError(f"Invalid action: {action}", "INVALID_ACTION")

    if action == "SKIP":
        return

    if "payload" not in item:
        raise SaveValidationError("Missing 'payload' field", "INVALID_SCHEMA")

    payload = item["payload"]
    missing = REQUIRED_PAYLOAD_FIELDS - set(payload.keys())
    if missing:
        raise SaveValidationError(
            f"Missing required fields: {missing}", "MISSING_FIELD"
        )


def _try_sync_to_graph(
    memory_id: str,
    payload: Dict[str, Any],
    entities: List[str],
    relations: List[Dict],
    graph_path: str,
) -> None:
    """Best-effort sync to graph DB. Logs warning on failure."""
    try:
        from engram.graph import sync_to_graph

        sync_to_graph(
            memory_id=memory_id,
            event=payload["event"],
            category=payload["category"],
            timestamp=datetime.datetime.now(),
            entities=entities,
            relations=relations,
            graph_path=graph_path,
        )
    except Exception as e:
        logger.warning("Graph sync failed for %s: %s", memory_id, e)


def save_memories(
    payload: List[Dict[str, Any]],
    db_path: str,
    graph_path: Optional[str] = None,
) -> Dict[str, int]:
    """Save memories to LanceDB.

    Returns {"inserted": N, "updated": N, "skipped": N}.
    """
    result = {"inserted": 0, "updated": 0, "skipped": 0}

    # Validate all items first
    for item in payload:
        _validate_item(item)

    for item in payload:
        action = item["action"]

        if action == "SKIP":
            result["skipped"] += 1
            continue

        p = item["payload"]
        entities = item.get("entities", [])
        relations = item.get("relations", [])

        if action == "INSERT":
            memory_id = generate_memory_id(p["session_id"], p["event"])
            tags_str = " ".join(p.get("tags", []) or [])
            text = f"{p['event']} {p['context']} {p['core_lessons']} {tags_str}"
            vector = embed_text(text)

            # Check if already exists (upsert / idempotency)
            if record_exists(memory_id, db_path):
                # Overwrite: delete then re-insert
                delete_records([memory_id], db_path)

            record = {
                "id": memory_id,
                "vector": vector,
                "event": p["event"],
                "context": p["context"],
                "core_lessons": p["core_lessons"],
                "category": p["category"],
                "tags": p["tags"],
                "related_files": p["related_files"],
                "session_id": p["session_id"],
                "timestamp": datetime.datetime.now(),
                "entities_json": json.dumps(entities, ensure_ascii=False),
                "relations_json": json.dumps(relations, ensure_ascii=False),
            }
            insert_records([record], db_path)
            if graph_path is not None:
                _try_sync_to_graph(memory_id, p, entities, relations, graph_path)
            result["inserted"] += 1

        elif action == "UPDATE":
            target_id = item.get("target_id")
            try:
                target_exists = bool(target_id) and record_exists(target_id, db_path)
            except ValueError:
                target_exists = False
            if not target_exists:
                raise SaveValidationError(
                    f"Target record not found: {target_id}", "TARGET_NOT_FOUND"
                )

            tags_str = " ".join(p.get("tags", []) or [])
            text = f"{p['event']} {p['context']} {p['core_lessons']} {tags_str}"
            vector = embed_text(text)

            delete_records([target_id], db_path)

            record = {
                "id": target_id,
                "vector": vector,
                "event": p["event"],
                "context": p["context"],
                "core_lessons": p["core_lessons"],
                "category": p["category"],
                "tags": p["tags"],
                "related_files": p["related_files"],
                "session_id": p["session_id"],
                "timestamp": datetime.datetime.now(),
                "entities_json": json.dumps(entities, ensure_ascii=False),
                "relations_json": json.dumps(relations, ensure_ascii=False),
            }
            insert_records([record], db_path)
            if graph_path is not None:
                _try_sync_to_graph(target_id, p, entities, relations, graph_path)
            result["updated"] += 1

    return result

"""Kuzu graph DB: init, CRUD, search for entity-memory relationships."""

from __future__ import annotations

import datetime
import logging
import os
from typing import Dict, List, Optional

import kuzu

logger = logging.getLogger(__name__)

# Cache open databases to avoid re-opening in the same process
_db_cache: Dict[str, kuzu.Database] = {}
_schema_initialized: set = set()

_DDL_STATEMENTS = [
    (
        "CREATE NODE TABLE IF NOT EXISTS Entity("
        "name STRING, "
        "first_seen TIMESTAMP, "
        "last_seen TIMESTAMP, "
        "mention_count INT64 DEFAULT 0, "
        "PRIMARY KEY(name))"
    ),
    (
        "CREATE NODE TABLE IF NOT EXISTS Memory("
        "id STRING, "
        "event STRING, "
        "category STRING, "
        "timestamp TIMESTAMP, "
        "PRIMARY KEY(id))"
    ),
    "CREATE REL TABLE IF NOT EXISTS MENTIONS(FROM Memory TO Entity)",
    (
        "CREATE REL TABLE IF NOT EXISTS RELATES_TO("
        "FROM Entity TO Entity, "
        "rel_type STRING, "
        "memory_id STRING, "
        "created_at TIMESTAMP)"
    ),
]


def get_graph_db(graph_path: str) -> kuzu.Database:
    """Open (or create) a Kuzu DB at *graph_path* and ensure the schema exists."""
    if graph_path in _db_cache:
        db = _db_cache[graph_path]
    else:
        db = kuzu.Database(graph_path)
        _db_cache[graph_path] = db

    if graph_path not in _schema_initialized:
        conn = kuzu.Connection(db)
        for ddl in _DDL_STATEMENTS:
            conn.execute(ddl)
        _schema_initialized.add(graph_path)

    return db


def close_graph_db(graph_path: str) -> None:
    """Close and remove a cached DB instance. Useful for tests."""
    _schema_initialized.discard(graph_path)
    db = _db_cache.pop(graph_path, None)
    if db is not None:
        del db


def is_graph_available(graph_path: str) -> bool:
    """Return True if the graph DB directory exists and can be opened."""
    if not os.path.exists(graph_path):
        return False
    try:
        get_graph_db(graph_path)
        return True
    except Exception:
        return False


def sync_to_graph(
    memory_id: str,
    event: str,
    category: str,
    timestamp: datetime.datetime,
    entities: List[str],
    relations: List[Dict],
    graph_path: str,
) -> None:
    """Sync a memory + entities + relations to the graph.

    Idempotent: if the Memory node already exists, its edges are deleted and
    rebuilt so a re-sync produces the same result.
    """
    db = get_graph_db(graph_path)
    conn = kuzu.Connection(db)

    # If memory already exists, clean up its edges first
    _result = conn.execute(
        "MATCH (m:Memory {id: $mid}) RETURN count(m)", {"mid": memory_id}
    )
    if _result.has_next() and _result.get_next()[0] > 0:
        # Get entities that this memory mentions (for decrementing counts)
        old_entities_result = conn.execute(
            "MATCH (m:Memory {id: $mid})-[:MENTIONS]->(e:Entity) RETURN e.name",
            {"mid": memory_id},
        )
        old_entity_names = []
        while old_entities_result.has_next():
            old_entity_names.append(old_entities_result.get_next()[0])

        # Decrement mention_count for old entities
        for name in old_entity_names:
            conn.execute(
                "MATCH (e:Entity {name: $name}) "
                "SET e.mention_count = e.mention_count - 1",
                {"name": name},
            )

        # Delete MENTIONS edges
        conn.execute(
            "MATCH (m:Memory {id: $mid})-[r:MENTIONS]->() DELETE r",
            {"mid": memory_id},
        )

        # Delete RELATES_TO edges associated with this memory
        conn.execute(
            "MATCH ()-[r:RELATES_TO {memory_id: $mid}]->() DELETE r",
            {"mid": memory_id},
        )

    # MERGE Memory node
    conn.execute(
        "MERGE (m:Memory {id: $mid}) "
        "SET m.event = $event, m.category = $category, m.timestamp = $ts",
        {"mid": memory_id, "event": event, "category": category, "ts": timestamp},
    )

    # MERGE Entity nodes and MENTIONS edges
    for entity_name in entities:
        conn.execute(
            "MERGE (e:Entity {name: $name}) "
            "ON CREATE SET e.first_seen = $ts, e.last_seen = $ts, e.mention_count = 1 "
            "ON MATCH SET e.last_seen = $ts, e.mention_count = e.mention_count + 1",
            {"name": entity_name, "ts": timestamp},
        )
        conn.execute(
            "MATCH (m:Memory {id: $mid}), (e:Entity {name: $name}) "
            "MERGE (m)-[:MENTIONS]->(e)",
            {"mid": memory_id, "name": entity_name},
        )

    # MERGE RELATES_TO edges
    for rel in relations:
        source = rel.get("source", "")
        target = rel.get("target", "")
        rel_type = rel.get("type", "RELATED")
        if not source or not target:
            continue

        # Ensure source and target entities exist
        for ename in (source, target):
            conn.execute(
                "MERGE (e:Entity {name: $name}) "
                "ON CREATE SET e.first_seen = $ts, e.last_seen = $ts, e.mention_count = 0",
                {"name": ename, "ts": timestamp},
            )

        conn.execute(
            "MATCH (e1:Entity {name: $src}), (e2:Entity {name: $tgt}) "
            "MERGE (e1)-[:RELATES_TO {rel_type: $rt, memory_id: $mid, created_at: $ca}]->(e2)",
            {
                "src": source,
                "tgt": target,
                "rt": rel_type,
                "mid": memory_id,
                "ca": timestamp,
            },
        )


def remove_from_graph(memory_id: str, graph_path: str) -> None:
    """Remove a Memory node and its MENTIONS / RELATES_TO edges.

    Decrements mention_count on related Entity nodes.
    """
    db = get_graph_db(graph_path)
    conn = kuzu.Connection(db)

    # Get entities mentioned by this memory
    result = conn.execute(
        "MATCH (m:Memory {id: $mid})-[:MENTIONS]->(e:Entity) RETURN e.name",
        {"mid": memory_id},
    )
    entity_names: List[str] = []
    while result.has_next():
        entity_names.append(result.get_next()[0])

    # Decrement mention_count
    for name in entity_names:
        conn.execute(
            "MATCH (e:Entity {name: $name}) "
            "SET e.mention_count = e.mention_count - 1",
            {"name": name},
        )

    # Delete RELATES_TO edges associated with this memory
    conn.execute(
        "MATCH ()-[r:RELATES_TO {memory_id: $mid}]->() DELETE r",
        {"mid": memory_id},
    )

    # Delete MENTIONS edges
    conn.execute(
        "MATCH (m:Memory {id: $mid})-[r:MENTIONS]->() DELETE r",
        {"mid": memory_id},
    )

    # Delete Memory node
    conn.execute(
        "MATCH (m:Memory {id: $mid}) DELETE m",
        {"mid": memory_id},
    )


def find_related_memories(
    entity_names: List[str],
    graph_path: str,
    max_hops: int = 2,
    limit: int = 10,
) -> List[Dict]:
    """Find Memory nodes reachable from *entity_names* within *max_hops*."""
    if not entity_names:
        return []

    db = get_graph_db(graph_path)
    conn = kuzu.Connection(db)

    all_ids: List[str] = []

    for entity_name in entity_names:
        # Check entity exists
        check = conn.execute(
            "MATCH (e:Entity {name: $name}) RETURN count(e)",
            {"name": entity_name},
        )
        if check.has_next() and check.get_next()[0] == 0:
            continue

        # Variable-length path from entity to memory
        query = (
            f"MATCH (start:Entity {{name: $name}})-[*1..{max_hops}]-(m:Memory) "
            "RETURN DISTINCT m.id, m.event, m.category, m.timestamp"
        )
        result = conn.execute(query, {"name": entity_name})
        while result.has_next():
            row = result.get_next()
            mid = row[0]
            if mid not in all_ids:
                all_ids.append(mid)

    # Re-fetch details for deduplication and ordering
    if not all_ids:
        return []

    memories: List[Dict] = []
    for mid in all_ids[:limit]:
        result = conn.execute(
            "MATCH (m:Memory {id: $mid}) RETURN m.id, m.event, m.category, m.timestamp",
            {"mid": mid},
        )
        if result.has_next():
            row = result.get_next()
            memories.append({
                "id": row[0],
                "event": row[1],
                "category": row[2],
                "timestamp": row[3],
            })

    return memories


def get_entity_neighborhood(
    entity_name: str,
    graph_path: str,
    max_hops: int = 1,
) -> Dict:
    """Return the neighborhood of an entity: memories and related entities."""
    db = get_graph_db(graph_path)
    conn = kuzu.Connection(db)

    # Memories that mention this entity
    result = conn.execute(
        "MATCH (m:Memory)-[:MENTIONS]->(e:Entity {name: $name}) "
        "RETURN m.id, m.event, m.category",
        {"name": entity_name},
    )
    memories = []
    while result.has_next():
        row = result.get_next()
        memories.append({"id": row[0], "event": row[1], "category": row[2]})

    # Related entities (via RELATES_TO in either direction)
    result = conn.execute(
        "MATCH (e:Entity {name: $name})-[r:RELATES_TO]-(other:Entity) "
        "RETURN other.name, r.rel_type",
        {"name": entity_name},
    )
    related_entities = []
    while result.has_next():
        row = result.get_next()
        related_entities.append({"name": row[0], "rel_type": row[1]})

    return {
        "entity": entity_name,
        "memories": memories,
        "related_entities": related_entities,
    }


def get_graph_stats(graph_path: str) -> Dict:
    """Return basic statistics about the graph."""
    db = get_graph_db(graph_path)
    conn = kuzu.Connection(db)

    def _count(query: str) -> int:
        result = conn.execute(query)
        if result.has_next():
            return result.get_next()[0]
        return 0

    memory_count = _count("MATCH (m:Memory) RETURN count(m)")
    entity_count = _count("MATCH (e:Entity) RETURN count(e)")
    mentions_count = _count("MATCH ()-[r:MENTIONS]->() RETURN count(r)")
    relates_to_count = _count("MATCH ()-[r:RELATES_TO]->() RETURN count(r)")

    # Top entities by mention_count
    result = conn.execute(
        "MATCH (e:Entity) RETURN e.name, e.mention_count "
        "ORDER BY e.mention_count DESC LIMIT 10"
    )
    top_entities = []
    while result.has_next():
        row = result.get_next()
        top_entities.append({"name": row[0], "mention_count": row[1]})

    return {
        "memory_count": memory_count,
        "entity_count": entity_count,
        "mentions_count": mentions_count,
        "relates_to_count": relates_to_count,
        "top_entities": top_entities,
    }

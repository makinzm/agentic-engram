# Agentic Engram

**Autonomous local memory ecosystem for AI coding agents -- inspired by how human memory works.**

Agentic Engram captures raw development session logs, extracts reusable knowledge via LLM, and stores it in a local vector database. Agents can then recall past lessons by semantic search -- no cloud, no Docker, no running server.

## Concept

```mermaid
flowchart LR
    A["Terminal Session\n(script command)"] -->|raw log| B["short-term-memory/"]
    B -->|diff via mtime + cursor| C["ae-miner\n(LLM extraction)"]
    C -->|JSON| D["ae-save\n(LanceDB + embeddings)"]
    D --> E["memory-db/\nvector_store"]
    E -->|semantic search| F["ae-recall"]
    F -->|context| A
    E --> G["ae-console\n(Streamlit UI)"]
```

**Lifecycle:**

1. **Capture** -- `script` command streams terminal I/O into `~/.engram/short-term-memory/`.
2. **Mine** -- `ae-miner` (cron) detects changed logs via `mtime` + line-pointer cursor, sends diffs to an LLM, which decides INSERT / UPDATE / SKIP.
3. **Store** -- `ae-save` embeds payloads with `sentence-transformers` and upserts into LanceDB.
4. **Recall** -- `ae-recall` performs cosine-similarity search. Agents call it autonomously when they hit unknown errors.
5. **Manage** -- `ae-console` provides a Streamlit dashboard for browsing, searching, and deleting memories.

## Features

- Fully local, zero-overhead -- file-system based, no external APIs or servers required
- Filebeat-style crash resilience -- state tracked by `mtime` + line pointer only, no status flags
- Deterministic IDs (SHA-256) for idempotent upserts
- Semantic search via LanceDB + `paraphrase-multilingual-MiniLM-L12-v2` (384-dim)
- Category and tag filtering
- TTL-based auto-archiving of stale logs
- Streamlit management console
- Graph DB extension points (`entities_json`, `relations_json`) reserved for V2

## Quick Start

### Requirements

- Python 3.9+
- LLM provider (OpenAI, Anthropic, etc.): **not required** for `ae-save`, `ae-recall`, or `ae-console`. `ae-miner` is designed to use an LLM for log extraction, but CLI-level integration is not yet implemented.

### Install

```bash
pip install -e ".[dev]"
```

### Record a session

```bash
script -q -a ~/.engram/short-term-memory/session_$(date +%Y%m%d_%H%M%S)_log.txt
```

### Save a memory manually

```bash
echo '[{"action":"INSERT","payload":{"event":"CORS error with Ollama","context":"Direct fetch from Next.js client","core_lessons":"Use Route Handler as proxy","category":"architecture","tags":["Next.js","CORS"],"related_files":["app/api/chat/route.ts"],"session_id":"session_001"}}]' \
  | python scripts/ae-save.py
```

### Search memories

```bash
python scripts/ae-recall.py --query "CORS error" --format markdown
python scripts/ae-recall.py --query "CORS error" --format json --limit 3
```

### Run the miner

> **Note:** LLM integration in `ae-miner` is not yet implemented at the CLI level.
> Only `--dry-run` is functional; it previews the list of target log files without processing them.

```bash
python scripts/ae-miner.py --dry-run       # preview target log files (no LLM required)
```

### Launch the console

```bash
streamlit run scripts/ae-console.py
```

## Architecture

```
~/.engram/
  short-term-memory/     Raw session logs (short-term memory)
    archive/             TTL-expired logs
  memory-db/
    vector_store/        LanceDB data (semantic search)
    graph_store/         [V2] Kuzu data (logical network)
  config/
    cursor.json          Line pointer + mtime per log file
```

| Component | File | Role |
|-----------|------|------|
| `db` | `src/engram/db.py` | LanceDB connection, schema, CRUD |
| `save` | `src/engram/save.py` | Validation, ID generation, upsert logic |
| `recall` | `src/engram/recall.py` | Semantic search, output formatting |
| `miner` | `src/engram/miner.py` | Log scanning, diff reading, LLM orchestration, archiving |
| `cursor` | `src/engram/cursor.py` | Atomic cursor.json state management |
| `prompts` | `src/engram/prompts.py` | LLM prompt construction for extraction |
| `embedder` | `src/engram/embedder.py` | Sentence-transformers singleton wrapper |
| `console` | `src/engram/console.py` | Streamlit UI logic (stats, browse, delete) |

## CLI Reference

### ae-save

Reads a JSON array from stdin, validates, embeds, and upserts into LanceDB.

```
python scripts/ae-save.py [--db-path PATH]
```

### ae-recall

Searches memories by semantic similarity.

```
python scripts/ae-recall.py --query "..." [--format json|markdown] [--limit N] [--category CAT]
```

### ae-miner

Scans session logs, extracts knowledge via LLM, saves to memory DB.

```
python scripts/ae-miner.py [--log-dir DIR] [--db-path PATH] [--cursor-path PATH]
                           [--archive-dir DIR] [--ttl-days N] [--dry-run]
```

### ae-console

Streamlit web dashboard for memory management.

```
streamlit run scripts/ae-console.py
```

## Development

```bash
pip install -e ".[dev]"
pytest -v
```

## Roadmap

- **V2: Graph DB extension** -- Integrate [Kuzu](https://kuzudb.com/) to materialize `entities_json` / `relations_json` into a property graph, enabling GraphRAG-style hybrid retrieval (vector similarity + logical traversal).

## License

[Apache License 2.0](LICENSE)

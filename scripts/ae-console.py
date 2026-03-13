"""ae-console: Streamlit management UI for Agentic Engram memories."""

import os

import streamlit as st

from engram.console import get_all_memories, get_stats, delete_memory
from engram.recall import search_memories, format_output

DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".engram", "memory-db", "vector_store")

st.set_page_config(page_title="Agentic Engram Console", layout="wide")
st.title("Agentic Engram Console")

db_path = st.sidebar.text_input("DB Path", value=DEFAULT_DB_PATH)

# --- Statistics ---
st.header("Statistics")
stats = get_stats(db_path)
col1, col2 = st.columns(2)
with col1:
    st.metric("Total Memories", stats["total"])
with col2:
    if stats["categories"]:
        st.bar_chart(stats["categories"])
    else:
        st.info("No memories stored yet.")

# --- Search ---
st.header("Search")
query = st.text_input("Semantic search query")
search_limit = st.slider("Max results", 1, 20, 5)
search_category = st.text_input("Filter by category (optional)")

if st.button("Search") and query:
    try:
        cat = search_category.strip() if search_category.strip() else None
        results = search_memories(query, db_path=db_path, limit=search_limit, category=cat)
        if results:
            st.markdown(format_output(results, fmt="markdown"))
        else:
            st.warning("No results found.")
    except ValueError as e:
        st.error(f"カテゴリフィルターの入力が不正です: {e}")

# --- Memory List ---
st.header("All Memories")
memories = get_all_memories(db_path)

if memories:
    # Build display data
    display_data = []
    for m in memories:
        tags = m.get("tags", [])
        if isinstance(tags, list):
            tags = ", ".join(str(t) for t in tags)
        display_data.append(
            {
                "id": m.get("id", "")[:12] + "...",
                "event": m.get("event", ""),
                "category": m.get("category", ""),
                "tags": tags,
                "session_id": m.get("session_id", ""),
                "timestamp": m.get("timestamp", ""),
                "full_id": m.get("id", ""),
            }
        )

    st.dataframe(
        [
            {k: v for k, v in d.items() if k != "full_id"}
            for d in display_data
        ],
        use_container_width=True,
    )

    # --- Delete ---
    st.header("Delete Memory")
    id_options = [d["full_id"] for d in display_data]
    selected_id = st.selectbox("Select memory ID to delete", id_options)

    if st.button("Delete", type="primary"):
        if delete_memory(selected_id, db_path):
            st.success(f"Deleted memory: {selected_id[:12]}...")
            st.rerun()
        else:
            st.error("Failed to delete. Memory may not exist.")
else:
    st.info("No memories found in the database.")

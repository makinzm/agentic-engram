"""ae-console: Streamlit management UI for Agentic Engram memories."""

import os

import streamlit as st

from engram.console import (
    get_all_memories, get_stats, delete_memory,
    get_graph_stats, get_entity_graph,
)
from engram.recall import search_memories, format_output

DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".engram", "memory-db", "vector_store")
DEFAULT_GRAPH_PATH = os.path.join(os.path.expanduser("~"), ".engram", "memory-db", "graph_store")

st.set_page_config(page_title="Agentic Engram Console", layout="wide")
st.title("Agentic Engram Console")

db_path = st.sidebar.text_input("DB Path", value=DEFAULT_DB_PATH)
graph_path = st.sidebar.text_input("Graph Path", value=DEFAULT_GRAPH_PATH)

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

use_graph = st.checkbox("Enable graph-boosted search", value=True)

if st.button("Search") and query:
    try:
        cat = search_category.strip() if search_category.strip() else None
        gp = graph_path if use_graph else None
        results = search_memories(
            query, db_path=db_path, limit=search_limit, category=cat,
            graph_path=gp,
        )
        if results:
            st.markdown(format_output(results, fmt="markdown"))
        else:
            st.warning("No results found.")
    except ValueError as e:
        st.error(f"Invalid category filter: {e}")

# --- Memory List ---
st.header("All Memories")
memories = get_all_memories(db_path)

if memories:
    # Build display data — show all columns, stringify lists for readability
    display_data = []
    for m in memories:
        row = {}
        for k, v in m.items():
            if isinstance(v, list):
                v = ", ".join(str(item) for item in v)
            row[k] = v
        display_data.append(row)

    st.dataframe(display_data, use_container_width=True)

    # --- Delete ---
    st.header("Delete Memory")
    id_options = [m.get("id", "") for m in memories]
    selected_id = st.selectbox("Select memory ID to delete", id_options)

    if st.button("Delete", type="primary"):
        if delete_memory(selected_id, db_path):
            st.success(f"Deleted memory: {selected_id[:12]}...")
            st.rerun()
        else:
            st.error("Failed to delete. Memory may not exist.")
else:
    st.info("No memories found in the database.")

# --- Graph Statistics ---
st.header("Graph Statistics")
gstats = get_graph_stats(graph_path)

if gstats.get("available"):
    gcol1, gcol2, gcol3, gcol4 = st.columns(4)
    with gcol1:
        st.metric("Entities", gstats.get("entity_count", 0))
    with gcol2:
        st.metric("Memories (graph)", gstats.get("memory_count", 0))
    with gcol3:
        st.metric("MENTIONS edges", gstats.get("mentions_count", 0))
    with gcol4:
        st.metric("RELATES_TO edges", gstats.get("relates_to_count", 0))

    top_entities = gstats.get("top_entities", [])
    if top_entities:
        st.subheader("Top 10 Entities (by mention count)")
        st.dataframe(top_entities, use_container_width=True)
else:
    st.info("Graph database is not available. Save memories with --graph-path to enable.")

# --- Entity Explorer ---
st.header("Entity Explorer")

if gstats.get("available"):
    top_entities = gstats.get("top_entities", [])
    entity_names = [e["name"] for e in top_entities] if top_entities else []

    if entity_names:
        selected_entity = st.selectbox("Select entity to explore", entity_names)

        if selected_entity:
            neighborhood = get_entity_graph(selected_entity, graph_path)

            if neighborhood["memories"] or neighborhood["related_entities"]:
                # Build Graphviz DOT string
                dot_lines = ["digraph {", '  rankdir=LR;', '  node [shape=box];']
                dot_lines.append(
                    f'  "{selected_entity}" [shape=ellipse, style=filled, fillcolor=lightblue];'
                )

                for mem in neighborhood["memories"]:
                    mid_short = mem["id"][:12]
                    label = mem.get("event", "")[:40].replace('"', '\\"')
                    dot_lines.append(f'  "{mid_short}" [label="{label}"];')
                    dot_lines.append(f'  "{mid_short}" -> "{selected_entity}" [label="MENTIONS"];')

                for rel in neighborhood["related_entities"]:
                    rname = rel["name"]
                    rtype = rel.get("rel_type", "RELATED")
                    dot_lines.append(
                        f'  "{rname}" [shape=ellipse, style=filled, fillcolor=lightyellow];'
                    )
                    dot_lines.append(f'  "{selected_entity}" -> "{rname}" [label="{rtype}"];')

                dot_lines.append("}")
                st.graphviz_chart("\n".join(dot_lines))
            else:
                st.info(f"No connections found for entity: {selected_entity}")
    else:
        st.info("No entities in the graph yet.")
else:
    st.info("Graph database is not available.")

"""DAO for knowledge_graph_edges table.

知识图谱边 — 记录知识点间的关系。
初始阶段只支持 is_prerequisite 和 extends 两种自动推断关系。
"""

import json
from typing import Optional

from .database import get_connection, row_to_dict, rows_to_dicts


def add_edge(
    user_id: int,
    source_node_id: int,
    target_node_id: int,
    relation_type: str,
    description: str = "",
    confidence: int = 1,
) -> dict:
    """Add a knowledge graph edge. Returns the created edge."""
    conn = get_connection()
    try:
        try:
            cur = conn.execute(
                """INSERT INTO knowledge_graph_edges
                   (user_id, source_node_id, target_node_id, relation_type, description, confidence)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, source_node_id, target_node_id, relation_type, description, confidence),
            )
            conn.commit()
            return get_edge(cur.lastrowid)
        except conn.IntegrityError:
            # Unique constraint violation — return existing
            row = conn.execute(
                "SELECT * FROM knowledge_graph_edges WHERE user_id=? AND source_node_id=? "
                "AND target_node_id=? AND relation_type=?",
                (user_id, source_node_id, target_node_id, relation_type),
            ).fetchone()
            return row_to_dict(row)
    finally:
        conn.close()


def get_edge(edge_id: int) -> Optional[dict]:
    """Get a single edge by ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM knowledge_graph_edges WHERE id = ?",
            (edge_id,),
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_edges(user_id: int, relation_type: Optional[str] = None) -> list[dict]:
    """List all edges for a user, optionally filtered by relation type."""
    conn = get_connection()
    try:
        if relation_type:
            rows = conn.execute(
                "SELECT * FROM knowledge_graph_edges WHERE user_id=? AND relation_type=? ORDER BY created_at",
                (user_id, relation_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_graph_edges WHERE user_id=? ORDER BY relation_type, created_at",
                (user_id,),
            ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def delete_edge(edge_id: int) -> bool:
    """Delete an edge by ID."""
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM knowledge_graph_edges WHERE id = ?", (edge_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_graph(user_id: int) -> dict:
    """Get the full knowledge graph as nodes + edges structure."""
    edges = list_edges(user_id)

    # Collect unique node IDs
    node_ids = set()
    for e in edges:
        node_ids.add(e["source_node_id"])
        node_ids.add(e["target_node_id"])

    # Fetch node names
    nodes = {}
    if node_ids:
        conn = get_connection()
        try:
            placeholders = ",".join("?" * len(node_ids))
            rows = conn.execute(
                f"SELECT id, name, current_level FROM knowledge_nodes WHERE id IN ({placeholders})",
                list(node_ids),
            ).fetchall()
            for r in rows:
                nodes[r["id"]] = {"id": r["id"], "name": r["name"], "level": r["current_level"]}
        finally:
            conn.close()

    return {
        "nodes": list(nodes.values()),
        "edges": [dict(e) for e in edges],
    }

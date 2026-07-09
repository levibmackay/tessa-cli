"""SQLite storage for the semantic search index (Milestone 2 retrieval).

One `.tessa/index.sqlite3` per project. Embeddings are stored as raw
float32 blobs rather than JSON text — an order of magnitude smaller and
avoids re-parsing floats on every query.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DB_FILE_NAME = "index.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
"""


@dataclass
class StoredChunk:
    id: int
    path: str
    start_line: int
    end_line: int
    text: str
    embedding: np.ndarray


def db_path(project_root: Path) -> Path:
    return project_root / ".tessa" / DB_FILE_NAME


def connect(project_root: Path) -> sqlite3.Connection:
    path = db_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


def file_hashes(conn: sqlite3.Connection) -> dict[str, str]:
    """The content_hash currently stored for each indexed path.

    All chunks belonging to one file share the same hash (the file's own
    hash at index time), so DISTINCT collapses cleanly per path.
    """
    rows = conn.execute("SELECT DISTINCT path, content_hash FROM chunks").fetchall()
    return dict(rows)


def indexed_paths(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT DISTINCT path FROM chunks")}


def delete_path(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM chunks WHERE path = ?", (path,))


def insert_chunks(conn: sqlite3.Connection, chunks: list, embeddings: list[list[float]]) -> None:
    conn.executemany(
        "INSERT INTO chunks (path, start_line, end_line, text, content_hash, embedding) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                c.path, c.start_line, c.end_line, c.text, c.content_hash,
                np.asarray(emb, dtype=np.float32).tobytes(),
            )
            for c, emb in zip(chunks, embeddings)
        ],
    )


def all_chunks(conn: sqlite3.Connection) -> list[StoredChunk]:
    rows = conn.execute("SELECT id, path, start_line, end_line, text, embedding FROM chunks").fetchall()
    return [
        StoredChunk(
            id=r[0], path=r[1], start_line=r[2], end_line=r[3], text=r[4],
            embedding=np.frombuffer(r[5], dtype=np.float32),
        )
        for r in rows
    ]


def chunk_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

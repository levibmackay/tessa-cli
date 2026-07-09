"""Semantic search over the chunk index built by context/indexer.py."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tessa.context.indexer import EMBED_MODEL
from tessa.database import sqlite as db
from tessa.llm.client import OllamaClient


@dataclass
class SearchResult:
    path: str
    start_line: int
    end_line: int
    text: str
    score: float


def is_indexed(project_root: Path) -> bool:
    if not db.db_path(project_root).exists():
        return False
    conn = db.connect(project_root)
    try:
        return db.chunk_count(conn) > 0
    finally:
        conn.close()


def search(project_root: Path, client: OllamaClient, query: str, top_k: int = 8) -> list[SearchResult]:
    conn = db.connect(project_root)
    try:
        chunks = db.all_chunks(conn)
        if not chunks:
            return []
        [query_vector] = client.embed(EMBED_MODEL, [query])
        query_vector = np.asarray(query_vector, dtype=np.float32)
        query_norm = np.linalg.norm(query_vector)
        if query_norm == 0:
            return []

        scored: list[tuple[float, db.StoredChunk]] = []
        for chunk in chunks:
            chunk_norm = np.linalg.norm(chunk.embedding)
            if chunk_norm == 0:
                continue
            similarity = float(np.dot(query_vector, chunk.embedding) / (query_norm * chunk_norm))
            scored.append((similarity, chunk))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        return [
            SearchResult(path=c.path, start_line=c.start_line, end_line=c.end_line, text=c.text, score=score)
            for score, c in scored[:top_k]
        ]
    finally:
        conn.close()

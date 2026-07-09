"""Tests for the SQLite chunk store."""

from pathlib import Path

import numpy as np

from tessa.context.indexer import Chunk
from tessa.database import sqlite as db


def make_chunk(path: str = "a.py", start: int = 1, end: int = 5, text: str = "code", h: str = "hash1") -> Chunk:
    return Chunk(path=path, start_line=start, end_line=end, text=text, content_hash=h)


def test_insert_and_read_back_chunks(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    chunks = [make_chunk(start=1, end=5), make_chunk(start=6, end=10)]
    embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    db.insert_chunks(conn, chunks, embeddings)
    conn.commit()

    stored = db.all_chunks(conn)
    assert len(stored) == 2
    assert stored[0].path == "a.py"
    np.testing.assert_allclose(stored[0].embedding, np.array([0.1, 0.2, 0.3], dtype=np.float32), rtol=1e-5)
    conn.close()


def test_file_hashes_collapses_per_path(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    db.insert_chunks(conn, [make_chunk(start=1, end=5, h="abc"), make_chunk(start=6, end=10, h="abc")], [[0.1], [0.2]])
    conn.commit()
    assert db.file_hashes(conn) == {"a.py": "abc"}
    conn.close()


def test_delete_path_removes_all_its_chunks(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    db.insert_chunks(conn, [make_chunk(path="a.py"), make_chunk(path="b.py")], [[0.1], [0.2]])
    conn.commit()
    db.delete_path(conn, "a.py")
    conn.commit()
    remaining = db.all_chunks(conn)
    assert [c.path for c in remaining] == ["b.py"]
    conn.close()


def test_indexed_paths_and_chunk_count(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    db.insert_chunks(conn, [make_chunk(path="a.py"), make_chunk(path="a.py"), make_chunk(path="b.py")], [[0.1], [0.2], [0.3]])
    conn.commit()
    assert db.indexed_paths(conn) == {"a.py", "b.py"}
    assert db.chunk_count(conn) == 3
    conn.close()


def test_db_persists_across_connections(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    db.insert_chunks(conn, [make_chunk()], [[0.1, 0.2]])
    conn.commit()
    conn.close()

    conn2 = db.connect(tmp_path)
    assert db.chunk_count(conn2) == 1
    conn2.close()

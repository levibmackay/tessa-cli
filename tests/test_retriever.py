"""Tests for semantic search ranking."""

from pathlib import Path

from tessa.context.indexer import Chunk
from tessa.context.retriever import is_indexed, search
from tessa.database import sqlite as db


class FakeEmbedClient:
    """Returns pre-programmed vectors keyed by exact input text."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in inputs]


def seed(tmp_path: Path, chunks_and_vectors: list[tuple[str, list[float]]]) -> None:
    conn = db.connect(tmp_path)
    chunks = [
        Chunk(path=f"file{i}.py", start_line=1, end_line=5, text=text, content_hash="h")
        for i, (text, _) in enumerate(chunks_and_vectors)
    ]
    embeddings = [vec for _, vec in chunks_and_vectors]
    db.insert_chunks(conn, chunks, embeddings)
    conn.commit()
    conn.close()


def test_is_indexed_false_when_no_db(tmp_path: Path) -> None:
    assert is_indexed(tmp_path) is False


def test_is_indexed_true_after_chunks_inserted(tmp_path: Path) -> None:
    seed(tmp_path, [("some code", [1.0, 0.0])])
    assert is_indexed(tmp_path) is True


def test_search_ranks_by_cosine_similarity(tmp_path: Path) -> None:
    # "auth code" should rank closer to the query than "unrelated code"
    seed(tmp_path, [
        ("handles user login", [1.0, 0.0]),
        ("totally unrelated math", [0.0, 1.0]),
    ])
    client = FakeEmbedClient({"authentication": [1.0, 0.0]})
    results = search(tmp_path, client, "authentication", top_k=2)

    assert len(results) == 2
    assert results[0].text == "handles user login"
    assert results[0].score > results[1].score


def test_search_respects_top_k(tmp_path: Path) -> None:
    seed(tmp_path, [(f"chunk {i}", [1.0, float(i)]) for i in range(5)])
    client = FakeEmbedClient({"query": [1.0, 0.0]})
    results = search(tmp_path, client, "query", top_k=2)
    assert len(results) == 2


def test_search_empty_index_returns_nothing(tmp_path: Path) -> None:
    client = FakeEmbedClient({"query": [1.0, 0.0]})
    assert search(tmp_path, client, "query") == []

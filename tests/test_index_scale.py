"""Scale check (slow, run by hand): `pytest -m slow tests/test_index_scale.py -s`."""

import statistics
import time
from pathlib import Path

import numpy as np
import pytest

from secondbrain.index import SCHEMA, Index

DIM = 768
CHUNKS = 200_000


class RandomEmbedder:
    name = "random-768"

    def __init__(self):
        self.rng = np.random.default_rng(1)

    def embed(self, texts):
        return [self.rng.standard_normal(DIM).tolist() for _ in texts]


def build_big_index(path: Path, chunks: int) -> Index:
    index = Index(path, RandomEmbedder())
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    con = index._connect()
    index._create_tables(con)
    con.execute("CREATE INDEX idx_chunks_card ON chunks(card_id)")
    con.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for key, value in (("schema", SCHEMA), ("embedder", index._embedder_name()), ("dim", str(DIM)), ("version", "1")):
        con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    per_card = 4
    con.execute("BEGIN")
    for c in range(chunks // per_card):
        con.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,NULL,NULL,NULL)",
                    (f"tg_{c}", "telegram", f"note {c}", "2026-11-20", 50.0, 0, "s", "hot"))
    for start in range(0, chunks, 5000):
        vecs = rng.standard_normal((min(5000, chunks - start), DIM)).astype(np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        rows = []
        for j, vec in enumerate(vecs.astype(np.float16)):
            i = start + j
            rows.append((f"tg_{i // per_card}", i % per_card, f"word{i % 997} filler text number {i}", vec.tobytes()))
        cur = con.executemany("INSERT INTO chunks(card_id, ord, text, vec) VALUES (?,?,?,?)", rows)
        first = con.execute("SELECT max(id) FROM chunks").fetchone()[0] - len(rows) + 1
        con.executemany("INSERT INTO fts(rowid, text, source, local) VALUES (?,?,?,0)",
                        [(first + j, r[2], "telegram") for j, r in enumerate(rows)])
    con.execute("COMMIT")
    con.close()
    return index


@pytest.mark.slow
def test_two_hundred_thousand_chunks_query_under_300ms_warm(tmp_path: Path):
    t = time.time()
    index = build_big_index(tmp_path / "big.db", CHUNKS)
    print(f"\nbuilt {index.chunk_count()} chunks in {time.time() - t:.1f}s")
    t = time.time()
    index.search("word42 filler text")  # cold: loads the matrix into memory
    cold = time.time() - t
    times = []
    for q in ("word7 filler", "word500 text number", "word999 note", "filler text", "word123 number"):
        t = time.time()
        hits = index.search(q, k=8)
        times.append(time.time() - t)
        assert hits
    filtered = []
    for q in ("word7 filler", "word500 text number", "word999 note", "filler text", "word123 number"):
        t = time.time()
        assert index.search(q, k=8, include_local_only=False, sources=frozenset({"telegram", "mentor"}))
        filtered.append(time.time() - t)
    print(f"filtered (as /ask searches) warm median {statistics.median(filtered) * 1000:.0f} ms")
    assert statistics.median(filtered) < 0.3
    warm = statistics.median(times)
    print(f"cold first query {cold:.2f}s | warm median {warm * 1000:.0f} ms | max {max(times) * 1000:.0f} ms")
    assert index.cache_reloads == 1
    assert warm < 0.3

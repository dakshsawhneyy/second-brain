"""Local search index: SQLite FTS5 (keywords) + vectors, ranked by relevance. Rebuildable from the cards."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .embed import Embedder
from .schema import Card
from .store import Store

NEUTRAL_IMPORTANCE = 50
# Common words must not count as keyword matches (one shared "my" used to give a card a full keyword score).
STOPWORDS = frozenset("a an and are as at be but by for from had has have he her his i if in into is it its me my of on "
                      "or our she so that the their them then there they this to was we were what when which who will "
                      "with you your do does did am been being just not no yes can could would should about how why".split())
EMBED_BATCH = 64


@dataclass(frozen=True)
class Hit:
    card_id: str
    title: str
    snippet: str
    score: float


def _body(card: Card) -> str:
    parts = [k.text for k in card.key_points]
    if card.action:
        parts.append(card.action.text)
    if card.reply_to:  # "yes" alone means nothing: keep the question it answered (cards without one are unchanged)
        parts.append(f"(in reply to: {card.reply_to})")
    return "\n".join(parts)


def _importance(card: Card) -> float:
    return card.relevance.score if card.relevance else NEUTRAL_IMPORTANCE


def _sig(card: Card) -> str:
    """Changes whenever anything the index stores about a card changes."""
    raw = f"{card.source}\n{card.title}\n{_body(card)}\n{_importance(card)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _snippet(card: Card) -> str:
    if card.key_points:
        if card.reply_to:
            return f"(replying to: {card.reply_to[:100]}) {card.key_points[0].text}"
        return card.key_points[0].text
    return card.action.text if card.action else ""


class Index:
    def __init__(self, db_path: Path, embedder: Embedder):
        self.db_path = Path(db_path)
        self.embedder = embedder

    def rebuild(self, store: Store) -> int:
        """Rebuild from scratch into a temp file, then swap it in, so searches never see a half-built index."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.db_path.with_name(self.db_path.name + ".tmp")
        tmp.unlink(missing_ok=True)

        cards = [c for c in store.iter_cards() if c.tier != "cold"]
        texts = [f"{c.title}\n{_body(c)}" for c in cards]
        vectors: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH):
            vectors.extend(self.embedder.embed(texts[i : i + EMBED_BATCH]))

        try:
            with closing(sqlite3.connect(tmp)) as con:
                con.executescript(
                    "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                    "CREATE TABLE cards(id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL, "
                    "snippet TEXT NOT NULL, importance REAL NOT NULL, vec BLOB NOT NULL, sig TEXT NOT NULL DEFAULT '');"
                    "CREATE VIRTUAL TABLE fts USING fts5(id UNINDEXED, title, body);"
                )
                for card, vec in zip(cards, vectors):
                    con.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?)",
                                (card.id, card.source, card.title, _snippet(card), _importance(card),
                                 np.asarray(vec, dtype=np.float32).tobytes(), _sig(card)))
                    con.execute("INSERT INTO fts(id, title, body) VALUES (?,?,?)", (card.id, card.title, _body(card)))
                con.execute("INSERT INTO meta VALUES ('embedder', ?)", (self._embedder_name(),))
                con.commit()
            os.replace(tmp, self.db_path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return len(cards)

    def _embedder_name(self) -> str:
        return getattr(self.embedder, "name", type(self.embedder).__name__)

    def _has_sig(self) -> bool:
        """True when the index can be updated in place: it has per-card signatures and was built by this embedder."""
        try:
            with closing(sqlite3.connect(self.db_path)) as con:
                if not any(row[1] == "sig" for row in con.execute("PRAGMA table_info(cards)")):
                    return False
                row = con.execute("SELECT value FROM meta WHERE key = 'embedder'").fetchone()
                return row is not None and row[0] == self._embedder_name()
        except sqlite3.DatabaseError:
            return False  # an old index, or one built by another model: rebuild instead of mixing vectors

    def update(self, store: Store) -> tuple[int, int, int]:
        """Incremental: embed only new or changed cards, drop removed ones. Returns (added_or_changed, removed, total)."""
        if not self.db_path.is_file() or not self._has_sig():
            n = self.rebuild(store)
            return n, 0, n
        cards = {c.id: c for c in store.iter_cards() if c.tier != "cold"}
        with closing(sqlite3.connect(self.db_path)) as con:
            existing = dict(con.execute("SELECT id, sig FROM cards").fetchall())
        sigs = {cid: _sig(c) for cid, c in cards.items()}
        removed = [cid for cid in existing if cid not in cards]
        changed = [cid for cid in cards if existing.get(cid) != sigs[cid]]
        fresh = [cards[cid] for cid in changed]
        texts = [f"{c.title}\n{_body(c)}" for c in fresh]
        vectors: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH):
            vectors.extend(self.embedder.embed(texts[i : i + EMBED_BATCH]))
        with closing(sqlite3.connect(self.db_path)) as con:
            for cid in removed + changed:
                con.execute("DELETE FROM cards WHERE id = ?", (cid,))
                con.execute("DELETE FROM fts WHERE id = ?", (cid,))
            for card, vec in zip(fresh, vectors):
                con.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?)",
                            (card.id, card.source, card.title, _snippet(card), _importance(card),
                             np.asarray(vec, dtype=np.float32).tobytes(), sigs[card.id]))
                con.execute("INSERT INTO fts(id, title, body) VALUES (?,?,?)", (card.id, card.title, _body(card)))
            con.commit()
        return len(changed), len(removed), len(cards)

    def search(self, query: str, k: int = 5, per_source_cap: int = 3) -> list[Hit]:
        all_tokens = re.findall(r"\w+", query.lower())
        tokens = [t for t in all_tokens if t not in STOPWORDS]
        if not all_tokens or not self.db_path.is_file():
            return []
        with closing(sqlite3.connect(self.db_path)) as con:
            rows = con.execute("SELECT id, source, title, snippet, importance, vec FROM cards").fetchall()
            if not rows:
                return []
            expr = " OR ".join(f'"{t}"' for t in tokens)  # \w-only tokens, quoted: no FTS syntax can leak in
            raw_bm25 = ({cid: -score for cid, score in
                         con.execute("SELECT id, bm25(fts) FROM fts WHERE fts MATCH ?", (expr,))} if tokens else {})

        max_bm25 = max(raw_bm25.values(), default=0.0)
        query_vec = np.asarray(self.embedder.embed([query])[0], dtype=np.float32)
        matrix = np.vstack([np.frombuffer(r[5], dtype=np.float32) for r in rows])
        if matrix.shape[1] == query_vec.shape[0]:
            norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query_vec) or 1.0)
            cosine = np.divide(matrix @ query_vec, norms, out=np.zeros(len(rows), dtype=np.float32), where=norms > 0)
        else:
            cosine = np.zeros(len(rows), dtype=np.float32)

        scored: list[tuple[float, str, str, str, str]] = []
        for (cid, source, title, snippet, importance, _), cos in zip(rows, cosine):
            bm = raw_bm25.get(cid, 0.0) / max_bm25 if max_bm25 > 0 else 0.0
            score = (0.5 * bm + 0.5 * max(float(cos), 0.0)) * (0.5 + importance / 200)
            if score > 0:
                scored.append((score, cid, source, title, snippet))
        scored.sort(key=lambda s: (-s[0], s[1]))

        hits: list[Hit] = []
        per_source: Counter[str] = Counter()
        for score, cid, source, title, snippet in scored:
            if per_source[source] >= per_source_cap:
                continue
            per_source[source] += 1
            hits.append(Hit(card_id=cid, title=title, snippet=snippet, score=score))
            if len(hits) >= k:
                break
        return hits

    def related(self, text: str, k: int = 3, min_cosine: float = 0.55, exclude: frozenset[str] = frozenset()) -> list[Hit]:
        """Older cards that mean something similar to `text` (pure vector similarity, so only real matches pass).

        Calibrated on nomic-embed-text: related notes score about 0.6-0.75, unrelated ones about 0.3-0.4.
        """
        if not text.strip() or not self.db_path.is_file():
            return []
        with closing(sqlite3.connect(self.db_path)) as con:
            rows = con.execute("SELECT id, title, snippet, vec FROM cards").fetchall()
        rows = [r for r in rows if r[0] not in exclude]
        if not rows:
            return []
        query_vec = np.asarray(self.embedder.embed([text])[0], dtype=np.float32)
        matrix = np.vstack([np.frombuffer(r[3], dtype=np.float32) for r in rows])
        if matrix.shape[1] != query_vec.shape[0]:
            return []
        norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query_vec) or 1.0)
        cosine = np.divide(matrix @ query_vec, norms, out=np.zeros(len(rows), dtype=np.float32), where=norms > 0)
        order = np.argsort(-cosine)[:k]
        return [Hit(card_id=rows[i][0], title=rows[i][1], snippet=rows[i][2], score=float(cosine[i]))
                for i in order if cosine[i] >= min_cosine]

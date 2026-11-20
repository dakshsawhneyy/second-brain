"""Local search index v2: paragraph-level chunks, FTS5 keywords + vectors, ranked by relevance. Rebuildable from the cards.

Scale design (built for about 1M chunks):
- one search unit per paragraph (chunk), so every part of a long note is findable;
- vectors are kept L2-normalised as float16 in SQLite and in an in-process matrix cache; a query is one blocked
  matrix-vector product, and new notes are APPENDED to the cache (no reload per message);
- update() stats card files and parses only those whose (mtime, size) changed;
- the database is shared by two processes (the bot and the scheduled sync): WAL, short IMMEDIATE transactions, embedding
  done outside any lock, and rebuilds go into staging tables inside the same file and are swapped in by rename.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import uuid
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .chunks import chunk_card
from .embed import Embedder
from .schema import Card
from .store import Store

SCHEMA = "3"  # 3: the keyword table also carries each chunk's source and private flag (filter without joins)
NEUTRAL_IMPORTANCE = 50
EMBED_BATCH = 64
EMBED_TEXT_CHARS = 1800
FTS_CANDIDATES = 300
COSINE_CANDIDATES = 300
BLOCK_ROWS = 20_000
CACHE_FLOAT32_BYTES = 1_200_000_000  # up to about 390k chunks stay float32 (fast BLAS); beyond that float16, blocked
# Common words must not count as keyword matches (one shared "my" used to give a card a full keyword score).
STOPWORDS = frozenset("a an and are as at be but by for from had has have he her his i if in into is it its me my of on "
                      "or our she so that the their them then there they this to was we were what when which who will "
                      "with you your do does did am been being just not no yes can could would should about how why".split())


@dataclass(frozen=True)
class Hit:
    card_id: str
    title: str
    snippet: str  # the matching paragraph (chunk) of the card
    score: float
    date: str = ""
    source: str = ""


def _body(card: Card) -> str:
    parts = [k.text for k in card.key_points]
    if card.action:
        parts.append(card.action.text)
    if card.reply_to:  # "yes" alone means nothing: keep the question it answered
        parts.append(f"(in reply to: {card.reply_to})")
    return "\n".join(parts)


def _importance(card: Card) -> float:
    return card.relevance.score if card.relevance else NEUTRAL_IMPORTANCE


def _sig(card: Card) -> str:
    """Changes whenever anything the index stores about a card changes."""
    raw = f"{card.source}\n{card.title}\n{_body(card)}\n{_importance(card)}\n{card.tier}\n{card.channel}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _normalized(vec) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 0 else v


def _card_date(card: Card) -> str:
    return card.consumed_at.astimezone().date().isoformat()


class _Cache:
    """float16 matrix of normalised chunk vectors with spare capacity, so appending a row never copies the matrix."""

    def __init__(self, dim: int, count: int):
        self.dim = dim
        self.n = 0
        self.version = -1
        self.max_rowid = 0
        self.db_id = ""
        cap = count + 1024
        self.dtype = np.float32 if cap * dim * 4 <= CACHE_FLOAT32_BYTES else np.float16
        self.mat = np.zeros((cap, dim), dtype=self.dtype)
        self.rowids = np.zeros(cap, dtype=np.int64)
        self.local = np.zeros(cap, dtype=bool)
        self.src = np.zeros(cap, dtype=np.int16)

    def append(self, rowids, vecs: np.ndarray, local, src) -> None:
        add = len(rowids)
        if add == 0:
            return
        if self.n + add > self.mat.shape[0]:  # grow by doubling (amortised O(1) per row)
            cap = max(self.mat.shape[0] * 2, self.n + add + 1024)
            for name, dtype, shape in (("mat", self.dtype, (cap, self.dim)), ("rowids", np.int64, (cap,)),
                                       ("local", bool, (cap,)), ("src", np.int16, (cap,))):
                grown = np.zeros(shape, dtype=dtype)
                grown[:self.n] = getattr(self, name)[:self.n]
                setattr(self, name, grown)
        self.mat[self.n:self.n + add] = vecs
        self.rowids[self.n:self.n + add] = rowids
        self.local[self.n:self.n + add] = local
        self.src[self.n:self.n + add] = src
        self.n += add
        self.max_rowid = int(self.rowids[self.n - 1])

    def snapshot(self):
        return self.mat, self.rowids, self.local, self.n, self.src

    @staticmethod
    def cosine(snapshot, query: np.ndarray) -> np.ndarray:
        mat, _, _, n, _ = snapshot
        if mat.dtype == np.float32:
            return mat[:n] @ query  # one BLAS matrix-vector product
        out = np.empty(n, dtype=np.float32)
        for start in range(0, n, BLOCK_ROWS):
            stop = min(start + BLOCK_ROWS, n)
            out[start:stop] = mat[start:stop].astype(np.float32) @ query
        return out


class _ReadTx:
    """One consistent snapshot for everything a query reads (cache refresh, keyword search, chunk fetch)."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN")
        return self.con

    def __exit__(self, *exc):
        if self.con.in_transaction:
            self.con.execute("ROLLBACK")
        return False


class Index:
    def __init__(self, db_path: Path, embedder: Embedder):
        self.db_path = Path(db_path)
        self.embedder = embedder
        self.cache_reloads = 0
        self._cache: _Cache | None = None
        self._lock = threading.Lock()
        self._source_ids: dict[str, int] = {}

    # --- plumbing ------------------------------------------------------------------------------------------------
    def _embedder_name(self) -> str:
        return getattr(self.embedder, "name", type(self.embedder).__name__)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)  # autocommit: transactions are explicit
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _schema_ok(self, con: sqlite3.Connection) -> bool:
        try:
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
            con.execute("SELECT 1 FROM chunks LIMIT 1")
        except sqlite3.Error:
            return False
        return meta.get("schema") == SCHEMA and meta.get("embedder") == self._embedder_name()

    def _ready(self) -> bool:
        if not self.db_path.is_file():
            return False
        try:
            with closing(self._connect()) as con:
                return self._schema_ok(con)
        except sqlite3.Error:
            return False

    def _embed(self, texts: list[str]) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        for i in range(0, len(texts), EMBED_BATCH):
            out.extend(_normalized(v).astype(np.float16) for v in self.embedder.embed(texts[i:i + EMBED_BATCH]))
        return out

    @staticmethod
    def _chunks_of(card: Card):
        return [] if card.tier == "cold" else chunk_card(card)

    @staticmethod
    def _embed_text(card: Card, chunk) -> str:
        context = f"{chunk.context}\n" if chunk.context else ""
        return f"{card.title}\n{context}{chunk.text}"[:EMBED_TEXT_CHARS]

    @staticmethod
    def _create_tables(con: sqlite3.Connection, suffix: str = "") -> None:
        con.execute(f"CREATE TABLE cards{suffix}(id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL, "
                    "date TEXT NOT NULL, importance REAL NOT NULL, local_only INTEGER NOT NULL, sig TEXT NOT NULL, "
                    "tier TEXT NOT NULL, path TEXT, mtime_ns INTEGER, size INTEGER)")
        con.execute(f"CREATE TABLE chunks{suffix}(id INTEGER PRIMARY KEY AUTOINCREMENT, card_id TEXT NOT NULL, "
                    "ord INTEGER NOT NULL, text TEXT NOT NULL, vec BLOB NOT NULL)")
        con.execute(f"CREATE VIRTUAL TABLE fts{suffix} USING fts5(text, source UNINDEXED, local UNINDEXED)")

    @staticmethod
    def _card_row(card: Card) -> tuple:
        return (card.id, card.source, card.title, _card_date(card), _importance(card),
                1 if card.channel == "local-only" else 0, _sig(card), card.tier)

    @staticmethod
    def _insert_chunks(con: sqlite3.Connection, suffix: str, card: Card, chunks, vecs) -> None:
        for chunk, vec in zip(chunks, vecs):
            cur = con.execute(f"INSERT INTO chunks{suffix}(card_id, ord, text, vec) VALUES (?,?,?,?)",
                              (card.id, chunk.ord, chunk.text, vec.tobytes()))
            # keywords: the question an answer belongs to, and the card title (on the first chunk, so a book or note
            # can be found by its name)
            keywords = " ".join(part for part in (card.title if chunk.ord == 0 else "", chunk.context, chunk.text) if part)
            con.execute(f"INSERT INTO fts{suffix}(rowid, text, source, local) VALUES (?,?,?,?)",
                        (cur.lastrowid, keywords, card.source, 1 if card.channel == "local-only" else 0))

    @staticmethod
    def _delete_chunks(con: sqlite3.Connection, card_id: str) -> bool:
        ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE card_id = ?", (card_id,))]
        if not ids:
            return False
        con.executemany("DELETE FROM fts WHERE rowid = ?", [(i,) for i in ids])
        con.execute("DELETE FROM chunks WHERE card_id = ?", (card_id,))
        return True

    @staticmethod
    def _remember_dim(con: sqlite3.Connection, vecs) -> None:
        """An index built while empty has no vector size yet: learn it from the first vectors that arrive."""
        if vecs:
            con.execute("UPDATE meta SET value = ? WHERE key = 'dim' AND value = '0'", (str(len(vecs[0])),))

    @staticmethod
    def _bump_version(con: sqlite3.Connection) -> None:
        con.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'version'")

    # --- building ------------------------------------------------------------------------------------------------
    def rebuild(self, store: Store) -> int:
        """Full rebuild into staging tables inside the same file, swapped in by rename in ONE transaction.

        The live tables are never touched until the swap, so a failure (or a crash) leaves the previous index intact,
        and the database file itself is never replaced (the other process may have it open).
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        parsed: list[tuple[Card, str, int, int]] = []
        taken: set[str] = set()
        for path in store.iter_card_files():
            try:
                st = path.stat()
                card = store.read_card_file(path)
            except (OSError, ValueError):
                continue
            if card.id in taken:  # the same id in two month folders: index it once
                continue
            taken.add(card.id)
            parsed.append((card, path.relative_to(store.root).as_posix(), st.st_mtime_ns, st.st_size))
        with closing(self._connect()) as con:
            con.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for name in ("cards_new", "chunks_new", "fts_new"):
                con.execute(f"DROP TABLE IF EXISTS {name}")
            self._create_tables(con, "_new")
            dim = 0
            for start in range(0, len(parsed), 32):
                batch = []
                for card, rel, mtime, size in parsed[start:start + 32]:  # embedding is slow: do it OUTSIDE the write lock
                    chunks = self._chunks_of(card)
                    batch.append((card, rel, mtime, size, chunks,
                                  self._embed([self._embed_text(card, c) for c in chunks])))  # may raise: nothing is swapped
                con.execute("BEGIN IMMEDIATE")
                try:
                    for card, rel, mtime, size, chunks, vecs in batch:
                        if vecs:
                            dim = len(vecs[0])
                        con.execute("INSERT OR REPLACE INTO cards_new VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                    self._card_row(card) + (rel, mtime, size))
                        self._insert_chunks(con, "_new", card, chunks, vecs)
                    con.execute("COMMIT")
                except BaseException:
                    con.execute("ROLLBACK")
                    raise
            con.execute("BEGIN IMMEDIATE")
            try:
                version = int((con.execute("SELECT value FROM meta WHERE key = 'version'").fetchone() or ("0",))[0]) + 1
                for name in ("fts", "chunks", "cards"):
                    con.execute(f"DROP TABLE IF EXISTS {name}")
                for name in ("cards", "chunks", "fts"):
                    con.execute(f"ALTER TABLE {name}_new RENAME TO {name}")
                con.execute("CREATE INDEX idx_chunks_card ON chunks(card_id)")
                for key, value in (("schema", SCHEMA), ("embedder", self._embedder_name()), ("dim", str(dim)),
                                   ("version", str(version)), ("db_id", uuid.uuid4().hex)):  # new identity per rebuild
                    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        return sum(1 for card, *_ in parsed if card.tier != "cold")

    def update(self, store: Store) -> tuple[int, int, int]:
        """Incremental: parse only changed card files, embed only new or changed cards, drop removed ones.

        Returns (cards added or changed, cards removed, cards indexed in total).
        """
        if not self._ready():
            n = self.rebuild(store)
            return n, 0, n
        with closing(self._connect()) as con:
            rows = con.execute("SELECT id, sig, path, mtime_ns, size FROM cards").fetchall()
        by_path = {r[2]: r for r in rows if r[2] is not None}
        sig_by_id = {r[0]: r[1] for r in rows}
        seen: set[str] = set()
        changed: list[tuple[Card, str, int, int]] = []
        touched: list[tuple[str, str, int, int]] = []
        for path in store.iter_card_files():
            rel = path.relative_to(store.root).as_posix()
            try:
                st = path.stat()
            except OSError:
                continue
            known = by_path.get(rel)
            if known is not None and known[3] == st.st_mtime_ns and known[4] == st.st_size:
                seen.add(known[0])
                continue
            try:
                card = store.read_card_file(path)
            except (OSError, ValueError):
                continue  # a corrupt file: skip it, it is retried next time
            if card.id in seen:  # the same id in two month folders: first file wins
                continue
            seen.add(card.id)
            if sig_by_id.get(card.id) == _sig(card):
                touched.append((card.id, rel, st.st_mtime_ns, st.st_size))  # same content, new timestamp or new path
            else:
                changed.append((card, rel, st.st_mtime_ns, st.st_size))
        removed = [cid for cid in sig_by_id if cid not in seen]

        prepared = []
        for card, rel, mtime, size in changed:  # embedding happens OUTSIDE any lock
            chunks = self._chunks_of(card)
            prepared.append((card, rel, mtime, size, chunks, self._embed([self._embed_text(card, c) for c in chunks])))
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                deleted = False
                for cid in removed:
                    deleted |= self._delete_chunks(con, cid)
                    con.execute("DELETE FROM cards WHERE id = ?", (cid,))
                for card, rel, mtime, size, chunks, vecs in prepared:
                    deleted |= self._delete_chunks(con, card.id)
                    con.execute("INSERT OR REPLACE INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                self._card_row(card) + (rel, mtime, size))
                    self._insert_chunks(con, "", card, chunks, vecs)
                    self._remember_dim(con, vecs)
                for cid, rel, mtime, size in touched:
                    con.execute("UPDATE cards SET path = ?, mtime_ns = ?, size = ? WHERE id = ?", (rel, mtime, size, cid))
                if deleted:
                    self._bump_version(con)
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
            total = con.execute("SELECT count(*) FROM cards WHERE tier != 'cold'").fetchone()[0]
        cold = [card for card, *_ in changed if card.tier == "cold"]  # a card going cold leaves the index: "removed"
        left = sum(1 for card in cold if card.id in sig_by_id)
        return len(changed) - len(cold), len(removed) + left, total

    def add_card(self, card: Card) -> None:
        """Index one just-saved card right away (the bot calls this after saving). No-op until the index is built."""
        if not self._ready():
            return
        with closing(self._connect()) as con:
            row = con.execute("SELECT sig FROM cards WHERE id = ?", (card.id,)).fetchone()
        if row is not None and row[0] == _sig(card):
            return
        chunks = self._chunks_of(card)
        vecs = self._embed([self._embed_text(card, c) for c in chunks])  # outside the lock
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                deleted = self._delete_chunks(con, card.id)
                con.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,NULL,NULL,NULL) ON CONFLICT(id) DO UPDATE SET "
                            "source=excluded.source, title=excluded.title, date=excluded.date, "
                            "importance=excluded.importance, local_only=excluded.local_only, sig=excluded.sig, "
                            "tier=excluded.tier", self._card_row(card))
                self._insert_chunks(con, "", card, chunks, vecs)
                self._remember_dim(con, vecs)
                if deleted:
                    self._bump_version(con)
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise

    def chunk_count(self) -> int:
        if not self._ready():
            return 0
        with closing(self._connect()) as con:
            return con.execute("SELECT count(*) FROM chunks").fetchone()[0]

    # --- the cache ---------------------------------------------------------------------------------------------------
    def _refresh_cache(self, con: sqlite3.Connection) -> _Cache:
        """Bring the matrix up to date with the database (inside the caller's read transaction)."""
        meta = dict(con.execute("SELECT key, value FROM meta WHERE key IN ('version', 'dim', 'db_id')").fetchall())
        version, dim, db_id = int(meta.get("version", 0)), int(meta.get("dim", 0) or 0), meta.get("db_id", "")
        with self._lock:
            cache = self._cache
            # A deleted and rebuilt index restarts row ids and may restart `version`: the db_id tells them apart.
            if cache is None or cache.version != version or cache.dim != dim or cache.db_id != db_id:
                count = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
                cache = _Cache(dim, count)
                self.cache_reloads += 1
                after = 0
            else:
                after = cache.max_rowid
            cursor = con.execute("SELECT chunks.id, chunks.vec, cards.local_only, cards.source FROM chunks "
                                 "JOIN cards ON cards.id = chunks.card_id WHERE chunks.id > ? ORDER BY chunks.id", (after,))
            while True:
                batch = cursor.fetchmany(5000)
                if not batch:
                    break
                good = [r for r in batch if len(r[1]) == dim * 2]
                if good:
                    vecs = np.frombuffer(b"".join(r[1] for r in good), dtype=np.float16).reshape(-1, dim)
                    cache.append([r[0] for r in good], vecs, [bool(r[2]) for r in good],
                                 [self._source_ids.setdefault(r[3], len(self._source_ids)) for r in good])
            cache.version = version
            cache.db_id = db_id
            self._cache = cache
            return cache

    # --- searching -----------------------------------------------------------------------------------------------------
    def _query_vector(self, text: str, dim: int) -> np.ndarray | None:
        vec = _normalized(self.embedder.embed([text])[0])
        return vec if vec.shape[0] == dim else None

    def search(self, query: str, k: int = 5, per_source_cap: int = 3, per_card_cap: int = 2,
               include_local_only: bool = True, sources: frozenset[str] | None = None) -> list[Hit]:
        all_tokens = re.findall(r"\w+", query.lower())
        tokens = [t for t in all_tokens if t not in STOPWORDS]
        if not all_tokens or not self.db_path.is_file():
            return []
        try:
            con = self._connect()
        except sqlite3.Error:
            return []
        with closing(con), _ReadTx(con):
            if not self._schema_ok(con):
                return []
            cache = self._refresh_cache(con)
            snap = cache.snapshot()
            if snap[3] == 0:
                return []
            if sources is not None and not sources:
                return []
            filters, fts_filters, params = "", "", []
            if not include_local_only:
                filters += " AND cards.local_only = 0"
                fts_filters += " AND local = 0"
            if sources is not None:
                marks = ",".join("?" * len(sources))
                filters += f" AND cards.source IN ({marks})"
                fts_filters += f" AND source IN ({marks})"
                params += sorted(sources)
            bm25: dict[int, float] = {}
            if tokens:
                expr = " OR ".join(f'"{t}"' for t in tokens)  # \w-only tokens, quoted: no FTS syntax can leak in
                for rid, score in con.execute("SELECT rowid, bm25(fts) FROM fts WHERE fts MATCH ?" + fts_filters +
                                              " ORDER BY bm25(fts) LIMIT ?", (expr, *params, FTS_CANDIDATES)):
                    bm25[rid] = -score
            qvec = self._query_vector(query, cache.dim)
            _, rowids, local, n, src = snap
            cosine = _Cache.cosine(snap, qvec) if qvec is not None else np.zeros(n, dtype=np.float32)
            excluded = np.zeros(n, dtype=bool)
            if not include_local_only:
                excluded |= local[:n]
            if sources is not None:
                excluded |= ~np.isin(src[:n], [self._source_ids[s] for s in sources if s in self._source_ids])
            if excluded.any():
                cosine = np.where(excluded, -1.0, cosine)
            top = np.argpartition(-cosine, min(COSINE_CANDIDATES, n - 1))[:COSINE_CANDIDATES] if n else []
            candidate_ids = {int(rowids[i]) for i in top if cosine[i] > 0} | set(bm25)
            if not candidate_ids:
                return []
            marks = ",".join("?" * len(candidate_ids))
            meta = {r[0]: r for r in con.execute(
                f"SELECT chunks.id, chunks.card_id, chunks.text, cards.source, cards.title, cards.date, "
                f"cards.importance FROM chunks JOIN cards ON cards.id = chunks.card_id WHERE chunks.id IN ({marks})"
                + filters, (*candidate_ids, *params))}
        max_bm = max(bm25.values(), default=0.0)
        scored = []
        for rid in candidate_ids:
            row = meta.get(rid)
            if row is None:
                continue
            idx = int(np.searchsorted(rowids[:n], rid))
            cos = float(cosine[idx]) if idx < n and rowids[idx] == rid else 0.0
            base = 0.5 * (bm25.get(rid, 0.0) / max_bm if max_bm > 0 else 0.0) + 0.5 * max(cos, 0.0)
            score = base * (0.5 + row[6] / 200)
            if score > 0:
                scored.append((score, rid, row))
        scored.sort(key=lambda s: (-s[0], s[1]))
        hits: list[Hit] = []
        per_source: Counter[str] = Counter()
        per_card: Counter[str] = Counter()
        for score, _, (_, card_id, text, source, title, date, _imp) in scored:
            if per_source[source] >= per_source_cap or per_card[card_id] >= per_card_cap:
                continue
            per_source[source] += 1
            per_card[card_id] += 1
            hits.append(Hit(card_id=card_id, title=title, snippet=text, score=score, date=date, source=source))
            if len(hits) >= k:
                break
        return hits

    def related(self, text: str, k: int = 3, min_cosine: float = 0.55, exclude: frozenset[str] = frozenset(),
                include_local_only: bool = True, before: str | None = None,
                sources: frozenset[str] | None = None) -> list[Hit]:
        """Older notes that mean something similar to `text` (pure vector similarity, so only real matches pass).

        At most one hit per card; `exclude` holds CARD ids; `before` (an ISO date) keeps only notes from earlier days;
        `sources` keeps only those sources. Calibrated on nomic-embed-text: related notes score about
        0.6-0.75, unrelated ones about 0.3-0.4.
        """
        if not text.strip() or not self.db_path.is_file():
            return []
        try:
            con = self._connect()
        except sqlite3.Error:
            return []
        with closing(con), _ReadTx(con):
            if not self._schema_ok(con):
                return []
            cache = self._refresh_cache(con)
            snap = cache.snapshot()
            _, rowids, local, n, _ = snap
            qvec = self._query_vector(text, cache.dim) if n else None
            if qvec is None:
                return []
            cosine = _Cache.cosine(snap, qvec)
            if not include_local_only:
                cosine = np.where(local[:n], -1.0, cosine)
            limit = min(n, 400 if (before or sources) else max(50, k * 10 + len(exclude) * 4))
            order = np.argsort(-cosine)[:limit]
            ids = [int(rowids[i]) for i in order if cosine[i] >= min_cosine]
            if not ids:
                return []
            marks = ",".join("?" * len(ids))
            meta = {r[0]: r for r in con.execute(
                f"SELECT chunks.id, chunks.card_id, chunks.text, cards.source, cards.title, cards.date "
                f"FROM chunks JOIN cards ON cards.id = chunks.card_id WHERE chunks.id IN ({marks})", ids)}
        hits: list[Hit] = []
        seen: set[str] = set(exclude)
        by_rowid = {int(rowids[i]): float(cosine[i]) for i in order}
        for rid in ids:
            row = meta.get(rid)
            if row is None or row[1] in seen:
                continue
            if (before is not None and row[5] >= before) or (sources is not None and row[3] not in sources):
                continue
            seen.add(row[1])
            hits.append(Hit(card_id=row[1], title=row[4], snippet=row[2], score=by_rowid[rid], date=row[5], source=row[3]))
            if len(hits) >= k:
                break
        return hits

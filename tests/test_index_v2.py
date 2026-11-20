"""Schema 2 of the index: paragraph-level chunks, matrix cache, incremental scan, two-process safety."""

import sqlite3
from pathlib import Path

import pytest

from secondbrain.embed import HashEmbedder
from secondbrain.index import Index
from secondbrain.store import Store

from test_index import WHEN, card, env  # noqa: F401  (env is a fixture)


def long_journal(cid="tg_long"):
    paragraphs = ["I woke up early and went for a long run along the river before breakfast.",
                  "At work I fixed a flaky deployment pipeline and wrote the runbook for it.",
                  "Money worries are growing, so I plan to email five recruiters about remote devops roles.",
                  "Late at night I read about habit loops and decided to build a habit tracker app."]
    return card(cid, paragraphs[0][:40], paragraphs, source="telegram"), paragraphs


def test_search_finds_a_later_paragraph_of_a_long_journal(env):
    store, index = env
    c, paragraphs = long_journal()
    store.write_card(c)
    store.write_card(card("yt_other", "Terraform modules", ["split state per environment"]))
    index.rebuild(store)
    hit = index.search("recruiters remote devops roles")[0]
    assert hit.card_id == "tg_long" and hit.snippet == paragraphs[2]  # the matching PARAGRAPH, not paragraph 1


def test_hit_carries_date_and_source(env):
    store, index = env
    c, _ = long_journal()
    store.write_card(c)
    index.rebuild(store)
    hit = index.search("habit tracker")[0]
    assert hit.source == "telegram" and hit.date == WHEN.astimezone().date().isoformat()


def test_per_card_cap_limits_chunks_from_one_card(env):
    store, index = env
    c, _ = long_journal()
    store.write_card(c)
    index.rebuild(store)
    default = index.search("work money habit river", k=10, per_source_cap=10)
    assert len([h for h in default if h.card_id == "tg_long"]) <= 2
    many = index.search("work money habit river", k=10, per_source_cap=10, per_card_cap=3)
    assert 2 < len([h for h in many if h.card_id == "tg_long"]) <= 3


def test_search_can_exclude_local_only_cards(env):
    store, index = env
    secret = card("tg_secret", "my private worry about money", ["my private worry about money"], source="telegram")
    store.write_card(secret.model_copy(update={"channel": "local-only"}))
    store.write_card(card("tg_open", "my public plan about money", ["my public plan about money"], source="telegram"))
    index.rebuild(store)
    assert {h.card_id for h in index.search("money worry plan")} == {"tg_secret", "tg_open"}
    assert {h.card_id for h in index.search("money worry plan", include_local_only=False)} == {"tg_open"}
    assert all(h.card_id != "tg_secret"
               for h in index.related("my private worry about money", min_cosine=0.1, include_local_only=False))


def test_related_returns_one_hit_per_card_and_excludes_by_card_id(env):
    store, index = env
    store.write_card(card("tg_a", "habit tracker",
                          ["habit tracker idea one", "habit tracker idea two", "habit tracker idea three"], source="telegram"))
    store.write_card(card("tg_b", "habit tracker notes", ["habit tracker idea four"], source="telegram"))
    index.rebuild(store)
    hits = index.related("habit tracker idea", k=5, min_cosine=0.1)
    assert sorted(h.card_id for h in hits) == ["tg_a", "tg_b"]  # one hit per card
    only_b = index.related("habit tracker idea", k=5, min_cosine=0.1, exclude=frozenset({"tg_a"}))
    assert [h.card_id for h in only_b] == ["tg_b"]


class CountingStore(Store):
    reads = 0

    def read_card_file(self, path):
        CountingStore.reads += 1
        return super().read_card_file(path)


def test_update_parses_only_changed_files(tmp_path: Path):
    store = CountingStore(tmp_path / "brain")
    index = Index(tmp_path / "brain" / "index" / "brain.db", HashEmbedder())
    for i in range(5):
        store.write_card(card(f"tg_{i}", f"note {i} about pricing", [f"note {i} about pricing"], source="telegram"))
    index.update(store)  # first run builds everything
    CountingStore.reads = 0
    assert index.update(store) == (0, 0, 5) and CountingStore.reads == 0  # nothing changed: no file is parsed
    store.write_card(card("tg_2", "note 2 now about hiring and interviews",
                          ["note 2 now about hiring and interviews"], source="telegram"))
    assert index.update(store) == (1, 0, 5) and CountingStore.reads == 1
    assert index.search("hiring interviews")[0].card_id == "tg_2"
    assert all(h.card_id != "tg_2" for h in index.search("pricing"))  # the old chunk is gone


def test_update_removes_deleted_cards_and_the_cache_forgets_them(env, tmp_path: Path):
    store, index = env
    store.write_card(card("tg_a", "kubernetes basics", ["kubernetes basics"], source="telegram"))
    store.write_card(card("tg_b", "terraform basics", ["terraform basics"], source="telegram"))
    index.update(store)
    assert index.search("kubernetes")[0].card_id == "tg_a"
    (tmp_path / "brain" / "cards" / "2026" / "11" / "tg_a.json").unlink()
    assert index.update(store) == (0, 1, 1)
    assert all(h.card_id != "tg_a" for h in index.search("kubernetes basics"))


def test_add_card_makes_a_note_searchable_without_update(env):
    store, index = env
    store.write_card(card("tg_a", "old note", ["old note about kubernetes"], source="telegram"))
    index.rebuild(store)
    fresh = card("tg_new", "fresh", ["a brand new thought about negotiating salary"], source="telegram")
    index.add_card(fresh)
    assert index.search("negotiating salary")[0].card_id == "tg_new"
    index.add_card(fresh)  # idempotent: no duplicate chunks
    assert index.chunk_count() == 2


def test_add_card_before_the_first_build_does_nothing_and_does_not_crash(env):
    _, index = env
    index.add_card(card("tg_x", "x", ["some text that is long enough"], source="telegram"))
    assert index.search("text") == []


def test_second_index_instance_sees_add_card_without_reloading_the_whole_matrix(env):
    store, index = env
    store.write_card(card("tg_a", "old note", ["old note about kubernetes"], source="telegram"))
    index.rebuild(store)
    other = Index(index.db_path, HashEmbedder())
    other.search("kubernetes")  # warms the other instance's cache
    assert other.cache_reloads == 1
    index.add_card(card("tg_new", "fresh", ["a brand new thought about negotiating salary"], source="telegram"))
    assert other.search("negotiating salary")[0].card_id == "tg_new"
    assert other.cache_reloads == 1  # rows were APPENDED, not reloaded


def test_old_schema_index_is_rebuilt_by_update(env):
    store, index = env
    store.write_card(card("tg_a", "kubernetes basics", ["kubernetes basics"], source="telegram"))
    index.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(index.db_path)  # a schema-1 file: cards table with a vec column
    con.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                      "CREATE TABLE cards(id TEXT PRIMARY KEY, source TEXT, title TEXT, snippet TEXT, importance REAL,"
                      " vec BLOB, sig TEXT);")
    con.commit()
    con.close()
    assert index.search("kubernetes") == []  # unusable old file: no crash, no results
    index.update(store)
    assert index.search("kubernetes")[0].card_id == "tg_a"


def test_a_failed_rebuild_keeps_the_previous_index_searchable(env):
    store, index = env
    store.write_card(card("tg_a", "kubernetes basics", ["kubernetes basics"], source="telegram"))
    index.rebuild(store)

    class Boom:
        def embed(self, texts):
            raise RuntimeError("embedding model down")

    broken = Index(index.db_path, Boom())
    store.write_card(card("tg_b", "terraform basics", ["terraform basics"], source="telegram"))
    with pytest.raises(RuntimeError):
        broken.rebuild(store)
    assert index.search("kubernetes")[0].card_id == "tg_a"  # the old tables were never touched
    assert index.rebuild(store) == 2  # and a later rebuild cleans up and succeeds


def test_two_processes_add_card_update_and_rebuild_do_not_corrupt(tmp_path: Path):
    import multiprocessing as mp

    import _index_workers as w

    root, db = tmp_path / "brain", tmp_path / "brain" / "index" / "brain.db"
    seed = Store(root)
    for i in range(1000, 1004):
        seed.write_card(w.make(i))
    Index(db, HashEmbedder()).rebuild(seed)
    ctx = mp.get_context("spawn")
    bot = ctx.Process(target=w.bot_like, args=(str(root), str(db), 40))
    sync = ctx.Process(target=w.sync_like, args=(str(root), str(db), 6))
    bot.start()
    sync.start()
    bot.join(180)
    sync.join(180)
    assert bot.exitcode == 0 and sync.exitcode == 0  # neither process hit "database is locked" or crashed
    final = Index(db, HashEmbedder())
    final.update(Store(root))  # picks up anything a rebuild swapped away
    with sqlite3.connect(db) as con:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    found = {h.card_id for h in final.search("concurrent note kubernetes terraform habits",
                                             k=100, per_source_cap=100, per_card_cap=1)}
    assert {f"tg_{i}" for i in range(40)} <= found and {f"tg_{i}" for i in range(1000, 1004)} <= found


def test_a_card_id_present_in_two_files_is_indexed_once(env):
    from datetime import timedelta
    store, index = env
    first = card("tg_dup", "kubernetes basics", ["kubernetes basics"], source="telegram")
    store.write_card(first)
    store.write_card(first.model_copy(update={"consumed_at": first.consumed_at + timedelta(days=40)}))  # other month folder
    assert len(list(store.iter_card_files())) == 2
    index.rebuild(store)
    assert index.chunk_count() == 1


def test_search_can_be_limited_to_chosen_sources_so_other_sources_cannot_crowd_them_out(env):
    store, index = env
    for i in range(12):  # session summaries that match the query very well
        store.write_card(card(f"cc_{i}", "deployment pipeline fix", ["fixed the deployment pipeline again"], source="claude-code"))
    store.write_card(card("tg_note", "my note", ["thinking about the deployment pipeline at work"], source="telegram"))
    index.rebuild(store)
    unfiltered = [h.card_id for h in index.search("fixed the deployment pipeline", k=5, per_source_cap=5)]
    assert "tg_note" not in unfiltered                                          # crowded out without the filter
    only = index.search("fixed the deployment pipeline", k=5, per_source_cap=5, sources=frozenset({"telegram"}))
    assert [h.card_id for h in only] == ["tg_note"]
    assert index.search("deployment", sources=frozenset({"no-such-source"})) == []


class ConstantEmbedder:
    """Every text gets the same vector, so only keyword search can decide the order."""
    name = "const"

    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_the_card_title_is_keyword_searchable(tmp_path: Path):
    store = Store(tmp_path / "brain")
    store.write_card(card("tg_1", "Some other note", ["monopolies are a good business to be in"], source="telegram"))
    store.write_card(card("tg_2", "Zero to One", ["monopolies are a good business to be in"], source="telegram"))
    index = Index(tmp_path / "i.db", ConstantEmbedder())
    index.rebuild(store)
    assert index.search("zero to one")[0].card_id == "tg_2"

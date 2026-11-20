from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from secondbrain.advisor import DOC_BUDGET, PACK_CHARS, build_context
from secondbrain.digest import _eligible
from secondbrain.embed import HashEmbedder
from secondbrain.index import Index
from secondbrain.mentor.persona import ASK_MODE
from secondbrain.schema import Card, KeyPoint, Topic
from secondbrain.store import Store

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 20, 14, 0, tzinfo=IST)


def card(cid, texts, source="telegram", channel=None, title=None, days_ago=40):
    return Card(id=cid, source=source, type="thought", title=title or texts[0][:50], consumed_at=NOW - timedelta(days=days_ago),
                topic=Topic(primary="uncertain"), channel=channel,
                key_points=[KeyPoint(text=t, topic="uncertain", confidence=1.0) for t in texts])


@pytest.fixture
def library(tmp_path: Path):
    store = Store(tmp_path / "brain")
    store.write_card(card("tg_mine", ["I think I should find customers who feel the pain of slow deployments"]))
    store.write_card(card("doc_5_p1", ["[12 Mar 2024]", "Rahul Sharma (founder): find customers who feel the pain of slow deployments first",
                                       "Daksh: ok"], source="document", title="WhatsApp chat with Rahul (founder) (part 1 of 1)"))
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)
    return store, index


def test_shared_material_has_its_own_labelled_section_and_never_mixes_into_his_evidence(library):
    store, index = library
    pack = build_context(store, "how do I find customers who feel the pain of slow deployments", "goals", NOW, index=index)
    assert "MATERIAL HE SHARED" in pack and "not by him" in pack.lower()
    material = pack.split("MATERIAL HE SHARED")[1]
    assert "Rahul Sharma (founder): find customers" in material and "WhatsApp chat with Rahul" in material
    mine = pack.split("EVIDENCE FROM HIS NOTES")[1].split("MATERIAL HE SHARED")[0]
    assert "I think I should find customers" in mine and "Rahul Sharma (founder)" not in mine    # his words stay his
    recent = pack.split("RECENT ENTRIES")[1].split("EVIDENCE FROM HIS NOTES")[0] if "RECENT ENTRIES" in pack else ""
    assert "Rahul Sharma" not in recent


def test_private_documents_never_reach_the_pack(library, tmp_path):
    store, index = library
    store.write_card(card("doc_6_p1", ["Amy (investor): secret terms about slow deployments customers"], source="document",
                          channel="local-only", title="Private chat"))
    index.update(store)
    pack = build_context(store, "slow deployments customers terms", "goals", NOW, index=index)
    assert "secret terms" not in pack


def test_the_material_section_has_its_own_budget_and_the_total_stays_bounded(tmp_path):
    store = Store(tmp_path / "brain")
    for i in range(30):
        store.write_card(card(f"doc_9_p{i}", [f"Rahul (founder): pricing advice number {i} " + "words about customers " * 30],
                              source="document", title=f"Chat part {i}"))
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)
    pack = build_context(store, "pricing advice customers", "g" * 5000, NOW, index=index, profile="p" * 9000)
    material = pack.split("MATERIAL HE SHARED")[1]
    assert 0 < len(material) <= DOC_BUDGET + 200 and len(pack) <= PACK_CHARS


def test_without_an_index_documents_are_found_by_keywords(library):
    store, _ = library
    pack = build_context(store, "customers who feel the pain of slow deployments", "goals", NOW, index=None)
    assert "Rahul Sharma (founder)" in pack.split("MATERIAL HE SHARED")[1]


def test_no_documents_means_no_material_section(tmp_path):
    store = Store(tmp_path / "brain")
    store.write_card(card("tg_a", ["a note about prices"]))
    assert "MATERIAL HE SHARED" not in build_context(store, "prices", "goals", NOW)


def test_ask_mode_tells_claude_shared_material_is_other_peoples_words():
    low = " ".join(ASK_MODE.lower().split())
    assert "material he shared" in low and "never present it as his" in low and "attribute" in low


def test_documents_never_feed_digests_suggestions_or_evals():
    from secondbrain.bot.app import RELATED_SOURCES
    doc = card("doc_1_p1", ["Rahul: pricing advice about customers and plans"], source="document")
    assert _eligible(doc) is False and "document" not in RELATED_SOURCES

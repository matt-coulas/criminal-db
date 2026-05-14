"""Tests for :mod:`criminal_db.db`."""

from __future__ import annotations

import json
import math
import random
import sqlite3

import pytest

from criminal_db.db import Database
from criminal_db.db.operations import sanitize_fts5
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json


# ── Helpers ────────────────────────────────────────────────────────────────


def _random_unit_vector(dim: int, *, seed: int) -> list[float]:
    rng = random.Random(seed)
    raw = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


@pytest.fixture
def db_with_fulltext(tmp_db, fulltext_html):
    db = Database(tmp_db)
    case = CanLIIParser(fulltext_html).parse()
    db.store_case(export_case_to_json(case))
    return db, case


def _vec_available() -> bool:
    import sqlite3

    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.enable_load_extension(True)
        except AttributeError:
            return False
        import sqlite_vec

        sqlite_vec.load(conn)
        return True
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


vector_only = pytest.mark.skipif(
    not _vec_available(),
    reason="sqlite-vec is not loadable in this Python's SQLite build",
)


# ── Round-trip ─────────────────────────────────────────────────────────────


class TestRoundTrip:
    def test_store_and_get(self, db_with_fulltext):
        db, parsed = db_with_fulltext
        retrieved = db.get_case("2024 SCC 1")
        assert retrieved is not None
        assert retrieved["canlii_ref"] == "2024 SCC 1"
        assert retrieved["court_year"] == 2024
        assert retrieved["judges"] == parsed.judges
        assert len(retrieved["paragraphs"]) == len(parsed.paragraphs)
        assert retrieved["paragraphs"][0]["paragraph_num"] == 1

    def test_store_is_idempotent_on_canlii_ref(self, db_with_fulltext):
        db, parsed = db_with_fulltext
        first = db.store_case(export_case_to_json(parsed))
        second = db.store_case(export_case_to_json(parsed))
        assert first == second
        assert db.case_count() == 1
        assert db.paragraph_count() == len(parsed.paragraphs)

    def test_rejects_unknown_citation(self, tmp_db):
        db = Database(tmp_db)
        with pytest.raises(ValueError):
            db.store_case({"meta": {"canlii_ref": "UNKNOWN"}, "paragraphs": []})

    def test_paragraph_cascade_delete(self, db_with_fulltext):
        db, _ = db_with_fulltext
        db.conn.execute("DELETE FROM cases")
        db.conn.commit()
        assert db.paragraph_count() == 0
        assert db.case_count() == 0


# ── FTS5 ───────────────────────────────────────────────────────────────────


class TestFTS:
    def test_search_finds_paragraph(self, db_with_fulltext):
        db, _ = db_with_fulltext
        results = db.search_fts("warrantless")
        assert results, "expected at least one hit for 'warrantless'"
        first = results[0]
        assert first.canlii_ref == "2024 SCC 1"
        assert "warrantless" in first.text.lower()
        assert first.source == "fts"

    def test_search_court_filter(self, db_with_fulltext):
        db, _ = db_with_fulltext
        # Filter that excludes our only case returns empty.
        assert db.search_fts("Charter", court="Bogus Court") == []

    def test_sanitize_handles_special_characters(self):
        # OR is the default join so ranked retrieval ranks partial matches.
        assert sanitize_fts5('section 24(2) "exclusion"') == '"section" OR "242" OR "exclusion"'
        assert sanitize_fts5("the OR ( unbalanced") == '"the" OR "unbalanced"'

    def test_sanitize_allows_and_join(self):
        assert (
            sanitize_fts5("warrantless thermal imaging", join="AND")
            == '"warrantless" AND "thermal" AND "imaging"'
        )

    def test_sanitize_drops_dangling_operators(self):
        assert sanitize_fts5("AND OR foo bar AND") == '"foo" OR "bar"'

    def test_search_does_not_crash_on_user_specials(self, db_with_fulltext):
        db, _ = db_with_fulltext
        # The buggy old implementation would raise sqlite3.OperationalError
        # on input like this.
        results = db.search_fts('section 8 charter "search"')
        assert isinstance(results, list)

    def test_fts_update_trigger_keeps_index_in_sync(self, db_with_fulltext):
        db, _ = db_with_fulltext
        db.conn.execute(
            "UPDATE paragraphs SET text = 'totally different content about fishing' "
            "WHERE paragraph_num = 1"
        )
        db.conn.commit()
        assert not db.search_fts("warrantless")  # only para 1 had 'warrantless'
        # depending on stemming "fishing" may stem to "fish"; both are valid hits
        hits = db.search_fts("fishing") or db.search_fts("fish")
        assert hits


# ── Vector search ─────────────────────────────────────────────────────────


@vector_only
class TestVector:
    def test_store_and_query_embeddings(self, tmp_db, fulltext_html):
        db = Database(tmp_db)
        case = CanLIIParser(fulltext_html).parse()
        db.store_case(export_case_to_json(case))

        from criminal_db import config

        missing = db.paragraphs_missing_embeddings()
        assert len(missing) == len(case.paragraphs)

        # Use deterministic fake embeddings so the test doesn't depend on
        # downloading the actual model.
        vectors = [
            (pid, _random_unit_vector(config.EMBEDDING_DIM, seed=pid))
            for pid, _ in missing
        ]
        written = db.store_embeddings(vectors)
        assert written == len(vectors)
        assert db.embedding_count() == len(vectors)
        assert db.paragraphs_missing_embeddings() == []

        query = vectors[0][1]
        results = db.search_vector(query, limit=3)
        assert results
        assert results[0].paragraph_id == vectors[0][0]
        assert results[0].source == "vector"

    def test_hybrid_combines_both_sides(self, tmp_db, fulltext_html):
        from criminal_db import config

        db = Database(tmp_db)
        case = CanLIIParser(fulltext_html).parse()
        db.store_case(export_case_to_json(case))
        for pid, _ in db.paragraphs_missing_embeddings():
            db.store_embeddings(
                [(pid, _random_unit_vector(config.EMBEDDING_DIM, seed=pid))]
            )

        # A made-up query vector and FTS query.
        query_vec = _random_unit_vector(config.EMBEDDING_DIM, seed=999)
        results = db.search_hybrid("warrantless", query_vec, limit=3)
        assert results
        assert results[0].source == "hybrid"
        # scores should be in [0, 1] after the convex combination.
        for r in results:
            assert 0.0 - 1e-9 <= r.score <= 1.0 + 1e-9


# ── Stats ─────────────────────────────────────────────────────────────────


class TestStats:
    def test_distributions(self, tmp_db, fulltext_html, headnote_html):
        db = Database(tmp_db)
        db.store_case(export_case_to_json(CanLIIParser(fulltext_html).parse()))
        db.store_case(export_case_to_json(CanLIIParser(headnote_html).parse()))

        assert db.case_count() == 2
        assert db.paragraph_count() > 0
        assert db.headnote_paragraph_count() >= 1

        by_court = db.court_distribution()
        assert any("Supreme Court" in name for name in by_court)
        by_year = db.year_distribution()
        assert by_year.get(2024) == 1
        assert by_year.get(2023) == 1

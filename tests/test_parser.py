"""Tests for :mod:`criminal_db.harvester.parser`."""

from __future__ import annotations

from criminal_db.harvester.parser import (
    CanLIIParser,
    CaseData,
    Paragraph,
    export_case_to_json,
)


# ── Fulltext fixture ───────────────────────────────────────────────────────


class TestFulltextParser:
    def test_canlii_ref(self, fulltext_html):
        case = CanLIIParser(fulltext_html).parse()
        assert case.canlii_ref == "2024 SCC 1"

    def test_metadata(self, fulltext_html):
        case = CanLIIParser(fulltext_html).parse()
        assert case.neutral_citation == "[2024] 1 SCR 42"
        assert case.reporter_citation == "[2024] 1 S.C.R. 42"
        assert case.court_year == 2024
        assert "Supreme Court of Canada" in case.court
        assert case.decided_date == "2024-01-15"

    def test_corpus_is_fulltext_when_paragraphs_numbered(self, fulltext_html):
        case = CanLIIParser(fulltext_html).parse()
        # regression for the property/_paragraphs bug
        assert case.corpus == "fulltext"
        assert case.is_headnote_only == 0

    def test_paragraph_numbers_preserved(self, fulltext_html):
        case = CanLIIParser(fulltext_html).parse()
        nums = [p.paragraph_num for p in case.paragraphs]
        assert nums == [1, 2, 3, 4, 5, 6, 7]

    def test_heading_uses_proximity_not_first_heading(self, fulltext_html):
        case = CanLIIParser(fulltext_html).parse()
        headings = [p.heading for p in case.paragraphs]
        # paragraphs 1 -> Issues, 2 -> Holding, 3..6 -> Reasons, 7 -> Conclusion.
        # The buggy implementation returned 'ISSUES' for every paragraph.
        assert headings.count("ISSUES") <= 1
        assert "HOLDING" in headings
        assert "REASONS" in headings
        assert "CONCLUSION" in headings

    def test_judges_scoped_and_deduplicated(self, fulltext_html):
        case = CanLIIParser(fulltext_html).parse()
        assert len(case.judges) == 3
        assert "Wagner C.J." in case.judges
        assert "Karakatsanis J." in case.judges
        # no duplicates, no literal "judge"/"judges" token.
        assert "judge" not in {j.lower() for j in case.judges}

    def test_ratio_classification(self, fulltext_html):
        case = CanLIIParser(fulltext_html).parse()
        ratio_paragraphs = [p for p in case.paragraphs if p.is_ratio]
        assert ratio_paragraphs  # at least one ratio paragraph detected


# ── Headnote fixture ───────────────────────────────────────────────────────


class TestHeadnoteParser:
    def test_canlii_ref(self, headnote_html):
        case = CanLIIParser(headnote_html).parse()
        assert case.canlii_ref == "2023 FCA 42"

    def test_corpus_is_headnote(self, headnote_html):
        case = CanLIIParser(headnote_html).parse()
        assert case.corpus == "headnote"
        assert case.is_headnote_only == 1

    def test_paragraph_numbers(self, headnote_html):
        case = CanLIIParser(headnote_html).parse()
        nums = [p.paragraph_num for p in case.paragraphs]
        assert nums == [5, 8, 15, 22]

    def test_is_headnote_flag(self, headnote_html):
        case = CanLIIParser(headnote_html).parse()
        assert all(p.is_headnote for p in case.paragraphs)


# ── Fallback / unknown citation ────────────────────────────────────────────


class TestFallbacks:
    def test_unknown_citation_does_not_crash(self):
        html = "<html><body><p>Just some prose without a citation.</p></body></html>"
        case = CanLIIParser(html).parse()
        assert case.canlii_ref == "UNKNOWN"
        assert case.corpus == "headnote"
        assert len(case.paragraphs) == 1

    def test_empty_html(self):
        case = CanLIIParser("").parse()
        assert case.canlii_ref == "UNKNOWN"
        assert case.paragraphs == []

    def test_class_none_does_not_crash(self):
        # Regression for the _extract_date bug: a tag with class=None caused
        # ``None + [...]`` -> TypeError in the previous implementation.
        html = '<html><body><span data-type="date">2024-01-15</span></body></html>'
        case = CanLIIParser(html).parse()
        assert case.decided_date == "2024-01-15"


# ── Export ────────────────────────────────────────────────────────────────


class TestExport:
    def test_round_trip(self, fulltext_html):
        case = CanLIIParser(fulltext_html).parse()
        payload = export_case_to_json(case)
        assert payload["meta"]["canlii_ref"] == "2024 SCC 1"
        assert payload["meta"]["court_year"] == 2024
        assert isinstance(payload["paragraphs"], list)
        assert payload["paragraphs"][0]["paragraph_num"] == 1
        assert payload["paragraphs"][0]["text"].startswith("The appellant")

    def test_export_of_empty_case(self):
        case = CaseData(canlii_ref="2025 SCC 99")
        case.paragraphs = [Paragraph(text="x")]
        payload = export_case_to_json(case)
        assert payload["meta"]["canlii_ref"] == "2025 SCC 99"
        assert payload["paragraphs"][0]["text"] == "x"

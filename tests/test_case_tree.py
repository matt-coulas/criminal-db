"""Tests for TUI case browser tree helpers."""

from __future__ import annotations

from criminal_db.tui.case_tree import (
    case_label,
    cases_for_court_year,
    courts_from_entries,
    short_title_from_fields,
    years_for_court,
)
from criminal_db.tui.case_tree import CaseBrowserEntry


def _entry(**kwargs) -> CaseBrowserEntry:
    defaults = dict(
        canlii_ref="2024 SCC 1",
        neutral_citation="2024 SCC 1",
        court="SCC",
        court_year=2024,
        short_title="R. v. Example",
        store="fulltext",
    )
    defaults.update(kwargs)
    return CaseBrowserEntry(**defaults)


def test_short_title_prefers_heading():
    title = short_title_from_fields(
        canlii_ref="2024 ONCA 2",
        neutral_citation="2024 ONCA 2",
        heading="R. v. Smith",
        lead_text="Long body text that should not be used first.",
    )
    assert title == "R. v. Smith"


def test_short_title_from_r_v_lead():
    title = short_title_from_fields(
        canlii_ref="2023 FCA 9",
        neutral_citation="2023 FCA 9",
        heading=None,
        lead_text="R. v. Jones was charged after an incident in 2022 involving several parties.",
    )
    assert title.startswith("R. v. Jones")


def test_court_year_case_tree_filters():
    entries = [
        _entry(court="SCC", court_year=2024, canlii_ref="2024 SCC 1"),
        _entry(court="SCC", court_year=2023, canlii_ref="2023 SCC 2"),
        _entry(court="ONCA", court_year=2024, canlii_ref="2024 ONCA 1"),
    ]
    assert courts_from_entries(entries) == ["ONCA", "SCC"]
    assert years_for_court(entries, "SCC") == [2024, 2023]
    cases = cases_for_court_year(entries, "SCC", 2024)
    assert len(cases) == 1
    assert cases[0].canlii_ref == "2024 SCC 1"
    assert "R. v. Example" in case_label(cases[0])

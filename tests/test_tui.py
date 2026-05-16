"""Smoke tests for the optional TUI."""

from __future__ import annotations

import pytest


def test_tui_module_import():
    from criminal_db.tui import run_tui

    assert callable(run_tui)


@pytest.mark.asyncio
async def test_tui_app_compose():
    pytest.importorskip("textual")

    from criminal_db.tui.app import CriminalDbApp, MENU

    app = CriminalDbApp()
    assert len(MENU) >= 10
    assert MENU[0].label == "Browse cases"
    async with app.run_test() as pilot:
        assert pilot.app is app


@pytest.mark.asyncio
async def test_case_browser_screen_compose():
    pytest.importorskip("textual")

    from textual.widgets import ListView

    from criminal_db.tui.case_browser import CaseBrowserScreen

    screen = CaseBrowserScreen()
    async with screen.run_test():
        assert screen.query_one("#col-court", ListView) is not None

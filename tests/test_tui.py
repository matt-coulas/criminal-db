"""Smoke tests for the optional TUI."""

from __future__ import annotations

import asyncio

import pytest


def test_tui_module_import():
    from criminal_db.tui import run_tui

    assert callable(run_tui)


def test_tui_app_compose():
    pytest.importorskip("textual")

    from criminal_db.tui.app import CriminalDbApp, MENU

    async def _run() -> None:
        app = CriminalDbApp()
        assert len(MENU) >= 10
        assert MENU[0].label == "Browse cases"
        async with app.run_test() as pilot:
            assert pilot.app is app

    asyncio.run(_run())


def test_case_browser_screen_compose():
    pytest.importorskip("textual")

    from textual.widgets import ListView

    from criminal_db.tui.app import CriminalDbApp
    from criminal_db.tui.case_browser import CaseBrowserScreen

    async def _run() -> None:
        async with CriminalDbApp().run_test() as pilot:
            await pilot.app.push_screen(CaseBrowserScreen())
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, CaseBrowserScreen)
            assert screen.query_one("#col-court", ListView) is not None

    asyncio.run(_run())

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
    async with app.run_test() as pilot:
        assert pilot.app is app

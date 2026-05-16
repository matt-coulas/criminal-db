"""Terminal UI for criminal-db (requires ``criminal-db[tui]``)."""

from __future__ import annotations


def run_tui() -> None:
    from .app import CriminalDbApp

    CriminalDbApp().run()


__all__ = ["run_tui"]

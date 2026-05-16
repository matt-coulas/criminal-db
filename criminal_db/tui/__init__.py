"""Terminal UI for criminal-db (requires ``criminal-db[tui]``)."""

from __future__ import annotations


def run_tui() -> None:
    import os

    os.environ.setdefault("TERM", "xterm-256color")
    os.environ.setdefault("NO_COLOR", "1")
    from .app import CriminalDbApp

    CriminalDbApp().run()


__all__ = ["run_tui"]

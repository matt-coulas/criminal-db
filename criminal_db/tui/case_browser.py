"""Miller-column case browser with full-text viewer."""

from __future__ import annotations

from typing import Optional

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, RichLog, Static

from ..db.router import DatabaseRouter
from .case_tree import (
    CaseBrowserEntry,
    CaseBrowserNode,
    case_label,
    cases_for_court_year,
    courts_from_entries,
    load_browser_entries,
    load_case_full_text,
    years_for_court,
)


class CaseBrowserScreen(Screen):
    """Browse cases court → year → case and read full text."""

    BINDINGS = [
        ("escape", "back_to_menu", "Menu"),
        ("left", "focus_left", "Left col"),
        ("right", "focus_right", "Right col"),
    ]

    CSS = """
    CaseBrowserScreen {
        layout: vertical;
    }
    #browser-columns {
        height: 14;
        min-height: 8;
    }
    .browser-col {
        width: 1fr;
        height: 100%;
        border: solid $accent;
        margin: 0 1 0 0;
    }
    .browser-col-title {
        background: $boost;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    #case-viewer {
        height: 1fr;
        min-height: 8;
        border: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    #browser-status {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._router = DatabaseRouter()
        self._entries: list[CaseBrowserEntry] = []
        self._court: Optional[str] = None
        self._year: Optional[int] = None
        self._court_nodes: list[CaseBrowserNode] = []
        self._year_nodes: list[CaseBrowserNode] = []
        self._case_nodes: list[CaseBrowserNode] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "Browse: court → year → case. Enter selects; ←/→ moves column. Esc returns to menu.",
            id="browser-status",
        )
        with Horizontal(id="browser-columns"):
            with Vertical(classes="browser-col"):
                yield Label("Court", classes="browser-col-title")
                yield ListView(id="col-court")
            with Vertical(classes="browser-col"):
                yield Label("Year", classes="browser-col-title")
                yield ListView(id="col-year")
            with Vertical(classes="browser-col"):
                yield Label("Case", classes="browser-col-title")
                yield ListView(id="col-case")
        yield RichLog(id="case-viewer", markup=False, highlight=False, wrap=True)
        yield Footer()

    def action_back_to_menu(self) -> None:
        self.app.pop_screen()

    def on_mount(self) -> None:
        self._load_index()

    @work(thread=True)
    def _load_index(self) -> None:
        try:
            entries = load_browser_entries(self._router)
        except Exception as exc:  # noqa: BLE001 — show in UI
            self.call_from_thread(self._show_error, str(exc))
            return
        self.call_from_thread(self._apply_index, entries)

    def _show_error(self, message: str) -> None:
        log = self.query_one("#case-viewer", RichLog)
        log.clear()
        log.write(f"Error loading cases:\n{message}")
        self.query_one("#browser-status", Static).update(
            "Could not read database. Run init / ingest first."
        )

    def _apply_index(self, entries: list[CaseBrowserEntry]) -> None:
        self._entries = entries
        courts = courts_from_entries(entries)
        self._fill_list(
            "col-court",
            [CaseBrowserNode(c, court=c) for c in courts],
            attr="_court_nodes",
        )
        self._fill_list("col-year", [], attr="_year_nodes")
        self._fill_list("col-case", [], attr="_case_nodes")
        self.query_one("#col-court", ListView).focus()
        count = len(entries)
        self.query_one("#browser-status", Static).update(
            f"{count} case(s) in index — select a court."
            if count
            else "No cases in database. Run init and ingest from the menu."
        )
        if not count:
            log = self.query_one("#case-viewer", RichLog)
            log.clear()
            log.write("No cases found in fulltext.db / headnotes.db.")

    def _fill_list(
        self,
        list_id: str,
        nodes: list[CaseBrowserNode],
        *,
        attr: str,
    ) -> None:
        setattr(self, attr, nodes)
        view = self.query_one(f"#{list_id}", ListView)
        view.clear()
        for node in nodes:
            view.append(ListItem(Label(node.label)))

    def _selected_node(self, nodes: list[CaseBrowserNode], list_id: str) -> Optional[CaseBrowserNode]:
        view = self.query_one(f"#{list_id}", ListView)
        idx = view.index
        if idx is None or idx < 0 or idx >= len(nodes):
            return None
        return nodes[idx]

    @on(ListView.Selected, "#col-court")
    def _court_selected(self, event: ListView.Selected) -> None:
        node = self._selected_node(self._court_nodes, "col-court")
        if node is None or node.court is None:
            return
        self._court = node.court
        self._year = None
        years = years_for_court(self._entries, self._court)
        self._fill_list(
            "col-year",
            [CaseBrowserNode(str(y), court=self._court, year=y) for y in years],
            attr="_year_nodes",
        )
        self._fill_list("col-case", [], attr="_case_nodes")
        log = self.query_one("#case-viewer", RichLog)
        log.clear()
        log.write(f"Court {self._court}: select a year.")
        self.query_one("#col-year", ListView).focus()

    @on(ListView.Selected, "#col-year")
    def _year_selected(self, event: ListView.Selected) -> None:
        node = self._selected_node(self._year_nodes, "col-year")
        if node is None or node.court is None or node.year is None:
            return
        self._court = node.court
        self._year = node.year
        cases = cases_for_court_year(self._entries, self._court, self._year)
        self._fill_list(
            "col-case",
            [
                CaseBrowserNode(case_label(c), court=self._court, year=self._year, entry=c)
                for c in cases
            ],
            attr="_case_nodes",
        )
        log = self.query_one("#case-viewer", RichLog)
        log.clear()
        log.write(f"{self._court} {self._year}: select a case.")
        self.query_one("#col-case", ListView).focus()

    @on(ListView.Selected, "#col-case")
    def _case_selected(self, event: ListView.Selected) -> None:
        node = self._selected_node(self._case_nodes, "col-case")
        if node is None or node.entry is None:
            return
        log = self.query_one("#case-viewer", RichLog)
        log.clear()
        log.write("Loading case text…")
        self._load_case_body(node.entry)

    @work(thread=True)
    def _load_case_body(self, entry: CaseBrowserEntry) -> None:
        try:
            text = load_case_full_text(self._router, entry)
        except Exception as exc:  # noqa: BLE001
            text = f"Error loading case:\n{exc}"
        self.call_from_thread(self._show_case_text, text, entry)

    def _show_case_text(self, text: str, entry: CaseBrowserEntry) -> None:
        log = self.query_one("#case-viewer", RichLog)
        log.clear()
        log.write(f"{case_label(entry)}\n{'-' * 72}\n")
        log.write(text)

    def action_focus_left(self) -> None:
        focused = self.focused
        if focused and focused.id == "col-case":
            self.query_one("#col-year", ListView).focus()
        elif focused and focused.id == "col-year":
            self.query_one("#col-court", ListView).focus()

    def action_focus_right(self) -> None:
        focused = self.focused
        if focused and focused.id == "col-court" and self._court:
            self.query_one("#col-year", ListView).focus()
        elif focused and focused.id == "col-year" and self._year:
            self.query_one("#col-case", ListView).focus()

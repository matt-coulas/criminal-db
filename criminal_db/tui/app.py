"""Textual menu for common criminal-db CLI workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

from click.testing import CliRunner
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, RichLog, Static

from criminal_db import config
from criminal_db.cli import cli


@dataclass(frozen=True)
class MenuAction:
    label: str
    hint: str
    build_args: Callable[[dict[str, str]], list[str]]
    needs_input: tuple[str, ...] = ()


MENU: list[MenuAction] = [
    MenuAction(
        "Browse cases",
        "Court → year → case; read full decision text",
        lambda _: ["__case_browser__"],
    ),
    MenuAction("Initialize (init)", "Create db/ and data/ layout", lambda _: ["init"]),
    MenuAction(
        "Ingest HTML",
        "Parse data/cases/* and data/raw (optional path)",
        lambda f: ["ingest", *([f["path"]] if f.get("path") else [])],
        ("path",),
    ),
    MenuAction(
        "Import files",
        "Import data/import/ or given path",
        lambda f: ["import", *([f["path"]] if f.get("path") else [])],
        ("path",),
    ),
    MenuAction(
        "Validate HTML",
        "Dry-run parser on file or directory",
        lambda f: ["validate", f["path"]],
        ("path",),
    ),
    MenuAction("Verify catalog ↔ DB", "Consistency checks", lambda _: ["verify"]),
    MenuAction(
        "Curate",
        "Re-apply criminal-law rules",
        lambda f: ["curate", *(["--report"] if f.get("report") == "y" else [])],
        ("report",),
    ),
    MenuAction(
        "Embed vectors",
        "sentence-transformers; optional scope",
        lambda f: [
            "embed",
            *(
                ["--scope", f["scope"]]
                if f.get("scope") in ("cases", "statutes", "all")
                else []
            ),
        ],
        ("scope",),
    ),
    MenuAction(
        "Search",
        "FTS / vector / hybrid",
        lambda f: [
            "search",
            f["query"],
            "--type",
            f.get("type") or "fts",
            "--scope",
            f.get("scope") or "cases",
            "-n",
            f.get("limit") or "10",
        ],
        ("query", "type", "scope", "limit"),
    ),
    MenuAction(
        "Get case",
        "By neutral citation",
        lambda f: ["get", f["citation"], "--format", "text"],
        ("citation",),
    ),
    MenuAction("Analyze DB", "Case counts and courts", lambda _: ["analyze"]),
    MenuAction(
        "Statutes: parse",
        "Justice Canada HTML → statutes.db",
        lambda f: ["statutes", "parse", *([f["path"]] if f.get("path") else [])],
        ("path",),
    ),
    MenuAction(
        "Statutes: get",
        "Section number",
        lambda f: ["statutes", "get", f["section"]],
        ("section",),
    ),
    MenuAction(
        "Statutes: search",
        "FTS over Criminal Code",
        lambda f: ["statutes", "search", f["query"], "-n", f.get("limit") or "10"],
        ("query", "limit"),
    ),
    MenuAction(
        "Statutes: analyze",
        "Section counts",
        lambda _: ["statutes", "analyze"],
    ),
    MenuAction(
        "Backup",
        "Archive db/ + catalog",
        lambda f: ["backup", *([f["dest"]] if f.get("dest") else [])],
        ("dest",),
    ),
    MenuAction(
        "Restore",
        "From .tar.gz archive",
        lambda f: ["restore", f["archive"]],
        ("archive",),
    ),
    MenuAction(
        "Catalog index",
        "List manifest entries",
        lambda f: [
            "index",
            *(
                ["--status", f["status"]]
                if f.get("status")
                in ("pending", "ok", "failed", "skipped", "excluded")
                else []
            ),
        ],
        ("status",),
    ),
    MenuAction("API status", "Serve URL and token hint", lambda _: ["__serve_status__"]),
]


class PromptScreen(ModalScreen[Optional[dict[str, str]]]):
    """Collect optional fields for a menu action."""

    DEFAULTS = {
        "path": "",
        "query": "",
        "citation": "",
        "section": "",
        "archive": "",
        "dest": "",
        "type": "fts",
        "scope": "cases",
        "limit": "10",
        "report": "n",
        "status": "",
    }

    PLACEHOLDERS = {
        "path": "Leave empty for CLI defaults",
        "query": "Search text",
        "citation": "e.g. 2024 SCC 1",
        "section": "e.g. 8",
        "archive": "/path/to/backup.tar.gz",
        "dest": "Optional backup directory",
        "type": "fts | vector | hybrid",
        "scope": "cases | statutes | all",
        "limit": "10",
        "report": "y for --report, else n",
        "status": "pending|ok|failed|skipped|excluded or empty",
    }

    REQUIRED = {"path", "query", "citation", "section", "archive"}

    def __init__(self, action: MenuAction) -> None:
        super().__init__()
        self.action = action

    def compose(self) -> ComposeResult:
        yield Static(f"[bold]{self.action.label}[/]\n{self.action.hint}", id="prompt-title")
        with Vertical(id="prompt-fields"):
            for key in self.action.needs_input:
                yield Label(key)
                yield Input(
                    value=self.DEFAULTS.get(key, ""),
                    placeholder=self.PLACEHOLDERS.get(key, ""),
                    id=f"field-{key}",
                )
        with Horizontal(id="prompt-buttons"):
            yield Button("Run", variant="primary", id="run")
            yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#run")
    def _run(self) -> None:
        values: dict[str, str] = {}
        for key in self.action.needs_input:
            widget = self.query_one(f"#field-{key}", Input)
            val = widget.value.strip()
            if key in self.REQUIRED and not val:
                self.app.notify(f"{key} is required", severity="error")
                return
            values[key] = val
        self.dismiss(values)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class CriminalDbApp(App):
    """Main TUI: pick a command, fill prompts, view CLI output."""

    TITLE = "criminal-db"
    SUB_TITLE = "Canadian criminal-law search"
    CSS = """
    #menu { height: 1fr; min-height: 8; }
  #log { height: 1fr; min-height: 6; border: solid $accent; }
    #paths { height: auto; padding: 0 1; color: $text-muted; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_paths", "Refresh paths"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="paths")
        with Horizontal():
            yield ListView(id="menu")
            yield RichLog(id="log", markup=False, highlight=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_paths()
        menu = self.query_one("#menu", ListView)
        for action in MENU:
            menu.append(ListItem(Label(action.label)))
        menu.focus()
        self._log_system(
            "Select an action (↑↓) and press Enter. Choose Browse cases to read full text. Press q to quit."
        )

    def _refresh_paths(self) -> None:
        paths = self.query_one("#paths", Static)
        token = "set" if config.API_TOKEN else "none"
        paths.update(
            f"data: {config.DATA_DIR}  |  db: {config.DB_DIR}  |  models: {config.MODELS_DIR}\n"
            f"API: http://{config.API_HOST}:{config.API_PORT}/  token: {token}"
        )

    def action_refresh_paths(self) -> None:
        self._refresh_paths()

    def _log_system(self, message: str) -> None:
        self.query_one("#log", RichLog).write(message)

    @staticmethod
    def _sanitize_output(text: str) -> str:
        """Strip ANSI and Rich markup triggers from CLI output."""
        return _ANSI_ESCAPE.sub("", text)

    def _log_output(self, exit_code: int, output: str) -> None:
        log = self.query_one("#log", RichLog)
        status = "ok" if exit_code == 0 else "FAILED"
        log.write(f"--- exit {exit_code} ({status}) ---")
        if output.strip():
            log.write(self._sanitize_output(output.rstrip()))

    @staticmethod
    def _serve_status_text() -> str:
        lines = [
            "HTTP API (criminal-db serve)",
            f"  listen: http://{config.API_HOST}:{config.API_PORT}/",
            "  endpoints: /health, /search?q=..., /get?citation=...",
        ]
        if config.API_TOKEN:
            lines.append("  auth: Authorization: Bearer <CRIMINAL_DB_API_TOKEN>")
        else:
            lines.append("  auth: none (set CRIMINAL_DB_API_TOKEN to protect)")
        lines.append("")
        lines.append("Docker Compose runs `serve` as the default api service.")
        lines.append("Host: map CRIMINAL_DB_HOST_PORT → container API port.")
        lines.append("TUI does not start the server; run serve in another terminal or use compose.")
        return "\n".join(lines)

    @work(thread=True)
    def _run_cli(self, args: list[str]) -> None:
        if args == ["__serve_status__"]:
            self.call_from_thread(self._log_output, 0, self._serve_status_text())
            return
        runner = CliRunner()
        result = runner.invoke(cli, args, catch_exceptions=False, color=False)
        self.call_from_thread(self._log_output, result.exit_code, result.output)

    @on(ListView.Selected, "#menu")
    def _menu_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is None or index < 0 or index >= len(MENU):
            return
        action = MENU[index]
        self._log_system(f"→ {action.label}")

        if action.build_args({}) == ["__case_browser__"]:
            from .case_browser import CaseBrowserScreen

            self.push_screen(CaseBrowserScreen())
            return

        def after_prompt(values: Optional[dict[str, str]]) -> None:
            if values is None:
                self._log_system("Cancelled.")
                return
            args = action.build_args(values)
            if args == ["__serve_status__"]:
                self._run_cli(args)
                return
            self._log_system(f"$ criminal-db {' '.join(args)}")
            self._run_cli(args)

        if action.needs_input:
            self.push_screen(PromptScreen(action), after_prompt)
        else:
            after_prompt({})

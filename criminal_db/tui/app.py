"""Textual TUI — main menu and actions for criminal-db."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RichLog,
    Static,
)
from textual.widgets.option_list import Option

from .. import config


def _run_cli(args: list[str]) -> tuple[int, str]:
    """Invoke ``criminal-db`` CLI; return (code, combined output)."""
    cmd = ["criminal-db", *args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(config.BASE_DIR),
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


class OutputScreen(Screen):
    """Show command output."""

    BINDINGS = [("escape", "dismiss", "Back"), ("q", "dismiss", "Back")]

    def __init__(self, title: str, text: str, *, success: bool = True) -> None:
        super().__init__()
        self._title = title
        self._text = text
        self._success = success

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"[bold]{self._title}[/]", id="title")
        log = RichLog(id="log", wrap=True, highlight=True)
        yield VerticalScroll(log)
        yield Button("Back", id="back", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        style = "green" if self._success else "red"
        log.write(self._text or "(no output)", shrink=False)

    @on(Button.Pressed, "#back")
    def back(self) -> None:
        self.dismiss()


class PromptScreen(Screen[str]):
    """Single-line input dialog."""

    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, label: str, *, placeholder: str = "", default: str = "") -> None:
        super().__init__()
        self._label = label
        self._placeholder = placeholder
        self._default = default

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(self._label)
        yield Input(placeholder=self._placeholder, value=self._default, id="value")
        with Container():
            yield Button("OK", id="ok", variant="primary")
            yield Button("Cancel", id="cancel")
        yield Footer()

    @on(Button.Pressed, "#ok")
    def ok(self) -> None:
        self.dismiss(self.query_one("#value", Input).value.strip())

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(Screen[bool]):
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._message)
        with Container():
            yield Button("Yes", id="yes", variant="primary")
            yield Button("No", id="no")
        yield Footer()

    @on(Button.Pressed, "#yes")
    def yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def no(self) -> None:
        self.dismiss(False)


class MenuScreen(Screen):
    """Main action menu."""

    BINDINGS = [("q", "quit", "Quit"), ("slash", "search_palette", "Search")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._status_text(), id="status")
        opts = OptionList(id="menu")
        for label, _ in MENU_ITEMS:
            opts.add_option(Option(label))
        yield opts
        yield Footer()

    def _status_text(self) -> str:
        lines = [
            f"data: {config.DATA_DIR}",
            f"db:   {config.DB_DIR}",
            f"api:  {config.API_HOST}:{config.API_PORT}",
        ]
        return "\n".join(lines)

    @on(OptionList.OptionSelected, "#menu")
    async def menu_select(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx is None or idx >= len(MENU_ITEMS):
            return
        _, handler_name = MENU_ITEMS[idx]
        handler = getattr(self.app, handler_name, None)
        if handler is None:
            return
        result = handler()
        if hasattr(result, "__await__"):
            await result

    def action_quit(self) -> None:
        self.app.exit()

    def action_search_palette(self) -> None:
        self.app.action_do_search()


MENU_ITEMS: list[tuple[str, str]] = [
    ("Initialize databases and directories", "action_do_init"),
    ("Import cases (HTML/PDF from data/import/)", "action_do_import"),
    ("Ingest cases (data/cases/)", "action_do_ingest"),
    ("Parse HTML files (path prompt)", "action_do_parse"),
    ("Statutes: parse Criminal Code HTML", "action_do_statutes_parse"),
    ("Search (cases / statutes / all)", "action_do_search"),
    ("Get case by citation", "action_do_get_case"),
    ("Get statute section", "action_do_statutes_get"),
    ("Curate: apply criminal-law rules", "action_do_curate"),
    ("Curate: QA report (dry-run)", "action_do_curate_report_dry"),
    ("Curate: QA report (apply + list)", "action_do_curate_report"),
    ("Validate HTML (parser QA)", "action_do_validate"),
    ("Verify manifest ↔ databases", "action_do_verify"),
    ("Embed missing vectors (cases + statutes)", "action_do_embed"),
    ("Analyze corpus statistics", "action_do_analyze"),
    ("Backup databases → tarball", "action_do_backup"),
    ("Restore from backup archive", "action_do_restore"),
    ("Export cases to JSON", "action_do_export"),
    ("Catalog index (manifest)", "action_do_index"),
    ("Quit", "action_quit_app"),
]


class CriminalDbTui(App):
    """criminal-db terminal UI."""

    TITLE = "criminal-db"
    SUB_TITLE = "Canadian criminal-law corpus"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
    ]

    def on_mount(self) -> None:
        self.push_screen(MenuScreen())

    def action_quit(self) -> None:
        self.exit()

    def action_help(self) -> None:
        self.push_screen(
            OutputScreen(
                "Help",
                "Use ↑↓ to select, Enter to run. "
                "Press q to quit. API runs via docker compose service 'api'.\n\n"
                "Mount corpus at CRIMINAL_DB_DATA_DIR and databases at "
                "CRIMINAL_DB_DB_DIR (see compose.yaml).",
            )
        )

    def _show_cli(self, title: str, args: list[str]) -> None:
        code, out = _run_cli(args)
        self.push_screen(OutputScreen(title, out, success=code == 0))

    @work(thread=True)
    def _run_cli_async(self, title: str, args: list[str]) -> None:
        code, out = _run_cli(args)
        self.call_from_thread(
            self.push_screen, OutputScreen(title, out, success=code == 0)
        )

    def action_quit_app(self) -> None:
        self.exit()

    def action_do_init(self) -> None:
        self._run_cli_async("Initialize", ["init"])

    def action_do_import(self) -> None:
        self._run_cli_async("Import", ["import", "--criminal-only"])

    def action_do_ingest(self) -> None:
        self._run_cli_async("Ingest", ["ingest", "--criminal-only"])

    async def action_do_parse(self) -> None:
        path = await self.push_screen_wait(
            PromptScreen("Path to HTML file or directory", placeholder="/data/import/html")
        )
        if not path:
            return
        self._run_cli_async("Parse", ["parse", path])

    def action_do_statutes_parse(self) -> None:
        self._run_cli_async("Statutes parse", ["statutes", "parse"])

    async def action_do_search(self) -> None:
        query = await self.push_screen_wait(
            PromptScreen("Search query", placeholder="section 8 charter")
        )
        if not query:
            return
        scope = await self.push_screen_wait(
            PromptScreen("Scope: cases | statutes | all", default="cases")
        )
        if not scope:
            return
        mode = await self.push_screen_wait(
            PromptScreen("Type: fts | hybrid", default="fts")
        )
        if not mode:
            return
        args = ["--json", "search", query, "--scope", scope, "--type", mode, "--limit", "10"]
        code, out = _run_cli(args)
        if code == 0:
            try:
                data = json.loads(out)
                lines = [f"Query: {data.get('query')}", ""]
                for i, r in enumerate(data.get("results") or [], 1):
                    if r.get("kind") == "statute":
                        lines.append(
                            f"{i}. [statute] s.{r.get('section')} score={r.get('score', 0):.3f}"
                        )
                    elif r.get("canlii_ref"):
                        lines.append(
                            f"{i}. {r.get('canlii_ref')} score={r.get('score', 0):.3f}"
                        )
                    else:
                        lines.append(f"{i}. {json.dumps(r)[:120]}")
                out = "\n".join(lines)
            except json.JSONDecodeError:
                pass
        self.push_screen(OutputScreen("Search", out, success=code == 0))

    async def action_do_get_case(self) -> None:
        cite = await self.push_screen_wait(
            PromptScreen("Neutral citation", placeholder="2024 SCC 1")
        )
        if not cite:
            return
        self._run_cli_async("Get case", ["get", cite])

    async def action_do_statutes_get(self) -> None:
        sec = await self.push_screen_wait(
            PromptScreen("Section number", placeholder="8")
        )
        if not sec:
            return
        self._run_cli_async("Statute", ["statutes", "get", sec])

    def action_do_curate(self) -> None:
        self._run_cli_async("Curate", ["curate"])

    def action_do_curate_report_dry(self) -> None:
        self._run_cli_async("Curate QA (dry-run)", ["curate", "--report", "--dry-run"])

    def action_do_curate_report(self) -> None:
        self._run_cli_async("Curate QA", ["curate", "--report"])

    async def action_do_validate(self) -> None:
        path = await self.push_screen_wait(
            PromptScreen(
                "HTML path to validate",
                placeholder=str(config.IMPORT_DIR / "html"),
            )
        )
        if not path:
            return
        self._run_cli_async("Validate", ["validate", path])

    def action_do_verify(self) -> None:
        self._run_cli_async("Verify", ["verify"])

    def action_do_embed(self) -> None:
        self._run_cli_async("Embed", ["embed", "--scope", "all"])

    def action_do_analyze(self) -> None:
        self._run_cli_async("Analyze", ["analyze"])

    async def action_do_backup(self) -> None:
        dest = await self.push_screen_wait(
            PromptScreen(
                "Backup directory or .tar.gz path",
                default=str(config.DB_DIR / "backups"),
            )
        )
        if not dest:
            return
        self._run_cli_async("Backup", ["backup", dest])

    async def action_do_restore(self) -> None:
        path = await self.push_screen_wait(
            PromptScreen("Path to backup .tar.gz", placeholder="db/backups/...")
        )
        if not path:
            return
        ok = await self.push_screen_wait(
            ConfirmScreen(f"Restore from {path}? This overwrites databases.")
        )
        if ok:
            self._run_cli_async("Restore", ["restore", path])

    async def action_do_export(self) -> None:
        out = await self.push_screen_wait(
            PromptScreen(
                "Export JSON path",
                default=str(config.DATA_DIR / "export" / "cases.json"),
            )
        )
        if not out:
            return
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        self._run_cli_async("Export", ["export", "-o", out])

    def action_do_index(self) -> None:
        self._run_cli_async("Catalog index", ["index"])


def run_tui() -> None:
    """Entry point for ``criminal-db-tui``."""
    CriminalDbTui().run()


if __name__ == "__main__":  # pragma: no cover
    run_tui()

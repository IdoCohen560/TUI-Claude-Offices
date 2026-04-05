#!/usr/bin/env python3
"""Claude Office TUI — rich terminal visualizer with pixel art.

Run standalone: cd tui && uv run python office.py
No tmux needed — works in any modern terminal.
"""

import asyncio
import json
from datetime import datetime
from rich.markup import escape

import websockets
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Footer, Header, Label, RichLog, Static

import os
import sys

WS_URL = "ws://localhost:8000/ws/{session_id}"
API_URL = "http://localhost:8000/api/v1"

# Agent colors (Rich color names — all single-width safe)
COLORS = [
    "dodger_blue1", "green3", "medium_purple1", "dark_orange",
    "hot_pink", "dark_cyan", "gold1", "red1",
]


def agent_at_desk(color: str, name: str, status: str, task: str) -> list[str]:
    """Render an agent at their desk — fixed-width, no emojis."""
    n = escape(name[:10]).center(14)
    s = escape(status[:12]).center(14)
    t = escape(task[:12]).center(14) if task else " " * 14
    return [
        f"[bold {color}]{n}[/]",
        f"[{color}]    .---.     [/]",
        f"[{color}]    |[/][bold white]o o[/][{color}]|     [/]",
        f"[{color}]    | ~ |     [/]",
        f"[{color}]   /|   |\\    [/]",
        f"[{color}]  / |___|[/][dim]=[/][{color}]\\   [/]",
        f"[dim] +-----------+ [/]",
        f"[dim] |[/][{color}]  ~~~~~~~  [/][dim]| [/]",
        f"[dim] +-----------+ [/]",
        f"[bold {color}]{s}[/]",
        f"[dim italic]{t}[/]",
    ]


def empty_desk(num: int) -> list[str]:
    """Render an empty desk — fixed-width."""
    label = f"Desk {num}".center(14)
    return [
        f"[dim]{label}[/]",
        f"              ",
        f"              ",
        f"              ",
        f"              ",
        f"              ",
        f"[dim] +-----------+ [/]",
        f"[dim] |           | [/]",
        f"[dim] +-----------+ [/]",
        f"[dim]      --      [/]",
        f"              ",
    ]


def boss_sprite(state: str, task: str) -> list[str]:
    """Render the boss character — fixed-width, no emojis."""
    icons = {
        "idle": ("z z", "idle"),
        "working": ("* *", "coding"),
        "delegating": ("> >", "delegating"),
        "receiving": ("o o", "on phone"),
        "waiting_permission": ("? ?", "waiting"),
        "reviewing": ("- -", "reviewing"),
        "completing": ("^ ^", "done!"),
    }
    eyes, label = icons.get(state, ("o o", state))
    t = escape(task[:30]) if task else ""

    return [
        f"  [bold yellow]  .===.  [/]",
        f"  [bold yellow]  |[/][bold white]{eyes}[/][bold yellow]|  [/]",
        f"  [bold yellow]  | v |  [/]",
        f"  [bold yellow] /|   |\\ [/]",
        f"  [bold yellow]= |___| =[/]",
        f"  [dim]+=========+[/]",
        f"  [dim]|[/][bold yellow] {label:^7s} [/][dim]|[/]",
        f"  [dim]+=========+[/]",
        f"  [dim italic]{t}[/]",
    ]


def elevator_sprite(is_open: bool) -> list[str]:
    """Render elevator — fixed-width, no emojis."""
    if is_open:
        return [
            f"[bold cyan] +------+ [/]",
            f"[cyan] |      | [/]",
            f"[cyan] | [bold]OPEN[/] | [/]",
            f"[cyan] |      | [/]",
            f"[bold cyan] +------+ [/]",
        ]
    return [
        f"[dim] +------+ [/]",
        f"[dim] |######| [/]",
        f"[dim] |##||##| [/]",
        f"[dim] |######| [/]",
        f"[dim] +------+ [/]",
    ]


class OfficeView(Static):
    """Renders the office with fixed-width character art."""

    boss_state: reactive[str] = reactive("idle")
    boss_task: reactive[str] = reactive("")
    context_pct: reactive[float] = reactive(0.0)
    agents: reactive[list] = reactive(list, always_update=True)
    tool_count: reactive[int] = reactive(0)
    tick: reactive[int] = reactive(0)

    def render(self) -> Text:
        return Text.from_markup(self._build_markup())

    def _build_markup(self) -> str:
        lines: list[str] = []

        # Context bar with color
        pct = self.context_pct
        bar_w = 30
        filled = int(pct * bar_w)
        clr = "red" if pct > 0.9 else ("yellow" if pct > 0.7 else "green")
        bar = f"[{clr}]{'#' * filled}[/][dim]{'.' * (bar_w - filled)}[/]"

        lines.append("")
        lines.append(f"  [bold white on blue] CLAUDE OFFICE [/]           Context [{bar}] [bold]{pct:.0%}[/]")
        lines.append(f"  [dim]{'_' * 72}[/]")
        lines.append("")

        # Boss
        b_lines = boss_sprite(self.boss_state, self.boss_task)

        lines.append(f"  [underline bold]BOSS[/]")
        for bl in b_lines:
            lines.append(f"  {bl}")

        lines.append("")
        lines.append(f"  [dim]{'=' * 72}[/]")

        # Agent desks - 2 rows of 4
        agent_list = list(self.agents) if self.agents else []

        # Dynamic rows — grows as agents are added (minimum 2 rows / 8 desks)
        agent_count = len(agent_list)
        # Default 4 desks (1 row), grows only when agents exceed 4
        total_desks = max(4, ((agent_count + 3) // 4) * 4)
        num_rows = total_desks // 4

        for row in range(num_rows):
            lines.append("")
            desk_start = row * 4

            # Build sprites for this row
            sprites: list[list[str]] = []
            for d in range(4):
                idx = desk_start + d
                if idx < len(agent_list):
                    a = agent_list[idx]
                    ci = idx % len(COLORS)
                    name = a.get("name", "Agent")
                    state = a.get("state", "working")

                    state_labels = {
                        "working": "* WORKING *",
                        "thinking": ". THINKING .",
                        "arriving": "> ARRIVING >",
                        "walking_to_desk": "> WALKING >",
                        "waiting": "~ WAITING ~",
                        "waiting_permission": "? PENDING ?",
                        "completed": "! DONE !",
                        "leaving": "< LEAVING <",
                        "reporting": "^ REPORT ^",
                    }
                    status = state_labels.get(state, state[:12])

                    bubble = a.get("bubble")
                    task = ""
                    if bubble and isinstance(bubble, dict):
                        task = bubble.get("text", "")[:12]
                    if not task:
                        task = (a.get("currentTask") or "")[:12]

                    sprites.append(agent_at_desk(COLORS[ci], name, status, task))
                else:
                    sprites.append(empty_desk(idx + 1))

            # Render sprite rows side by side
            max_rows = max(len(s) for s in sprites)
            for r in range(max_rows):
                row_str = "  "
                for s in sprites:
                    cell = s[r] if r < len(s) else " " * 14
                    row_str += f" {cell} "
                lines.append(row_str)

        # Metrics footer
        n = len(agent_list)
        spinner_chars = "|/-\\"
        sp = spinner_chars[self.tick % 4] if n > 0 else " "

        lines.append("")
        lines.append(f"  [dim]{'_' * 72}[/]")
        lines.append(
            f"  [bold]Tools:[/] {self.tool_count:<4}  "
            f"[bold]Active:[/] {n}  "
            f"[bold]Desks:[/] {total_desks}   "
            f"{'[bold green]' + sp + ' Processing[/]' if n > 0 else '[dim]Idle[/]'}"
        )

        return "\n".join(lines)


class OfficeApp(App):
    """Claude Office TUI. Run standalone — no tmux needed."""

    TITLE = "Claude Office"
    SUB_TITLE = "Terminal Visualizer"

    CSS = """
    Screen {
        layout: horizontal;
        background: $surface;
    }
    #office-scroll {
        width: 2fr;
        min-width: 60;
        height: 100%;
    }
    #office-view {
        width: 100%;
        height: auto;
        padding: 0;
    }
    #sidebar {
        width: 1fr;
        max-width: 40;
        min-width: 28;
        height: 100%;
        border-left: thick $accent;
    }
    #event-log {
        height: 1fr;
    }
    #info-panel {
        height: auto;
        max-height: 5;
        padding: 0 1;
        border-top: solid $secondary;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        text-align: center;
        background: $boost;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reconnect", "Reconnect"),
        Binding("d", "toggle_dark", "Theme"),
        Binding("j", "scroll_down", "Scroll Down", show=False),
        Binding("k", "scroll_up", "Scroll Up", show=False),
        Binding("down", "scroll_down", "Scroll Down", show=False),
        Binding("up", "scroll_up", "Scroll Up", show=False),
    ]

    connected = reactive(False)
    session_id = reactive("")
    _tick_timer: Timer | None = None
    _cli_session: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with VerticalScroll(id="office-scroll"):
                yield OfficeView(id="office-view")
            with Vertical(id="sidebar"):
                yield RichLog(id="event-log", max_lines=300, markup=True, wrap=True)
                yield Static(id="info-panel")
        yield Label("Connecting...", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._tick_timer = self.set_interval(0.25, self._tick)
        self.fetch_session_and_connect()

    def _tick(self) -> None:
        self.query_one("#office-view", OfficeView).tick += 1

    @work(exclusive=True)
    async def fetch_session_and_connect(self) -> None:
        import urllib.request

        status = self.query_one("#status-bar", Label)
        log = self.query_one("#event-log", RichLog)
        info = self.query_one("#info-panel", Static)

        try:
            with urllib.request.urlopen(f"{API_URL}/sessions", timeout=5) as resp:
                sessions = json.loads(resp.read())
        except Exception as e:
            status.update(f"[bold red]Cannot reach backend: {e}[/]")
            return

        if not sessions:
            status.update("[yellow]No sessions. Start Claude Code first.[/]")
            return

        # Priority: --session CLI arg > CLAUDE_SESSION_ID env var > auto-detect
        explicit_id = self._cli_session or os.environ.get("CLAUDE_SESSION_ID")

        if explicit_id:
            # Find the explicit session, or use it directly
            best = next((s for s in sessions if s["id"] == explicit_id), None)
            if not best:
                # Session ID exists but not in backend yet — use it anyway
                best = {"id": explicit_id, "status": "active", "eventCount": 0}
                log.write(Text(f"Waiting for session {explicit_id[:12]}...", style="yellow"))
        else:
            active = [s for s in sessions if s["status"] == "active"]
            candidates = active if active else sessions
            best = max(candidates, key=lambda s: s.get("eventCount", 0))

        self.session_id = best["id"]
        name = best.get("label") or best.get("projectName") or self.session_id[:8]

        info.update(
            f"[bold]Session:[/] {name}\n"
            f"[bold]ID:[/] [dim]{self.session_id[:20]}...[/]\n"
            f"[bold]Events:[/] {best.get('eventCount', 0)}"
        )
        log.write(Text(f"Connecting to: {name}", style="bold cyan"))

        ws_url = WS_URL.format(session_id=self.session_id)
        retry = 0
        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    self.connected = True
                    retry = 0
                    status.update(f"[bold green]LIVE[/] -- {name} ({self.session_id[:8]}...)")
                    log.write(Text("Connected!", style="bold green"))

                    async for raw in ws:
                        try:
                            self._handle_message(json.loads(raw))
                        except json.JSONDecodeError:
                            pass
            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError):
                self.connected = False
                retry += 1
                wait = min(retry * 2, 10)
                status.update(f"[bold red]DISCONNECTED[/] -- retry in {wait}s...")
                await asyncio.sleep(wait)

    def _handle_message(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "state_update":
            self._update_state(msg.get("state", {}))
        elif t == "event":
            self._log_event(msg.get("event", {}))

    def _update_state(self, state: dict) -> None:
        v = self.query_one("#office-view", OfficeView)
        boss = state.get("boss", {})
        v.boss_state = boss.get("state", "idle")
        v.boss_task = boss.get("currentTask") or ""
        office = state.get("office", {})
        v.context_pct = office.get("contextUtilization", 0)
        v.tool_count = office.get("toolUsesSinceCompaction", 0)
        v.agents = state.get("agents", [])

    def _log_event(self, event: dict) -> None:
        log = self.query_one("#event-log", RichLog)
        summary = escape(event.get("summary", event.get("type", "?")))
        agent = event.get("agentId", "")
        ts = event.get("timestamp", "")
        evt_type = event.get("type", "")

        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M:%S")
        except (ValueError, AttributeError):
            time_str = "??:??:??"

        if "subagent_start" in evt_type:
            style = "bold green"
        elif "subagent_stop" in evt_type:
            style = "bold red"
        elif "user_prompt" in evt_type:
            style = "bold yellow"
        elif "stop" == evt_type:
            style = "bold magenta"
        elif agent and agent != "main":
            style = "cyan"
        else:
            style = "white"

        agent_tag = escape(agent[:8]) if agent and agent != "main" else ""
        prefix = f"[dim]\\[{agent_tag}][/] " if agent_tag else ""
        log.write(Text.from_markup(f"[dim]{time_str}[/] {prefix}[{style}]{summary}[/]"))

    def action_scroll_down(self) -> None:
        self.query_one("#office-scroll", VerticalScroll).scroll_down(animate=False)

    def action_scroll_up(self) -> None:
        self.query_one("#office-scroll", VerticalScroll).scroll_up(animate=False)

    def action_reconnect(self) -> None:
        self.fetch_session_and_connect()

    def action_toggle_dark(self) -> None:
        self.theme = "textual-light" if self.theme == "textual-dark" else "textual-dark"


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Claude Office TUI")
    parser.add_argument(
        "--session", "-s",
        help="Session ID to connect to (default: auto-detect or CLAUDE_SESSION_ID env var)",
    )
    args = parser.parse_args()

    app = OfficeApp()
    app._cli_session = args.session
    app.run()


if __name__ == "__main__":
    main()

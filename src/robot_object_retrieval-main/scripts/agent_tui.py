from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib import error


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.agent_service import AgentSession
from robot_object_retrieval.application.agent_service import AgentTurnResult
from robot_object_retrieval.config import get_agent_config
from robot_object_retrieval.infrastructure.chat_models import ChatEndpointError
from robot_object_retrieval.infrastructure.chat_models import get_chat_model
from robot_object_retrieval.infrastructure.catalog_runtime import get_catalog_runtime
from robot_object_retrieval.infrastructure.prompt_profiles import (
    DEFAULT_PROMPT_PROFILE_PATH,
    load_prompt_profile,
)


def parse_args() -> argparse.Namespace:
    config = get_agent_config()
    parser = argparse.ArgumentParser(description="CLI-style object-retrieval agent TUI")
    parser.add_argument(
        "--model",
        default=config.model_name,
        help="OpenAI-compatible chat model name, e.g. gemma4:e4b",
    )
    parser.add_argument(
        "--provider",
        choices=["openai-compatible", "ollama-native"],
        default="openai-compatible",
        help="Chat provider. Use ollama-native to show Ollama thinking output.",
    )
    parser.add_argument(
        "--chat-url",
        default=None,
        help=(
            "Override chat endpoint URL. Defaults to .env for openai-compatible "
            "and http://localhost:11434/api/chat for ollama-native."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable request/response trace output",
    )
    parser.add_argument(
        "--debug-dir",
        default=".agent_debug",
        help="Directory for saving request/response traces when --debug is enabled",
    )
    parser.add_argument(
        "--enable-robot-tools",
        action="store_true",
        help="Enable fake move_platform/use_vla tools for planning smoke tests",
    )
    parser.add_argument(
        "--prompt-profile",
        type=Path,
        default=DEFAULT_PROMPT_PROFILE_PATH,
        help="YAML prompt profile path",
    )
    return parser.parse_args()


def build_session(args: argparse.Namespace) -> AgentSession:
    debug_dir = Path(args.debug_dir).resolve() if args.debug else None
    catalog_runtime = get_catalog_runtime()

    return AgentSession(
        model=args.model,
        debug_dir=debug_dir,
        chat_model=get_chat_model(provider=args.provider, chat_url=args.chat_url),
        semantic_map_search=catalog_runtime.semantic_map_search,
        semantic_map_regions=catalog_runtime.semantic_map_regions,
        prompt_profile=load_prompt_profile(args.prompt_profile),
        enable_robot_tools=args.enable_robot_tools,
    )


def run_tui(args: argparse.Namespace) -> None:
    try:
        from textual import work
        from textual.app import App, ComposeResult
        from textual.containers import Container
        from textual.timer import Timer
        from textual.widgets import Input, RichLog, Static

        from rich.text import Text
    except ImportError as exc:
        raise SystemExit(
            "Textual is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    def compact_json(value: object, *, max_length: int = 180) -> str:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 1]}…"

    def summarize_tool_result(result: dict[str, object]) -> str:
        payload = result.get("result")
        if isinstance(payload, dict):
            if "results" in payload and isinstance(payload["results"], list):
                return f"{len(payload['results'])} candidates"
            if "success" in payload:
                return f"success={payload.get('success')}"
            if "error" in payload:
                return str(payload["error"])
        return compact_json(payload)

    def format_tool_payload(result: dict[str, object]) -> list[str]:
        payload = result.get("debug_result", result.get("result"))
        if not isinstance(payload, dict):
            return [compact_json(payload, max_length=220)]

        rows: list[str] = []
        if "query" in payload:
            rows.append(f"query={payload.get('query')}")
        if "limit" in payload:
            rows.append(f"limit={payload.get('limit')}")
        if "frame_id" in payload:
            rows.append(f"frame_id={payload.get('frame_id')}")
        results = payload.get("results")
        if isinstance(results, list):
            for index, item in enumerate(results[:3], start=1):
                if not isinstance(item, dict):
                    continue
                position = item.get("position")
                if isinstance(position, dict):
                    rows.append(
                        f"{index}. id={item.get('id', '?')} class={item.get('class', '?')} "
                        f"x={position.get('x', '?')} y={position.get('y', '?')} "
                        f"z={position.get('z', '?')} confidence={item.get('confidence', '?')} "
                        f"similarity={item.get('similarity', '?')}"
                    )
                    continue
                name = item.get("name", "?")
                location = item.get("location_name", "?")
                x = item.get("x", "?")
                y = item.get("y", "?")
                similarity = item.get("similarity", "?")
                rows.append(
                    f"{index}. id={item.get('id', '?')} name={name} "
                    f"loc={location} x={x} y={y} sim={similarity}"
                )
            if len(results) > 3:
                rows.append(f"... {len(results) - 3} more")
            return rows

        if "object" in payload:
            rows.append(f"object={compact_json(payload['object'], max_length=180)}")
        if "error" in payload:
            rows.append(f"error={payload['error']}")
        if not rows:
            rows.append(compact_json(payload, max_length=220))
        return rows

    class AgentTui(App[None]):
        CSS = """
        Screen {
            layout: vertical;
            background: #0d1117;
            color: #d0d7de;
        }

        #status {
            height: 1;
            padding: 0 1;
            background: #161b22;
            color: #8b949e;
        }

        #feed {
            height: 1fr;
            padding: 1 2;
            background: #0d1117;
        }

        #input_bar {
            height: 3;
            padding: 0 1 1 1;
            background: #0d1117;
        }

        #prompt {
            height: 1;
            border: none;
            background: #0d1117;
        }
        """

        BINDINGS = [
            ("ctrl+q", "quit", "Quit"),
            ("ctrl+c", "quit", "Quit"),
            ("ctrl+l", "clear_feed", "Clear"),
        ]

        def __init__(self, session: AgentSession) -> None:
            super().__init__()
            self.session = session
            self.status: Static
            self.feed: RichLog
            self.prompt: Input
            self.turn_count = 0
            self.last_tool = "none"
            self.trace_path = "none"
            self.state = "idle"
            self.answer_timer: Timer | None = None

        def compose(self) -> ComposeResult:
            yield Static(id="status")
            yield RichLog(id="feed", wrap=True, highlight=False, markup=False)
            with Container(id="input_bar"):
                yield Input(placeholder="message", id="prompt")

        def on_mount(self) -> None:
            self.status = self.query_one("#status", Static)
            self.feed = self.query_one("#feed", RichLog)
            self.prompt = self.query_one("#prompt", Input)
            self.write_line("system", "Agent TUI ready. Ctrl+L clears the view, session history stays.", "dim")
            self.write_line("system", f"provider={args.provider}", "dim")
            self.refresh_status("ready")
            self.call_after_refresh(self.prompt.focus)

        def on_input_submitted(self, event: Input.Submitted) -> None:
            user_input = event.value.strip()
            if not user_input:
                return

            self.prompt.value = ""
            self.prompt.disabled = True
            self.turn_count += 1
            self.write_line("user", user_input, "green")
            self.write_line("thinking", "model request started", "yellow")
            self.refresh_status("thinking")
            self.send_message(user_input)

        @work(thread=True, exclusive=True)
        def send_message(self, user_input: str) -> None:
            try:
                result = self.session.send(user_input, on_event=self.handle_agent_event)
            except ChatEndpointError as exc:
                self.call_from_thread(self.show_error, f"Chat endpoint error: {exc}")
            except error.URLError as exc:
                self.call_from_thread(self.show_error, f"Connection error: {exc}")
            except Exception as exc:
                self.call_from_thread(self.show_error, f"Agent error: {exc}")
            else:
                self.call_from_thread(self.finish_turn, result)

        def handle_agent_event(self, event: dict[str, object]) -> None:
            event_type = event.get("type")
            if event_type == "tool_call":
                tool_name = str(event.get("tool_name", "unknown_tool"))
                arguments = event.get("arguments", {})
                self.call_from_thread(
                    self.show_tool_call,
                    tool_name,
                    compact_json(arguments),
                )
            elif event_type == "tool_result":
                self.call_from_thread(self.show_tool_result, event)
            elif event_type == "reasoning":
                self.call_from_thread(self.show_reasoning, str(event.get("content", "")))

        def show_reasoning(self, content: str) -> None:
            self.write_multiline("reasoning", content, "dim")

        def show_tool_call(self, tool_name: str, arguments: str) -> None:
            self.last_tool = tool_name
            self.write_line("tool call", f"{tool_name} {arguments}", "yellow")
            self.refresh_status("tool")

        def show_tool_result(self, event: dict[str, object]) -> None:
            tool_name = str(event.get("tool_name", "unknown_tool"))
            self.write_line("tool result", f"{tool_name}: {summarize_tool_result(event)}", "green")
            for row in format_tool_payload(event):
                self.write_line("  data", row, "dim")
            self.refresh_status("thinking")

        def finish_turn(self, result: AgentTurnResult) -> None:
            self.trace_path = str(result.trace_path) if result.trace_path else "none"
            self.write_multiline("assistant", result.answer, "green")
            self.prompt.disabled = False
            self.refresh_status("ready")
            self.prompt.focus()

        def show_error(self, message: str) -> None:
            self.write_line("error", message, "red")
            self.prompt.disabled = False
            self.refresh_status("error")
            self.prompt.focus()

        def write_line(self, label: str, message: str, style: str) -> None:
            line = Text()
            line.append("● ", style=style)
            line.append(f"{label:<11}", style=style)
            line.append(" ")
            line.append(message, style=style)
            self.feed.write(line, scroll_end=True)

        def write_multiline(self, label: str, message: str, style: str) -> None:
            lines = message.splitlines() or [""]
            self.write_line(label, lines[0], style)
            for line_text in lines[1:]:
                line = Text()
                line.append("  ")
                line.append(f"{'':<11}")
                line.append(" ")
                line.append(line_text, style=style)
                self.feed.write(line, scroll_end=True)

        def refresh_status(self, state: str) -> None:
            self.state = state
            style = {
                "ready": "green",
                "thinking": "yellow",
                "tool": "yellow",
                "error": "red",
            }.get(state, "dim")
            status = Text()
            status.append(f" {state.upper():<8}", style=style)
            status.append(f" model={self.session.model}", style="dim")
            status.append(f" provider={args.provider}", style="dim")
            status.append(f" turns={self.turn_count}", style="dim")
            status.append(f" messages={len(self.session.messages)}", style="dim")
            status.append(f" last_tool={self.last_tool}", style="dim")
            if self.session.debug_dir:
                status.append(f" trace={self.trace_path}", style="dim")
            self.status.update(status)

        def action_clear_feed(self) -> None:
            self.feed.clear()
            self.write_line("system", "view cleared; session history is still active", "dim")
            self.refresh_status(self.state)

    AgentTui(build_session(args)).run()


def main() -> int:
    args = parse_args()
    run_tui(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

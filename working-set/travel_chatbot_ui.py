import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_framework import (
    AgentSession,
    EXCLUDE_REASON_KEY,
    EXCLUDED_KEY,
    CharacterEstimatorTokenizer,
    FileSystemAgentFileStore,
    get_agent_mode,
    included_messages,
)

USAGE_STATE_KEY = "chatbot_usage"
MCP_MAX_RESULTS_SHOWN = 5
MCP_MAX_LINE_CHARS = 100


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CUSTOMER = "\033[96m"
    CONCIERGE = "\033[92m"
    EVENT = "\033[93m"
    MCP = "\033[94m"
    SYSTEM = "\033[95m"


@dataclass(frozen=True)
class ChatbotUIConfig:
    customer_id: str
    profile_file: str
    memory_root: Path
    compaction_strategy: str
    compaction_target_messages: int
    compaction_threshold_messages: int
    max_context_window_tokens: int
    mcp_server_name: str = "MCP"
    mcp_tool_names: frozenset[str] = field(default_factory=frozenset)


_use_color = False


def _styled(text: str, *styles: str) -> str:
    if not _use_color:
        return text
    return f"{''.join(styles)}{text}{Style.RESET}"


def _print_message(speaker: str, text: str, color: str) -> None:
    border = "─" * 68
    print("\n" + _styled(border, color, Style.DIM))
    print(_styled(f" {speaker.upper()} ", color, Style.BOLD))
    print(_styled(text, color))
    print(_styled(border, color, Style.DIM))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive travel concierge chatbot")
    parser.add_argument(
        "--reset-memory",
        action="store_true",
        help="Clear the demo customer profile before starting",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI terminal colors")
    return parser.parse_args()


def _history_metrics(session: AgentSession) -> tuple[int, int, int, list[str]]:
    messages = session.state.get("in_memory", {}).get("messages", [])
    active_messages = included_messages(messages)
    excluded_messages = [
        message
        for message in messages
        if message.additional_properties.get(EXCLUDED_KEY, False)
    ]
    reasons = sorted({
        message.additional_properties.get(EXCLUDE_REASON_KEY, "unknown")
        for message in excluded_messages
    })
    return len(messages), len(active_messages), len(excluded_messages), reasons


def _tool_calls(response: Any) -> list[str]:
    calls: list[str] = []
    for message in response.messages:
        for content in message.contents:
            if content.type == "function_call" and content.name:
                calls.append(content.name)
    return calls


def _truncate(text: str, limit: int = MCP_MAX_LINE_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _one_line(text: Any) -> str:
    return " ".join(str(text).split())


def _field(item: dict[str, Any], *names: str) -> str | None:
    lowered = {key.lower(): value for key, value in item.items()}
    for name in names:
        value = lowered.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _mcp_result_items(payload: Any, found: list[tuple[str, str]], seen: set[str]) -> None:
    if isinstance(payload, list):
        for entry in payload:
            _mcp_result_items(entry, found, seen)
    elif isinstance(payload, dict):
        url = _field(payload, "url")
        title = _field(payload, "title", "name")
        if url and url not in seen:
            seen.add(url)
            found.append((title or _field(payload, "domain", "sitename") or url, url))
        for value in payload.values():
            if isinstance(value, (dict, list)):
                _mcp_result_items(value, found, seen)


def _mcp_exchanges(response: Any, tool_names: frozenset[str]) -> list[tuple[str, dict[str, Any], Any]]:
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    exchanges: list[tuple[str, dict[str, Any], Any]] = []
    for message in response.messages:
        for content in message.contents:
            if content.type == "function_call" and content.name in tool_names and content.call_id:
                try:
                    arguments = content.parse_arguments() or {}
                except (TypeError, ValueError):
                    arguments = {"raw": str(content.arguments)}
                calls[content.call_id] = (content.name, arguments)
            elif content.type == "function_result" and content.call_id in calls:
                name, arguments = calls.pop(content.call_id)
                exchanges.append((name, arguments, content))
    exchanges.extend((name, arguments, None) for name, arguments in calls.values())
    return exchanges


def _print_mcp_results(response: Any, config: ChatbotUIConfig) -> None:
    exchanges = _mcp_exchanges(response, config.mcp_tool_names)
    if not exchanges:
        return

    print("\n" + _styled(f"┌─ {config.mcp_server_name} RESULTS " + "─" * 40, Style.MCP, Style.BOLD))
    for index, (name, arguments, result) in enumerate(exchanges):
        if index:
            print(_styled("│", Style.MCP))
        args_text = _one_line(", ".join(
            f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in arguments.items()
        ))
        print(_styled(_truncate(f"│ {name}({args_text})"), Style.MCP, Style.BOLD))
        if result is None:
            print(_styled("│   no result returned", Style.MCP))
            continue
        if result.exception:
            print(_styled(_truncate(f"│   error: {_one_line(result.exception)}"), Style.MCP))
            continue
        try:
            payload = json.loads(result.result or "null")
        except json.JSONDecodeError:
            print(_styled(_truncate(f"│   {_one_line(result.result)}"), Style.MCP))
            continue
        items: list[tuple[str, str]] = []
        _mcp_result_items(payload, items, set())
        if not items:
            print(_styled("│   no titled results with URLs", Style.MCP))
            continue
        for number, (title, url) in enumerate(items[:MCP_MAX_RESULTS_SHOWN], 1):
            print(_styled(_truncate(f"│   {number}. {_one_line(title)}"), Style.MCP))
            print(_styled(_truncate(f"│      {_one_line(url)}"), Style.MCP, Style.DIM))
        if len(items) > MCP_MAX_RESULTS_SHOWN:
            print(_styled(f"│   … {len(items) - MCP_MAX_RESULTS_SHOWN} more results", Style.MCP, Style.DIM))
    print(_styled("└" + "─" * 67, Style.MCP))


def _usage_value(usage: Any, key: str) -> int:
    if not isinstance(usage, dict):
        return 0
    value = usage.get(key)
    return value if isinstance(value, int) else 0


def _record_usage(response: Any, session: AgentSession) -> tuple[int, int, int, int, int, int]:
    usage = response.usage_details
    turn_input = _usage_value(usage, "input_token_count")
    turn_output = _usage_value(usage, "output_token_count")
    turn_total = _usage_value(usage, "total_token_count") or turn_input + turn_output

    session_usage = session.state.setdefault(
        USAGE_STATE_KEY,
        {"input_token_count": 0, "output_token_count": 0, "total_token_count": 0},
    )
    session_usage["input_token_count"] += turn_input
    session_usage["output_token_count"] += turn_output
    session_usage["total_token_count"] += turn_total
    return (
        turn_input,
        turn_output,
        turn_total,
        session_usage["input_token_count"],
        session_usage["output_token_count"],
        session_usage["total_token_count"],
    )


def _context_usage(session: AgentSession, max_tokens: int) -> tuple[int, float]:
    messages = session.state.get("in_memory", {}).get("messages", [])
    tokenizer = CharacterEstimatorTokenizer()
    active_tokens = sum(
        tokenizer.count_tokens(
            json.dumps(message.to_dict(), ensure_ascii=False, default=str)
        )
        for message in included_messages(messages)
    )
    return active_tokens, active_tokens / max_tokens * 100


def _todo_metrics(session: AgentSession) -> tuple[int, int, int]:
    todo_state = session.state.get("todo", {})
    items = todo_state.get("items", []) if isinstance(todo_state, dict) else []
    total = len(items) if isinstance(items, list) else 0
    completed = sum(
        1 for item in items if isinstance(item, dict) and item.get("is_complete") is True
    )
    return total, total - completed, completed


def _print_runtime_event(response: Any, session: AgentSession, config: ChatbotUIConfig) -> None:
    stored, active, excluded, reasons = _history_metrics(session)
    calls = _tool_calls(response)
    turn_input, turn_output, turn_total, session_input, session_output, session_total = (
        _record_usage(response, session)
    )
    active_tokens, context_percent = _context_usage(
        session,
        config.max_context_window_tokens,
    )
    todo_total, todo_open, todo_completed = _todo_metrics(session)

    print("\n" + _styled("┌─ AGENT HARNESS EVENT " + "─" * 45, Style.EVENT, Style.BOLD))
    print(_styled(f"│ session:    {session.session_id}", Style.EVENT))
    print(_styled(f"│ tools:      {', '.join(calls) if calls else 'none'}", Style.EVENT))
    print(_styled(f"│ mode:       {get_agent_mode(session)}", Style.EVENT))
    print(
        _styled(
            f"│ todos:      {todo_total} total | {todo_open} open | {todo_completed} completed",
            Style.EVENT,
        )
    )
    print(_styled(f"│ memory:     FileMemoryProvider(scope={config.customer_id})", Style.EVENT))
    print(_styled(f"│ history:    {stored} stored | {active} active | {excluded} compacted", Style.EVENT))
    print(
        _styled(
            f"│ tokens:     turn {turn_input:,} in | {turn_output:,} out | {turn_total:,} total",
            Style.EVENT,
        )
    )
    print(
        _styled(
            f"│ cumulative: {session_input:,} in | {session_output:,} out | {session_total:,} total",
            Style.EVENT,
        )
    )
    print(
        _styled(
            f"│ context:    ~{active_tokens:,} / {config.max_context_window_tokens:,} active-history "
            f"tokens ({context_percent:.1f}%)",
            Style.EVENT,
        )
    )
    if reasons:
        print(_styled(f"│ compaction: {', '.join(reasons)}", Style.EVENT))
    print(_styled("└" + "─" * 67, Style.EVENT))


def _print_status(session: AgentSession, config: ChatbotUIConfig) -> None:
    stored, active, excluded, reasons = _history_metrics(session)
    active_tokens, context_percent = _context_usage(
        session,
        config.max_context_window_tokens,
    )
    todo_total, todo_open, todo_completed = _todo_metrics(session)
    usage = session.state.get(USAGE_STATE_KEY, {})
    print("\n" + _styled("RUNTIME STATUS", Style.SYSTEM, Style.BOLD))
    print(f"  Session ID:          {session.session_id}")
    print(f"  Session state keys:  {', '.join(session.state) or 'none'}")
    print(f"  Agent mode:          {get_agent_mode(session)}")
    print(f"  Todos:               {todo_total} total | {todo_open} open | {todo_completed} completed")
    print("  Memory provider:     FileMemoryProvider")
    print(f"  Memory scope:        {config.customer_id}")
    print(f"  Memory path:         {config.memory_root / config.customer_id}")
    print(f"  Compaction strategy: {config.compaction_strategy}")
    print(f"  Summary target:      {config.compaction_target_messages} recent messages")
    print(f"  Trigger threshold:   +{config.compaction_threshold_messages} messages")
    print(f"  History:             {stored} stored | {active} active | {excluded} compacted")
    print(
        f"  Token usage:         {_usage_value(usage, 'input_token_count'):,} input | "
        f"{_usage_value(usage, 'output_token_count'):,} output | "
        f"{_usage_value(usage, 'total_token_count'):,} total"
    )
    print(
        f"  Active context:      ~{active_tokens:,} / {config.max_context_window_tokens:,} "
        f"history tokens ({context_percent:.1f}%)"
    )
    print(f"  Exclusion reasons:   {', '.join(reasons) or 'none'}")


async def _print_memory(memory_store: FileSystemAgentFileStore, config: ChatbotUIConfig) -> None:
    profile = await memory_store.read(f"{config.customer_id}/{config.profile_file}")
    print("\n" + _styled("DURABLE CUSTOMER MEMORY", Style.SYSTEM, Style.BOLD))
    print("  Provider: FileMemoryProvider")
    print(f"  Scope:    {config.customer_id}")
    print(f"  File:     {config.memory_root / config.customer_id / config.profile_file}")
    print("\n" + (profile or "No customer profile has been saved yet."))


async def _start_session(
    agent: Any,
    config: ChatbotUIConfig,
    previous_session: AgentSession | None = None,
) -> AgentSession:
    session = agent.create_session()
    print("\n" + _styled("=" * 68, Style.SYSTEM))
    print(_styled("NEW CHAT SESSION", Style.SYSTEM, Style.BOLD))
    if previous_session is not None:
        print(_styled(f"Previous session: {previous_session.session_id}", Style.SYSTEM))
    print(_styled(f"Current session:  {session.session_id}", Style.SYSTEM))
    print(_styled(f"Shared memory:    {config.customer_id} (persists across sessions)", Style.SYSTEM))
    print(_styled("=" * 68, Style.SYSTEM))

    response = await agent.run(
        "Begin this travel-concierge conversation. Check durable customer memory first. "
        "If a profile exists, greet the returning customer using it. Then ask exactly one concise "
        "question to begin planning their next trip.",
        session=session,
    )
    _print_message("Concierge", response.text, Style.CONCIERGE)
    _print_mcp_results(response, config)
    _print_runtime_event(response, session, config)
    return session


def _print_header() -> None:
    print("\n" + _styled("TRAVEL CONCIERGE CHATBOT", Style.SYSTEM, Style.BOLD))
    print("The chatbot asks one question at a time and saves reusable preferences.")
    print("Harness events show memory tools, session state, and compaction after every turn.")
    print("MCP result panels show each WebIQ call and the sources it returned.")
    print("\nCommands: /new  /memory  /status  /clear-memory  /exit")
    print("Suggested first-session answers:")
    print("  My name is Alex. I want to visit Mt. Rainier.")
    print("  Three days in September.")
    print("  I fly from SFO and always prefer a window seat.")
    print("  I like quiet hotels and easy hikes.")


async def run_chatbot(
    agent: Any,
    memory_store: FileSystemAgentFileStore,
    config: ChatbotUIConfig,
) -> None:
    global _use_color
    arguments = _parse_args()
    _use_color = sys.stdout.isatty() and not arguments.no_color and "NO_COLOR" not in os.environ

    if arguments.reset_memory:
        await memory_store.delete(f"{config.customer_id}/{config.profile_file}")
        print(_styled("Demo customer memory reset.", Style.SYSTEM))

    _print_header()
    session = await _start_session(agent, config)

    while True:
        try:
            user_input = input("\n" + _styled("YOU > ", Style.CUSTOMER, Style.BOLD)).strip()
        except EOFError:
            _print_message("Concierge", "Goodbye.", Style.CONCIERGE)
            break

        if not user_input:
            continue
        if user_input == "/exit":
            _print_message("Concierge", "Goodbye.", Style.CONCIERGE)
            break
        if user_input == "/new":
            session = await _start_session(agent, config, previous_session=session)
            continue
        if user_input == "/memory":
            await _print_memory(memory_store, config)
            continue
        if user_input == "/status":
            _print_status(session, config)
            continue
        if user_input == "/clear-memory":
            await memory_store.delete(f"{config.customer_id}/{config.profile_file}")
            print(_styled("Durable customer profile cleared. Start a new session with /new.", Style.SYSTEM))
            continue

        _print_message("You", user_input, Style.CUSTOMER)
        response = await agent.run(user_input, session=session)
        _print_message("Concierge", response.text, Style.CONCIERGE)
        _print_mcp_results(response, config)
        _print_runtime_event(response, session, config)

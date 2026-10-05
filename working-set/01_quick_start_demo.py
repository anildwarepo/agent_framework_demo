"""Streaming agent with user-scoped sessions, file-backed history, and local OpenTelemetry."""

import argparse
import asyncio
import hashlib
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from agent_framework import Agent, FileHistoryProvider
from agent_framework.observability import enable_instrumentation
from opentelemetry import trace
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import ConsoleLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import StatusCode

from demo_cli import run_cli
from model_client import create_model_client

LOGGER = logging.getLogger("quick_start_demo")
AGENT_INSTRUCTIONS = (
    "You are a concise, helpful recovery-readiness assistant. "   
)
DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent / "conversation-history"
DEFAULT_TELEMETRY_DIR = Path(__file__).resolve().parent / "otel-demo-output"
EXIT_COMMANDS = {"exit", "quit"}


@contextmanager
def local_telemetry(output_dir: Path):
    """Export Agent Framework traces and this demo's logs to local JSONL files."""
    output_dir.mkdir(parents=True, exist_ok=False)
    resource = Resource.create({"service.name": "agent-framework-quick-start"})
    with (
        (output_dir / "traces.jsonl").open("w", encoding="utf-8") as traces_file,
        (output_dir / "logs.jsonl").open("w", encoding="utf-8") as logs_file,
    ):
        traces = TracerProvider(resource=resource)
        traces.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter(
            out=traces_file, formatter=lambda span: span.to_json(indent=None) + "\n",
        )))
        logs = LoggerProvider(resource=resource)
        logs.add_log_record_processor(SimpleLogRecordProcessor(ConsoleLogRecordExporter(
            out=logs_file, formatter=lambda record: record.to_json(indent=None) + "\n",
        )))
        handler = LoggingHandler(level=logging.INFO, logger_provider=logs)
        old_level, old_propagate = LOGGER.level, LOGGER.propagate
        LOGGER.setLevel(logging.INFO)
        LOGGER.propagate = False
        LOGGER.addHandler(handler)
        trace.set_tracer_provider(traces)
        enable_instrumentation(enable_sensitive_data=True)
        try:
            yield
        finally:
            try:
                if not logs.force_flush() or not traces.force_flush():
                    raise RuntimeError("OpenTelemetry did not flush all local records.")
            finally:
                LOGGER.removeHandler(handler)
                LOGGER.setLevel(old_level)
                LOGGER.propagate = old_propagate
                handler.close()
                logs.shutdown()
                traces.shutdown()


def user_session_id(user_id: str, session_id: str) -> str:
    """Map an exact user/conversation pair to a stable, filesystem-safe session ID."""
    for name, value in (("user_id", user_id), ("session_id", session_id)):
        if not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError(f"{name} must be non-empty without outer whitespace or control characters.")
    # Structured encoding avoids delimiter collisions; hashing also avoids Windows case collisions.
    identity = json.dumps([user_id, session_id], ensure_ascii=True, separators=(",", ":"))
    return "user-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


async def chat(
    initial_prompt: str | None = None,
    *,
    user_id: str,
    session_id: str = "demo",
    storage_dir: Path = DEFAULT_STORAGE_DIR,
    once: bool = False,
) -> None:
    framework_session_id = user_session_id(user_id, session_id)
    client = create_model_client()
    history = FileHistoryProvider(storage_path=storage_dir)
    previous_messages = await history.get_messages(framework_session_id)

    agent = Agent(
        client=client,
        name="PersistentRecoveryAssistant",
        instructions=AGENT_INSTRUCTIONS,
        context_providers=[history],
    )
    session = agent.create_session(session_id=framework_session_id)
    prompt = initial_prompt

    print(f"[history] FileHistoryProvider | user: {user_id} | conversation: {session_id}")
    print(f"[session] Agent Framework session ID: {session.session_id}")
    print(f"[history] Storage: {storage_dir.resolve()}")
    print(f"[history] File: {storage_dir.resolve() / (framework_session_id + '.jsonl')}")
    print(f"[history] Found {len(previous_messages)} stored messages.")
    print("[history] Plaintext local demo history; do not enter sensitive data.")
    print("Type 'exit' or 'quit' to stop. Reuse --user-id and --session to resume.")
    LOGGER.info("History loaded", extra={
        "demo.event": "history.loaded",
        "demo.session_id": framework_session_id,
        "demo.stored_messages": len(previous_messages),
    })
    tracer = trace.get_tracer("quick_start_demo")

    while True:
        if prompt is None:
            try:
                prompt = input("\nYou: ").strip()
            except EOFError:
                print("\nGoodbye!")
                return

        if prompt.lower() in EXIT_COMMANDS:
            print("Goodbye!")
            return
        if not prompt.strip():
            if once:
                raise ValueError("A non-empty prompt is required with --once.")
            prompt = None
            continue

        with tracer.start_as_current_span(
            "demo.turn", record_exception=False, set_status_on_exception=False,
        ) as span:
            span.set_attribute("demo.session_id", framework_session_id)
            print(f"[otel] Trace ID: {span.get_span_context().trace_id:032x}")
            LOGGER.info("Agent turn started", extra={"demo.event": "turn.started"})
            try:
                print("\nAssistant: ", end="", flush=True)
                response_stream = agent.run(prompt, session=session, stream=True)
                async for update in response_stream:
                    if update.text:
                        print(update.text, end="", flush=True)
                await response_stream.get_final_response()
            except asyncio.CancelledError:
                span.set_attribute("demo.cancelled", True)
                LOGGER.info("Agent turn cancelled", extra={"demo.event": "turn.cancelled"})
                raise
            except Exception as error:
                span.set_status(StatusCode.ERROR, type(error).__name__)
                LOGGER.error("Agent turn failed", extra={
                    "demo.event": "turn.failed", "error.type": type(error).__name__,
                })
                raise
            else:
                LOGGER.info("Agent turn completed", extra={"demo.event": "turn.completed"})
        print("\n[history] Turn completed; conversation saved by FileHistoryProvider.")
        if once:
            return
        prompt = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resume user-scoped Agent Framework conversations from local history."
    )
    parser.add_argument("prompt", nargs="?", help="Optional first chat message.")
    parser.add_argument(
        "--user-id", required=True,
        help="Stable demo user ID; a hosted app must use authenticated identity instead.",
    )
    parser.add_argument(
        "--session", default="demo", help="Stable conversation ID to resume."
    )
    parser.add_argument(
        "--storage-dir", type=Path, default=DEFAULT_STORAGE_DIR,
        help="Trusted local history directory (default: beside this script).",
    )
    parser.add_argument("--once", action="store_true", help="Run one prompt, then exit.")
    parser.add_argument(
        "--telemetry-dir", type=Path, default=DEFAULT_TELEMETRY_DIR,
        help="Parent directory for a new run's traces.jsonl and logs.jsonl.",
    )
    args = parser.parse_args()
    if args.once and (args.prompt is None or not args.prompt.strip()):
        parser.error("--once requires a non-empty prompt.")
    try:
        user_session_id(args.user_id, args.session)
    except ValueError as exc:
        parser.error(str(exc))
    telemetry_dir = args.telemetry_dir / uuid4().hex
    print(f"[otel] Local telemetry: {telemetry_dir}")
    print("[otel] Prompts and responses are captured in telemetry; use synthetic data only.")
    try:
        with local_telemetry(telemetry_dir):
            asyncio.run(
                chat(
                    args.prompt, user_id=args.user_id, session_id=args.session,
                    storage_dir=args.storage_dir, once=args.once,
                )
            )
    finally:
        print(f"\n[otel] Telemetry directory: {telemetry_dir}", flush=True)


if __name__ == "__main__":
    run_cli(main)

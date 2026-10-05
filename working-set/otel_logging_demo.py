"""Show correlated OpenTelemetry logs and Agent Framework traces, exported locally."""

import argparse
import asyncio
import logging
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from agent_framework import Agent, tool
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

LOGGER = logging.getLogger("otel_logging_demo")
DEFAULT_PROMPT = "Check the fictional recovery policy and explain its RPO target in one sentence."


@tool
def get_recovery_policy() -> str:
    """Return the synthetic recovery policy used by this demo, not live operational data."""
    LOGGER.info("Reading synthetic recovery policy", extra={"demo.event": "policy.read"})
    return "Fictional policy: ClaimsPortal has an RPO target of 15 minutes."


@contextmanager
def local_telemetry(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=False)
    resource = Resource.create({"service.name": "agent-framework-otel-demo"})
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
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("[OTel demo] %(message)s"))
        old_level, old_propagate = LOGGER.level, LOGGER.propagate
        LOGGER.setLevel(logging.INFO)
        LOGGER.propagate = False
        LOGGER.addHandler(handler)
        LOGGER.addHandler(console)
        trace.set_tracer_provider(traces)
        enable_instrumentation(enable_sensitive_data=False)
        try:
            yield
        finally:
            try:
                if not logs.force_flush() or not traces.force_flush():
                    raise RuntimeError("OpenTelemetry did not flush all local records.")
            finally:
                LOGGER.removeHandler(handler)
                LOGGER.removeHandler(console)
                LOGGER.setLevel(old_level)
                LOGGER.propagate = old_propagate
                handler.close()
                console.close()
                logs.shutdown()
                traces.shutdown()


async def run_demo(prompt: str) -> None:
    client = create_model_client()
    try:
        agent = Agent(
            client=client,
            name="RecoveryPolicyAssistant",
            instructions=(
                "Call get_recovery_policy before answering. Use the returned fictional "
                "policy, state that it is synthetic, and answer briefly."
            ),
            tools=[get_recovery_policy],
        )
        session = agent.create_session()
        tracer = trace.get_tracer("otel_logging_demo")
        with tracer.start_as_current_span(
            "demo.turn", record_exception=False, set_status_on_exception=False,
        ) as span:
            print(f"Trace ID: {span.get_span_context().trace_id:032x}", flush=True)
            LOGGER.info("Agent turn started", extra={"demo.event": "turn.started"})
            try:
                print("\nAssistant: ", end="", flush=True)
                stream = agent.run(prompt, session=session, stream=True)
                async for update in stream:
                    if update.text:
                        print(update.text, end="", flush=True)
                await stream.get_final_response()
                print()
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
    finally:
        await client.client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path(__file__).resolve().parent / "otel-demo-output",
        help="Parent directory for a new run's traces.jsonl and logs.jsonl.",
    )
    args = parser.parse_args()
    if not args.prompt.strip():
        parser.error("The prompt must not be empty.")
    output_dir = args.output_dir / uuid4().hex
    print(f"Local telemetry: {output_dir}")
    print("Prompt/response telemetry capture is disabled. Console answers are still visible.")
    try:
        with local_telemetry(output_dir):
            asyncio.run(run_demo(args.prompt))
    finally:
        print(f"\nTelemetry directory: {output_dir}", flush=True)


if __name__ == "__main__":
    run_cli(main)

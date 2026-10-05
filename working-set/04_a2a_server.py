"""Host a Microsoft Agent Framework agent as an A2A server.

Run:  python 04_a2a_server.py
Then call it from another terminal with a2a_client.py.
"""

import argparse
from pathlib import Path

import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from agent_framework import Agent, FileHistoryProvider
from agent_framework.a2a import A2AExecutor
from demo_cli import run_cli
from model_client import create_model_client
from starlette.applications import Starlette

AGENT_INSTRUCTIONS = (
    "You are a concise recovery-readiness advisor. Answer directly, use the "
    "conversation history for continuity, and do not claim to have checked live systems."
)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9999
DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent / "a2a-history"


def build_agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="RecoveryAdvisor",
        description="Answers recovery-readiness questions; hosted with Microsoft Agent Framework.",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[AgentInterface(url=base_url, protocol_binding="JSONRPC")],
        skills=[
            AgentSkill(
                id="recovery_advice",
                name="Recovery advice",
                description="Explains backup, RPO/RTO, and clean-recovery concepts.",
                tags=["backup", "recovery", "ransomware"],
                examples=["What is the difference between RPO and RTO?"],
            )
        ],
    )


def create_app(base_url: str, storage_dir: Path) -> Starlette:
    card = build_agent_card(base_url)
    # A2AExecutor creates a fresh session per request with session_id = A2A context_id,
    # so history must live in a provider keyed by session_id, not in session state.
    agent = Agent(
        client=create_model_client(),
        name=card.name,
        instructions=AGENT_INSTRUCTIONS,
        context_providers=[FileHistoryProvider(storage_path=storage_dir)],
    )
    handler = DefaultRequestHandler(
        agent_executor=A2AExecutor(agent, stream=True),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    return Starlette(
        routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Host a Microsoft Agent Framework agent as an A2A server."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--storage-dir", type=Path, default=DEFAULT_STORAGE_DIR,
        help="Trusted local history directory (default: beside this script).",
    )
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}/"
    app = create_app(base_url, args.storage_dir)
    print(f"[a2a] Serving RecoveryAdvisor at {base_url} (JSON-RPC)")
    print(f"[a2a] Agent card: {base_url}.well-known/agent-card.json")
    print(f"[history] FileHistoryProvider keyed by A2A context_id: {args.storage_dir}")
    print("[a2a] Local demo only: no authentication; do not enter sensitive data.", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    run_cli(main)

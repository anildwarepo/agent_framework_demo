"""Discover a remote A2A agent from its agent card and chat with it.

Start 04_a2a_server.py first, then run:  python a2a_client.py
Works with any A2A-compatible agent; it does not import the server code.
"""

import argparse
import asyncio

import httpx
from a2a.client import A2ACardResolver
from agent_framework.a2a import A2AAgent
from demo_cli import run_cli

DEFAULT_URL = "http://127.0.0.1:9999/"
EXIT_COMMANDS = {"exit", "quit"}


async def chat(url: str, initial_prompt: str | None = None) -> None:
    async with httpx.AsyncClient() as http_client:
        card = await A2ACardResolver(http_client, url).get_agent_card()
    print(f"[discovery] {card.name} v{card.version}: {card.description}")
    for skill in card.skills:
        print(f"[discovery] skill: {skill.name} - {skill.description}")
    print(f"[discovery] streaming: {card.capabilities.streaming}")

    async with A2AAgent(agent_card=card, url=url) as remote:
        session = remote.create_session()
        prompt = initial_prompt
        print("Type 'exit' or 'quit' to stop.")
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
            if not prompt:
                prompt = None
                continue

            print(f"\n{card.name} (via A2A): ", end="", flush=True)
            response_stream = remote.run(prompt, session=session, stream=True)
            async for update in response_stream:
                if update.text:
                    print(update.text, end="", flush=True)
            await response_stream.get_final_response()
            service_session = session.service_session_id or {}
            print(f"\n[a2a] context_id: {service_session.get('context_id')}")
            prompt = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover a remote A2A agent and chat with it through A2AAgent."
    )
    parser.add_argument("prompt", nargs="?", help="Optional first chat message.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Base URL of the A2A agent.")
    args = parser.parse_args()
    asyncio.run(chat(args.url, args.prompt))


if __name__ == "__main__":
    run_cli(main)

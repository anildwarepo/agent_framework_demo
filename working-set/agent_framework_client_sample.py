"""Minimal model-endpoint sample using only an Agent Framework chat client."""

import argparse
import asyncio

from agent_framework import Message
from demo_cli import run_cli
from model_client import create_model_client

INSTRUCTIONS = "You are a concise, helpful assistant."
EXIT_COMMANDS = {"exit", "quit"}


async def chat(initial_prompt: str | None = None) -> None:
    client = create_model_client()
    messages = [Message(role="system", contents=[INSTRUCTIONS])]
    prompt = initial_prompt

    print("Agent Framework client chat started. Type 'exit' or 'quit' to stop.")
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

        messages.append(Message(role="user", contents=[prompt]))
        print("\nAssistant: ", end="", flush=True)
        response_stream = client.get_response(messages, stream=True)
        async for update in response_stream:
            if update.text:
                print(update.text, end="", flush=True)
        response = await response_stream.get_final_response()
        print()
        messages.extend(response.messages)
        prompt = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Call an OpenAI-compatible model endpoint with an Agent Framework client."
    )
    parser.add_argument("prompt", nargs="?", help="Optional first chat message.")
    args = parser.parse_args()
    asyncio.run(chat(args.prompt))


if __name__ == "__main__":
    run_cli(main)

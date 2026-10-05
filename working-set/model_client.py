"""Shared Agent Framework client for an explicit OpenAI-compatible model endpoint."""

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

from agent_framework.openai import OpenAIChatCompletionClient
from dotenv import load_dotenv


def _required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise RuntimeError(
            f"{name} is required. Configure the model endpoint in the environment "
            "or .env file; see MODEL_ENDPOINT_SETUP.md."
        )
    return value.strip()


def _entra_token_provider() -> Callable[[], Awaitable[str]]:
    from azure.identity.aio import AzureCliCredential, get_bearer_token_provider

    return get_bearer_token_provider(
        AzureCliCredential(process_timeout=60), "https://ai.azure.com/.default"
    )


def create_model_client(*, include_detailed_errors: bool = False) -> OpenAIChatCompletionClient:
    load_dotenv(Path(__file__).with_name(".env"))
    base_url = _required_setting("OPENAI_BASE_URL")
    model = _required_setting("OPENAI_MODEL")
    auth_mode = os.getenv("OPENAI_AUTH_MODE", "api_key").strip().lower()
    if auth_mode not in {"api_key", "entra"}:
        raise ValueError("OPENAI_AUTH_MODE must be 'api_key' or 'entra'.")
    try:
        endpoint = urlsplit(base_url)
        valid = (
            endpoint.scheme in {"https", "http"}
            and bool(endpoint.hostname)
            and endpoint.username is None
            and endpoint.password is None
            and not endpoint.query
            and not endpoint.fragment
            and not any(character.isspace() for character in base_url)
        )
        endpoint.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            "OPENAI_BASE_URL must be an HTTP(S) API base URL without embedded "
            "credentials, query parameters, or fragments."
        )
    if endpoint.path.rstrip("/").endswith(("/chat/completions", "/responses")):
        raise ValueError(
            "OPENAI_BASE_URL must be the API base (for example https://api.openai.com/v1), "
            "not a chat/completions or responses operation URL."
        )
    if auth_mode == "entra" and endpoint.scheme != "https":
        raise ValueError("OPENAI_BASE_URL must use HTTPS for Entra authentication.")
    api_key = _entra_token_provider() if auth_mode == "entra" else _required_setting("OPENAI_API_KEY")
    return OpenAIChatCompletionClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        function_invocation_configuration={"include_detailed_errors": include_detailed_errors},
    )

"""Minimal single-agent sample using Microsoft Agent Framework."""

import argparse
import asyncio
from typing import Annotated

import httpx
from agent_framework import Agent, tool
from demo_cli import run_cli
from model_client import create_model_client

AGENT_INSTRUCTIONS = (
    "You are a concise, helpful assistant. Answer the user's request directly. "
    "Use the get_weather tool whenever the user asks about weather conditions for a place."
)
EXIT_COMMANDS = {"exit", "quit"}
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow", 77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}

client = create_model_client()


@tool(approval_mode="never_require")
async def get_weather(
    place: Annotated[str, "City or place name, e.g. 'Seattle' or 'Paris, France'."],
) -> str:
    """Get the current weather for a place using the Open-Meteo API."""
    name = place.split(",")[0].strip()
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            geo = await http.get(GEOCODING_URL, params={"name": name, "count": 1})
            geo.raise_for_status()
            results = geo.json().get("results")
            if not results:
                return f"Could not find a location named '{place}'."
            loc = results[0]

            forecast = await http.get(FORECAST_URL, params={
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                           "wind_speed_10m,weather_code",
                "timezone": "auto",
            })
            forecast.raise_for_status()
            current = forecast.json()["current"]
    except httpx.HTTPError as exc:
        return f"Weather service request failed: {exc}"

    location = ", ".join(p for p in (loc.get("name"), loc.get("admin1"), loc.get("country")) if p)
    conditions = WEATHER_CODES.get(current.get("weather_code"), "unknown conditions")
    return (
        f"Current weather in {location} (as of {current['time']} local time): {conditions}, "
        f"{current['temperature_2m']}°C (feels like {current['apparent_temperature']}°C), "
        f"humidity {current['relative_humidity_2m']}%, wind {current['wind_speed_10m']} km/h."
    )


async def chat(initial_prompt: str | None = None) -> None:
    
    agent = Agent(
        client=client,
        name="SingleAgentSample",
        instructions=AGENT_INSTRUCTIONS,
        tools=[get_weather],
    )
    session = agent.create_session()
    prompt = initial_prompt

    print("Agent Framework chat started. Type 'exit' or 'quit' to stop.")
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

        print("\nAssistant: ", end="", flush=True)
        response_stream = agent.run(prompt, session=session, stream=True)
        async for update in response_stream:
            if update.text:
                print(update.text, end="", flush=True)
        await response_stream.get_final_response()
        print()
        prompt = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a minimal Microsoft Agent Framework agent."
    )
    parser.add_argument("prompt", nargs="?", help="Optional first chat message.")
    args = parser.parse_args()
    asyncio.run(chat(args.prompt))


if __name__ == "__main__":
    run_cli(main)

# Get started with Microsoft Agent Framework

[Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/) is an open-source framework for building AI agents and multi-agent workflows in Python and .NET. These four short demos take you from a single agent to agents that work together, remember users, use MCP tools, and talk to other agents.

| Demo | Key capabilities |
| --- | --- |
| [01 Quick start](#01-your-first-agent) | Model client, agent, per-user conversation history, OpenTelemetry tracing |
| [02 Concurrent workflow](#02-agents-working-in-parallel) | Multi-agent orchestration, MCP tools, combining results |
| [03 Agent harness](#03-a-long-running-assistant-with-memory) | Planning, to-dos, durable memory, context compaction, web search through MCP |
| [04 Agent-to-agent (A2A)](#04-call-an-agent-over-a2a) | Hosting an agent as an A2A service and calling it from a client |

## Before you start

You need:

- Python 3.13
- A model endpoint that supports the OpenAI Chat Completions API, with streaming and tool calling. For example, OpenAI, Azure OpenAI in Microsoft Foundry, or a local server such as vLLM or Ollama.
- A WebIQ API key, for demos 02 and 03 (web search through MCP).

## Set up

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example working-set\.env
```

Open `working-set\.env` and fill in your settings:

| Setting | Description |
| --- | --- |
| `OPENAI_BASE_URL` | API base URL, for example `https://api.openai.com/v1` |
| `OPENAI_MODEL` | Model or deployment name |
| `OPENAI_API_KEY` | API key for the endpoint |
| `WEBIQ_API_KEY` | Needed for demos 02 and 03 |

To use Microsoft Entra ID with an Azure endpoint instead of an API key, set `OPENAI_AUTH_MODE=entra`, leave `OPENAI_API_KEY` empty, and sign in with `az login`.

The demos run from the `working-set` folder:

```powershell
cd working-set
```

## 01: Your first agent

```powershell
python .\01_quick_start_demo.py --user-id user1 --session session1
```

Tell the agent who you are:

```text
I am UserA
```

Type `exit` to end the session. Then run the same command again and ask:

```text
who am I?
```

The agent answers that you're UserA. The conversation was saved after each turn and loaded again when the script restarted.

Now run the command with a different user and the same session name:

```powershell
python .\01_quick_start_demo.py --user-id user2 --session session1
```

Ask `who am I?` again. This time the agent doesn't know, because each user has their own history.

What it shows:

- **Model client.** The same code works with any OpenAI-compatible model. Change `OPENAI_BASE_URL` and `OPENAI_MODEL` to switch between a hosted and a local model.
- **Agent.** Instructions are defined once, and `agent.run()` streams the response.
- **Per-user conversation history.** `FileHistoryProvider` saves each conversation, so it survives a restart and stays separate for each user.
- **OpenTelemetry.** Each turn prints a trace ID. Open `otel-demo-output\<run>\traces.jsonl` to see the agent run and the model call, including the prompt and response, under that trace.

## 02: Agents working in parallel

```powershell
python .\02_concurrent_workflow_demo.py
```

Press Enter when prompted to move to the next stage.

A fictional healthcare company is hit by ransomware. Three specialist agents investigate at the same time, then an incident commander agent combines their findings into one recovery plan:

| Agent | Tool |
| --- | --- |
| Threat intelligence | Current public guidance, through the WebIQ MCP server |
| Policy analyst | Local recovery policy and incident documents, through a local MCP server |
| Recovery posture analyst | Backup and recovery data, through the same local MCP server |

What it shows:

- **Concurrent orchestration** with `ConcurrentBuilder`: fan out to several agents, then fan in to one result.
- **MCP tools** over both HTTP (remote) and stdio (local).
- Each agent's output is streamed in its own color, and every MCP call is shown.

Try your own scenario with `--scenario "..."`.

## 03: A long-running assistant with memory

```powershell
python .\03_travel_concierge_agent_harness_webiq_mcp.py
```

Try:

```text
I am travelling to Denver and my travel budget is $2k, I live in SEA, find best  flight options
```

Then type `/new` to start a new chat session and ask:

```text
what is my travel budget?
```

What it shows:

- **Agent harness** (`create_harness_agent`): a ready-made agent with planning modes, a to-do list, and context compaction for long conversations.
- **Durable memory.** Lasting preferences, such as your home airport and budget, are saved to a customer profile and remembered in new sessions. One-time trip details are not saved.
- **Web search through MCP.** After each answer, a results panel shows the WebIQ searches the agent made and the sources it used.
- **Harness events.** A panel shows the tools called, the current mode, to-dos, memory, compaction, and token usage.

Chat commands: `/new`, `/memory`, `/status`, `/clear-memory`, `/exit`. Use `--reset-memory` to start with an empty profile.

## 04: Call an agent over A2A

The [Agent-to-Agent (A2A) protocol](https://a2a-protocol.org/) lets agents built with different frameworks discover and call each other.

Start the server in one terminal:

```powershell
python .\04_a2a_server.py
```

In a second terminal (with the virtual environment activated, in `working-set`), start the client:

```powershell
python .\a2a_client.py
```

Ask:

```text
what is the readiness for 0 RPO?
```

What it shows:

- **Hosting.** An ordinary agent is served over A2A with `A2AExecutor`, and publishes an agent card at `/.well-known/agent-card.json`.
- **Discovery.** The client reads the agent card and calls the agent knowing only its URL.
- **Multi-turn conversations.** Each A2A conversation (`context_id`) keeps its own history on the server.

This demo has no authentication. In production, add authentication between agents.

## More samples

| Script | What it shows |
| --- | --- |
| [agent_framework_client_sample.py](working-set/agent_framework_client_sample.py) | Calling a model directly, without an agent |
| [single_agent_sample.py](working-set/single_agent_sample.py) | An agent with a simple tool (current weather for a place) |
| [otel_logging_demo.py](working-set/otel_logging_demo.py) | OpenTelemetry traces and logs for an agent that calls a tool |

## Start fresh

The demos write their state to files in `working-set`. Delete these folders to reset:

- `conversation-history/`: demo 01 conversations
- `otel-demo-output/`: demo 01 traces and logs
- `agent-file-memory/`: demo 03 customer profile
- `a2a-history/`: demo 04 conversations

To recreate the fictional data used by demo 02, run `python .\setup_demo.py`.

These files are stored as plain text, and the traces include prompts and responses. Don't enter real or sensitive data.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `OPENAI_BASE_URL is required` | Create `working-set\.env` (see [Set up](#set-up)) and run the demos from `working-set` |
| `WEBIQ_API_KEY is required` | Add your WebIQ key to `working-set\.env` |
| `UnicodeEncodeError` | Run `$env:PYTHONIOENCODING = "utf-8"` first |
| The A2A client can't connect | Start `04_a2a_server.py` first. It uses port 9999; change it with `--port` on the server and `--url` on the client. |

## Learn more

- [Agent Framework documentation](https://learn.microsoft.com/en-us/agent-framework/)
- [Agent Framework on GitHub](https://github.com/microsoft/agent-framework)
- [Workflows and orchestration patterns](https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/)
- [Observability](https://learn.microsoft.com/en-us/agent-framework/agents/observability)

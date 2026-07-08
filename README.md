# mcp-agent

Build effective agents with [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) using simple, composable patterns.

**Version:** 0.2.6 · **Python:** ≥ 3.10 · **License:** Apache 2.0

---

## Table of Contents

1. [Project Architecture](#1-project-architecture)
2. [System Workflow](#2-system-workflow)
3. [How the System Works](#3-how-the-system-works)
4. [Workflow Patterns](#4-workflow-patterns)
5. [Tools & Technologies](#5-tools--technologies)
6. [Constraints & Design Decisions](#6-constraints--design-decisions)
7. [Repository Structure](#7-repository-structure)

---

## 1. Project Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCPApp (app.py)                       │
│  - Application lifecycle & global context               │
│  - Workflow / Task registration decorators              │
│  - Agent factory & secrets management                   │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │  Agent   │  │  Agent   │  │  Agent   │  ← Named agents with
  │  (A)     │  │  (B)     │  │  (C)     │    scoped MCP server
  └────┬─────┘  └────┬─────┘  └────┬─────┘    connections
       │              │              │
       └──────────────┼──────────────┘
                      │
              ┌───────▼────────┐
              │  MCP Aggregator │  ← Namespace + fan-out
              │  (per Agent)   │    tool/resource/prompt
              └───────┬────────┘    calls
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │filesystem│  │  fetch   │  │ custom   │  ← External MCP
  │  server  │  │  server  │  │  server  │    Servers (stdio /
  └──────────┘  └──────────┘  └──────────┘    SSE / HTTP / WS)

       ▲
       │  AugmentedLLM wraps each agent with multi-provider LLM support
       │
  ┌────┴───────────────────────────────┐
  │         AugmentedLLM Layer         │
  │  OpenAI / Anthropic / Bedrock /    │
  │  Google / Azure / Ollama /         │
  │  LM Studio                         │
  └───────────────────────────────────┘
       │
  ┌────┴──────────────────┐
  │   Execution Engine    │
  │  asyncio  │  Temporal │  ← Swap without changing agent code
  └───────────────────────┘
```

### Key Layers

| Layer | Responsibility | Key File(s) |
|---|---|---|
| **MCPApp** | App lifecycle, context, workflow/task registration | `src/mcp_agent/app.py` |
| **Agent** | Tool aggregation, LLM attachment, human-input gate | `src/mcp_agent/agents/agent.py` |
| **MCP Aggregator** | Multiplexes N MCP servers into a single tool namespace | `src/mcp_agent/mcp/mcp_aggregator.py` |
| **AugmentedLLM** | Provider-agnostic LLM with tool-calling loop, memory, streaming | `src/mcp_agent/workflows/llm/augmented_llm.py` |
| **Workflows** | Orchestrator, Parallel, Router, Swarm, Evaluator-Optimizer | `src/mcp_agent/workflows/` |
| **Executor** | asyncio or Temporal; controls durability, signals, retries | `src/mcp_agent/executor/` |
| **Config** | Pydantic-validated YAML settings + secret resolution | `src/mcp_agent/config.py` |
| **CLI** | `mcp-agent` and `mcp-cloud` entry points | `src/mcp_agent/cli/` |
| **Tracing** | OpenTelemetry spans, token tracking, OTLP export | `src/mcp_agent/tracing/` |

---

## 2. System Workflow

```
User Code
   │
   ▼
MCPApp.run()              ← sets up logging, tracing, secrets, executor
   │
   ▼
Agent.__aenter__()        ← connects to MCP servers, registers tools
   │
   ├─► MCPConnectionManager  ← manages stdio/SSE/HTTP/WS server processes
   │
   └─► MCP Aggregator        ← merges tool lists from all servers (namespaced)
            │
            ▼
       AugmentedLLM          ← provider-specific subclass (OpenAI, Anthropic …)
            │
            │  generate_str() / generate() / generate_stream()
            │
            ▼
       [Tool-calling loop]
            │
            ├─ LLM API call  →  model response
            │
            └─ Tool call?  →  MCP Aggregator.call_tool()  →  MCP Server
                                        │
                                        └─ result injected back into conversation
            │
            ▼
       Final text / structured output
            │
            ▼
     Caller receives result
```

### Execution Flow Detail

1. **Initialization** – `MCPApp` reads `mcp_agent.config.yaml` and `mcp_agent.secrets.yaml`, initialises the chosen executor (`asyncio` or `Temporal`), sets up an OpenTelemetry tracer, and creates a `Context` singleton.

2. **Agent startup** – `async with agent:` launches each listed MCP server subprocess (or connects to remote SSE/HTTP/WebSocket endpoints), runs a capability handshake, and caches the tool list in `MCPAggregator`.

3. **LLM attachment** – `await agent.attach_llm(SomeLLM)` binds a provider implementation; the LLM receives the merged tool schema from the aggregator.

4. **Generation** – Calling `llm.generate_str(prompt)` kicks off the tool-calling loop: model is called → if it emits tool-use blocks they are dispatched to the correct MCP server → results are inserted as tool-result messages → loop continues until the model stops emitting tool calls → final text is returned.

5. **Workflow orchestration** – Higher-level patterns (`Orchestrator`, `ParallelLLM`, `Router`, `Swarm`) compose agents by wrapping this loop or delegating sub-tasks to other agent instances.

6. **Shutdown** – Context managers close all server connections, flush telemetry, and optionally persist logs.

---

## 3. How the System Works

### MCPApp — The Entry Point

`MCPApp` is the singleton application object. It:
- Registers `@app.workflow` and `@app.task` decorators so Temporal or asyncio can discover them.
- Exposes `app.run()` as an async context manager that wires up global context and executes shutdown hooks.
- Hosts an optional FastMCP server so the whole agent application is itself consumable as an MCP server (`agent-as-server` pattern).

### Agent — The Core Unit

Each `Agent`:
- Holds a list of **server names** that identify which MCP servers it can access.
- Manages its own `MCPAggregator`, which prefixes tool names with the server name to avoid collisions (e.g., `filesystem_read_file`).
- Proxies `list_tools`, `call_tool`, `list_resources`, `read_resource`, `list_prompts`, and `get_prompt` to whichever backend server owns each capability.
- Optionally exposes a `__human_input__` tool so the LLM can pause and ask the user a question.

### AugmentedLLM — The Intelligence Layer

`AugmentedLLM` is an abstract generic class parameterized by provider message types. Concrete subclasses (`OpenAIAugmentedLLM`, `AnthropicAugmentedLLM`, etc.) implement:
- `generate()` — full message-list in, message-list out, handles the tool loop.
- `generate_str()` — convenience wrapper returning a plain string.
- `generate_stream()` — async generator of `StreamEvent` objects.
- `structured()` — Pydantic-validated structured output.

All subclasses share a `Memory` object (in-context conversation history) and a `RequestParams` model for temperature, `max_tokens`, stop sequences, and tool-choice overrides.

### MCP Aggregator — The Tool Bus

`MCPAggregator` is the glue between an `Agent` and multiple MCP servers. It:
- Starts and caches `MCPAgentClientSession` connections.
- Namespaces tool names as `<server_name><sep><tool_name>` to prevent clashes.
- Routes `call_tool(namespaced_name, args)` to the correct backend.
- Supports server-side sampling so an MCP server can call back into the LLM.

### Executor — Asyncio vs. Temporal

The executor abstraction lets you swap durability engines without changing agent code:

| Feature | asyncio | Temporal |
|---|---|---|
| Durability | None — in-process only | Full — survives restarts |
| Long-running | Limited by process lifetime | Unlimited |
| Signals | In-memory queues | Temporal signals |
| Setup | Zero — default | Requires Temporal server |

`@app.workflow` / `@app.task` decorators are rewritten by the executor so the same code runs in either mode.

---

## 4. Workflow Patterns

All patterns are implemented in `src/mcp_agent/workflows/` and compose via `AugmentedLLM`.

### Orchestrator

An LLM plans and delegates tasks to a pool of specialized worker agents. Supports both iterative planning (next step only) and full up-front planning.

```
Orchestrator LLM
  ├── Plan → [task_a, task_b, task_c]
  ├── Dispatch task_a → Agent A → result_a
  ├── Dispatch task_b → Agent B → result_b  (can be parallel)
  └── Synthesize(result_a, result_b, result_c) → final answer
```

### Parallel (Fan-out / Fan-in)

Distributes a prompt to multiple agents simultaneously, then aggregates responses. Useful for independent sections or voting/consensus.

```
Input
  ├── Agent A (section 1)  ┐
  ├── Agent B (section 2)  ├── Fan-in (aggregator LLM)  → Output
  └── Agent C (section 3)  ┘
```

### Router

Classifies the input and routes it to the single best-fit agent or function. Two routing strategies are available:

- **LLM Router** – uses a reasoning LLM to classify intent.
- **Embedding Router** – uses cosine similarity over vector embeddings (OpenAI or Cohere).

### Swarm

Agents can hand off to each other mid-conversation (inspired by OpenAI Swarm). An agent can call a `transfer_to_<agent>` tool to cede control, enabling branching multi-agent conversations.

### Evaluator–Optimizer

A generation agent produces output; an evaluator agent scores it. If the score is below threshold the output is refined; loop continues until acceptable or max iterations reached.

### Intent Classifier

Standalone component that classifies free-text input into a predefined category set. Backed by either an LLM or embeddings.

---

## 5. Tools & Technologies

### Core Runtime

| Technology | Role |
|---|---|
| **Python 3.10+** | Runtime language |
| **[uv](https://docs.astral.sh/uv/)** | Fast Python package and project manager |
| **asyncio** | Default concurrency model |
| **[Temporal](https://temporal.io/)** | Optional durable workflow engine (`mcp-agent[temporal]`) |

### MCP Protocol

| Technology | Role |
|---|---|
| **[mcp ≥ 1.20](https://pypi.org/project/mcp/)** | MCP client + server SDK (stdio, SSE, Streamable HTTP, WebSocket transports) |
| **FastMCP** | Built-in MCP server class for exposing agent-as-server |

### LLM Providers (all optional extras)

| Provider | Install extra | Default model field |
|---|---|---|
| OpenAI / GPT-4o | `mcp-agent[openai]` | `openai.default_model` |
| Anthropic / Claude | `mcp-agent[anthropic]` | `anthropic.default_model` |
| AWS Bedrock | `mcp-agent[bedrock]` | `bedrock.default_model` |
| Anthropic on Bedrock | `mcp-agent[anthropic_bedrock]` | — |
| Anthropic on Vertex | `mcp-agent[anthropic_vertex]` | — |
| Google Gemini | `mcp-agent[google]` | `google.default_model` |
| Azure AI Inference | `mcp-agent[azure]` | `azure.default_model` |
| Ollama (local) | `mcp-agent[ollama]` (no extra dep) | `ollama.default_model` |
| LM Studio (local) | no extra dep | `lm_studio.default_model` |
| Cohere (embeddings) | `mcp-agent[cohere]` | — |

### Data & Validation

| Technology | Role |
|---|---|
| **Pydantic v2** | Config models, structured output, request/response validation |
| **pydantic-settings** | Environment + YAML settings loading |
| **pydantic-yaml** | YAML config file parsing |
| **scikit-learn** | Cosine similarity for embedding-based routing / classification |
| **NumPy** | Vector math used by embedding workflows |

### Observability

| Technology | Role |
|---|---|
| **OpenTelemetry SDK** | Distributed tracing |
| **OTLP HTTP exporter** | Sends spans to any OTLP-compatible backend (Jaeger, Grafana, etc.) |
| **opentelemetry-instrumentation-openai** | Auto-instrument OpenAI calls |
| **opentelemetry-instrumentation-anthropic** | Auto-instrument Anthropic calls |
| **Rich** | Terminal progress display and pretty logging |

### Auth & OAuth

| Technology | Role |
|---|---|
| **FastAPI** | HTTP server for OAuth callback handling and MCP-as-server |
| **aiohttp / httpx** | Async HTTP clients for OAuth token exchange and remote MCP servers |
| **python-dotenv** | `.env` file support for secrets |
| **websockets** | WebSocket transport for MCP server connections |

### Developer Tooling

| Technology | Role |
|---|---|
| **ruff** | Linter + formatter |
| **pytest + pytest-asyncio** | Test runner |
| **pre-commit** | Git hooks for lint/format |
| **hatchling** | Build backend (`pip install mcp-agent`) |
| **typer** | CLI framework for `mcp-agent` and `mcp-cloud` commands |

---

## 6. Constraints & Design Decisions

### MCP-First

Every tool capability is expressed as an MCP server. This means agents have no direct function-call bindings to user code — all tools are discovered at runtime through the MCP protocol. This enables remote tools, hot-swap servers, and multi-language tooling.

### Composability over Complexity

The framework deliberately avoids a monolithic "agent graph" abstraction. Instead, patterns like Orchestrator and Swarm are composed from the same `Agent` + `AugmentedLLM` primitives. Any pattern can be nested inside another.

### Provider Agnosticism

`AugmentedLLM` is an abstract base class. Provider-specific message formats (OpenAI `ChatCompletionMessage`, Anthropic `MessageParam`, etc.) are isolated in per-file subclasses and multipart converters. Switching providers requires changing one constructor call.

### Dual Execution Engine

asyncio and Temporal share the same API surface via the decorator registry. Code that runs in asyncio will run in Temporal with durable execution guarantees by changing `execution_engine: temporal` in config and starting a Temporal worker — **no application code changes required**.

### Config-First, Secrets-Separated

`mcp_agent.config.yaml` holds all non-sensitive configuration and is safe to commit. `mcp_agent.secrets.yaml` holds API keys and is gitignored by default. Environment variables can also supply secrets and are resolved automatically by `pydantic-settings`.

### Tool Namespace Isolation

When an agent connects to multiple MCP servers, tool names are prefixed with the server name (e.g., `filesystem_read_file`, `fetch_get`). This prevents collisions and makes the origin of each tool explicit in LLM tool-call logs.

### Python Version Floor

Requires Python ≥ 3.10 for `match`/`case`, `ParamSpec`, and `TypeAlias` used throughout the type system.

### Optional Dependencies

All LLM providers and Temporal are optional extras. A minimal `pip install mcp-agent` installs only the core framework; users pull in provider SDKs on demand. This keeps the base install lightweight.

### Observability Is Opt-In

OpenTelemetry tracing is configured via the `otel` block in `mcp_agent.config.yaml`. The `OpenTelemetrySettings` model defaults `enabled: false`, so no spans are emitted unless the block is explicitly configured with an exporter endpoint. Usage telemetry (anonymized metrics) has a separate `usage_telemetry.enabled` flag, which defaults to `true` but can be disabled.

---

## 7. Repository Structure

```
mcp-agent/
├── src/
│   └── mcp_agent/
│       ├── app.py                  # MCPApp — entry point
│       ├── config.py               # Pydantic settings & YAML loader
│       ├── agents/
│       │   ├── agent.py            # Agent class
│       │   └── agent_spec.py       # AgentSpec (YAML-defined agents)
│       ├── workflows/
│       │   ├── llm/                # AugmentedLLM + provider subclasses
│       │   │   ├── augmented_llm.py
│       │   │   ├── augmented_llm_openai.py
│       │   │   ├── augmented_llm_anthropic.py
│       │   │   ├── augmented_llm_google.py
│       │   │   ├── augmented_llm_azure.py
│       │   │   ├── augmented_llm_bedrock.py
│       │   │   ├── augmented_llm_ollama.py
│       │   │   ├── augmented_llm_lm_studio.py
│       │   │   ├── multipart_converter_*.py
│       │   │   ├── streaming_events.py
│       │   │   └── llm_selector.py
│       │   ├── orchestrator/       # Multi-agent task delegation
│       │   ├── parallel/           # Fan-out / fan-in
│       │   ├── router/             # LLM + embedding routing
│       │   ├── swarm/              # Agent handoff / swarm
│       │   ├── evaluator_optimizer/# Generate → evaluate → refine loop
│       │   ├── intent_classifier/  # Input classification
│       │   ├── embedding/          # Shared embedding utilities
│       │   └── deep_orchestrator/  # Extended orchestrator
│       ├── mcp/
│       │   ├── mcp_aggregator.py   # Multi-server tool bus
│       │   ├── mcp_connection_manager.py
│       │   └── mcp_agent_client_session.py
│       ├── executor/               # asyncio + Temporal execution engines
│       ├── core/                   # Context, context-dependent base
│       ├── cli/                    # mcp-agent & mcp-cloud CLI
│       │   ├── commands/           # init, dev, deploy, chat …
│       │   └── cloud/              # Cloud-specific sub-commands
│       ├── tracing/                # OpenTelemetry helpers
│       ├── logging/                # Structured logger, event progress
│       ├── oauth/                  # OAuth 2.0 manager & token store
│       ├── server/                 # FastAPI server (agent-as-server)
│       ├── human_input/            # Human-in-the-loop types & handler
│       ├── elicitation/            # LLM elicitation callbacks
│       ├── eval/                   # Evaluation framework
│       ├── tools/                  # Tool utilities
│       └── data/
│           ├── templates/          # mcp_agent.config.yaml templates
│           └── examples/           # Bundled runnable examples
├── examples/
│   ├── basic/                      # Hello-world, tool-filter, model selector
│   ├── workflows/                  # One example per workflow pattern
│   ├── model_providers/            # Per-provider quickstarts
│   ├── temporal/                   # Durable execution examples
│   ├── mcp/                        # SSE, WebSocket, roots, prompts
│   ├── mcp_agent_server/           # Agent exposed as MCP server
│   ├── oauth/                      # OAuth protected servers
│   ├── cloud/                      # mcp-agent Cloud deployment examples
│   ├── langchain/                  # LangChain integration
│   ├── crewai/                     # CrewAI integration
│   └── usecases/                   # End-to-end realistic use cases
├── tests/
│   └── workflows/                  # Unit + integration tests per pattern
├── scripts/
│   ├── format.py                   # ruff formatter wrapper
│   ├── lint.py                     # ruff linter wrapper
│   ├── gen_schema.py               # Regenerate config JSON schema
│   └── event_*.py                  # Log / event inspection utilities
├── schema/
│   └── mcp-agent.config.schema.json
├── pyproject.toml                  # Build metadata, dependencies, extras
├── Makefile                        # Developer shortcuts
└── uv.lock                         # Reproducible dependency lock file
```

# Getting Started — Step-by-Step

This guide walks you from a clean machine to a running `mcp-agent` project in the fewest steps possible.

---

## Prerequisites

| Requirement | Minimum version | Check |
|---|---|---|
| Python | 3.10 | `python --version` |
| Node.js | 18 (for some MCP servers) | `node --version` |
| [uv](https://docs.astral.sh/uv/) | latest | `uv --version` |

Install `uv` if missing:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Step 1 — Clone / enter the project

```bash
# If you cloned from a remote repo:
cd mcp-agent

# Or if you're already in the extracted directory, just stay there:
ls pyproject.toml   # should exist
```

---

## Step 2 — Set up a virtual environment and install dependencies

```bash
# Create a venv and install the package + all dev tools
uv sync --all-extras --all-packages --group dev
```

This installs:
- The `mcp-agent` core package (from `src/`)
- All optional LLM provider extras (OpenAI, Anthropic, Google, Azure, Bedrock, etc.)
- Dev tools: `ruff`, `pytest`, `pre-commit`

> **Minimal install** (no optional extras):
> ```bash
> uv sync
> ```

---

## Step 3 — Pick an example to run

All runnable examples live in `examples/`. Start with the simplest one:

```
examples/
├── basic/mcp_basic_agent/    ← recommended first example
├── basic/mcp_hello_world/
├── workflows/workflow_orchestrator_worker/
└── ...
```

```bash
cd examples/basic/mcp_basic_agent
```

---

## Step 4 — Configure an LLM provider

Each example has an `mcp_agent.config.yaml` that specifies which model to use,
and a `mcp_agent.secrets.yaml.example` that shows where to put your API keys.

**Copy the secrets template:**

```bash
cp mcp_agent.secrets.yaml.example mcp_agent.secrets.yaml
```

**Edit `mcp_agent.secrets.yaml` and add your key:**

```yaml
# mcp_agent.secrets.yaml  — gitignored, never commit this file

openai:
  api_key: "sk-..."

# Or for Anthropic:
# anthropic:
#   api_key: "sk-ant-..."
```

Alternatively, export the key as an environment variable — the framework resolves both:

```bash
export OPENAI_API_KEY="sk-..."
# or
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## Step 5 — Install MCP server dependencies (if needed)

Some examples use Node-based MCP servers. Install them once:

```bash
# Filesystem MCP server
npm install -g @modelcontextprotocol/server-filesystem

# Web fetch MCP server (installed via uvx on first run — no manual step needed)
```

> `uvx` tools (like `mcp-server-fetch`) are downloaded and cached automatically when the example runs.

---

## Step 6 — Run your first agent

```bash
# From inside examples/basic/mcp_basic_agent/
uv run main.py
```

You should see:
1. MCP server processes starting (logged to console)
2. Progress bars showing tool calls
3. The agent's final answer printed to stdout

---

## Step 7 — Explore other workflow patterns

Try the workflow examples to see each pattern in action:

```bash
# Orchestrator: LLM plans and delegates to worker agents
cd ../../workflows/workflow_orchestrator_worker
uv run main.py

# Parallel: fan-out to multiple agents simultaneously
cd ../workflow_parallel
uv run main.py

# Router: classify input and dispatch to best agent
cd ../workflow_router
uv run main.py

# Swarm: agents hand off to each other mid-conversation
cd ../workflow_swarm
uv run main.py

# Evaluator-Optimizer: generate → evaluate → refine loop
cd ../workflow_evaluator_optimizer
uv run main.py
```

Each folder contains its own `mcp_agent.config.yaml`. Copy the secrets file from Step 4 into each one, or export the API key as an environment variable.

---

## Step 8 — Scaffold a new project with the CLI

Instead of copying an example manually, use the CLI to scaffold a new project:

```bash
# Run via uvx (no install needed)
uvx mcp-agent init

# Or if installed:
mcp-agent init
```

Follow the prompts. A project directory is created with:
- `mcp_agent.config.yaml` — pre-configured template
- `mcp_agent.secrets.yaml` — secrets file (gitignored)
- `.gitignore` — preconfigured to exclude secrets and logs

---

## Step 9 — Run your new project

```bash
cd my_new_project
uv init
uv add "mcp-agent[openai]"   # or [anthropic], [google], etc.
# add your API key to mcp_agent.secrets.yaml
uv run main.py
```

---

## Step 10 — Run the test suite

From the repository root:

```bash
# All tests
uv run pytest

# Unit tests only (no LLM API calls, fast)
uv run pytest tests -m "not integration"

# With coverage report
uv run coverage run --omit="src/mcp_agent/cli/**" -m pytest tests -m "not integration"
uv run coverage report -m
```

---

## Common Configuration Options

### Switching the execution engine

Edit `mcp_agent.config.yaml`:

```yaml
# Default — in-process asyncio
execution_engine: asyncio

# Durable Temporal (requires a running Temporal server)
execution_engine: temporal
```

### Adding an MCP server

```yaml
mcp:
  servers:
    my_server:
      command: "uvx"
      args: ["my-mcp-server-package"]

    # SSE / remote server:
    remote_server:
      transport: sse
      url: "https://my-api.example.com/sse"
      headers:
        Authorization: "Bearer ${MY_API_TOKEN}"

    # WebSocket server:
    ws_server:
      transport: websocket
      url: "wss://my-service.example.com/mcp"
```

### Adjusting log level and output

```yaml
logger:
  transports: [console, file]
  level: debug          # debug | info | warning | error
  progress_display: true
  path_settings:
    path_pattern: "logs/mcp-agent-{unique_id}.jsonl"
    unique_id: "timestamp"
```

### Enabling OpenTelemetry tracing

```yaml
otel:
  endpoint: "http://localhost:4318"   # OTLP HTTP endpoint
  service_name: "my-agent"
  enabled: true
```

---

## Durable Execution with Temporal (Optional)

For long-running agents that must survive restarts:

### 1. Install Temporal extra

```bash
uv add "mcp-agent[temporal]"
```

### 2. Start a local Temporal server

```bash
# Via Docker
docker run --rm -p 7233:7233 -p 8233:8233 temporalio/auto-setup:latest

# Or install the Temporal CLI
temporal server start-dev
```

### 3. Set execution engine in config

```yaml
execution_engine: temporal
temporal:
  host: "localhost:7233"
  namespace: "default"
```

### 4. Start the worker and run

```bash
# Terminal 1 — start the Temporal worker
uv run run_worker.py

# Terminal 2 — trigger the workflow
uv run main.py
```

See `examples/temporal/` and `examples/cloud/temporal/` for full examples.

---

## Useful Makefile Commands

From the repository root:

```bash
make sync           # uv sync --all-extras (install / update deps)
make format         # run ruff formatter
make lint           # run ruff linter with auto-fix
make tests          # run pytest
make coverage       # run tests with coverage report
make schema         # regenerate schema/mcp-agent.config.schema.json
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: mcp_agent` | Run `uv sync` first; make sure you're in the `venv` created by `uv` |
| `npx: command not found` | Install Node.js ≥ 18 |
| `uvx: command not found` | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| MCP server fails to start | Check the server `command` / `args` in `mcp_agent.config.yaml`; run the command manually to see its output |
| `AuthenticationError` from OpenAI/Anthropic | Check `mcp_agent.secrets.yaml` or export the key as an env var |
| Temporal connection refused | Ensure `temporal server start-dev` is running on port 7233 |
| `python --version` shows < 3.10 | Use `uv python install 3.12` then `uv sync` |

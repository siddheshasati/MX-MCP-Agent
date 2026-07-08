import asyncio
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from mcp_agent.app import MCPApp
from mcp_agent.agents.agent import Agent
from mcp_agent.workflows.llm.augmented_llm import RequestParams
from mcp_agent.workflows.llm.llm_selector import ModelPreferences
from mcp_agent.workflows.llm.augmented_llm_openai import OpenAIAugmentedLLM
from mcp_agent.tracing.token_counter import TokenSummary

repo_root = Path(__file__).resolve().parents[3]
example_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=repo_root / ".env", override=False)
load_dotenv(dotenv_path=example_dir / ".env", override=False)

os.chdir(example_dir)
app = MCPApp(name="mcp_basic_agent")


def _get_provider_class() -> type:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "placeholder":
        raise RuntimeError("OPENAI_API_KEY is not set. Please add your API key to the .env file.")
    return OpenAIAugmentedLLM


def _get_model_name() -> str:
    return os.getenv("OPENAI_DEFAULT_MODEL", "llama3.2:3b")


@app.tool()
async def example_usage() -> str:
    """
    An example function/tool that uses an agent with access to the fetch and filesystem
    mcp servers. The agent will read the contents of mcp_agent.config.yaml, print the
    first 2 paragraphs of the mcp homepage, and summarize the paragraphs into a tweet.
    The example uses both OpenAI, Anthropic, and simulates a multi-turn conversation.
    """
    async with app.run() as agent_app:
        logger = agent_app.logger
        context = agent_app.context
        result = ""

        logger.info("Current config:", data=context.config.model_dump())

        # Add the current directory to the filesystem server's args
        context.config.mcp.servers["filesystem"].args.extend([os.getcwd()])

        finder_agent = Agent(
            name="finder",
            instruction="""You are an agent with access to the filesystem, 
            as well as the ability to fetch URLs. Your job is to identify 
            the closest match to a user's request, make the appropriate tool calls, 
            and return the URI and CONTENTS of the closest match.""",
            server_names=["fetch", "filesystem"],
        )

        async with finder_agent:
            logger.info("finder: Connected to server, calling list_tools...")
            tools_list = await finder_agent.list_tools()
            logger.info("Tools available:", data=tools_list.model_dump())

            provider_cls = _get_provider_class()
            logger.info(f"Using provider: {provider_cls.__name__}")

            llm = await finder_agent.attach_llm(provider_cls)
            if provider_cls is OpenAIAugmentedLLM:
                result += await llm.generate_str(
                    message="Print the contents of mcp_agent.config.yaml verbatim",
                )
            else:
                result += await llm.generate_str(
                    message="Print the contents of mcp_agent.config.yaml verbatim in a short summary",
                )
            logger.info(f"Response 1: {result}")

            result += "\n\n"
            result += await llm.generate_str(
                message="Give me a one-sentence summary of what this project does",
                request_params=RequestParams(
                    modelPreferences=ModelPreferences(
                        costPriority=0.1, speedPriority=0.2, intelligencePriority=0.7
                    )
                ),
            )
            logger.info(f"Response 2: {result}")

        # Display final comprehensive token usage summary (use app convenience)
        await display_token_summary(agent_app)

    return result


async def display_token_summary(app_ctx: MCPApp, agent: Agent | None = None):
    """Display comprehensive token usage summary using app/agent convenience APIs."""
    summary: TokenSummary = await app_ctx.get_token_summary()

    print("\n" + "=" * 50)
    print("TOKEN USAGE SUMMARY")
    print("=" * 50)

    # Total usage and cost
    print("\nTotal Usage:")
    print(f"  Total tokens: {summary.usage.total_tokens:,}")
    print(f"  Input tokens: {summary.usage.input_tokens:,}")
    print(f"  Output tokens: {summary.usage.output_tokens:,}")
    print(f"  Total cost: ${summary.cost:.4f}")

    # Breakdown by model
    if summary.model_usage:
        print("\nBreakdown by Model:")
        for model_key, data in summary.model_usage.items():
            print(f"\n  {model_key}:")
            print(
                f"    Tokens: {data.usage.total_tokens:,} (input: {data.usage.input_tokens:,}, output: {data.usage.output_tokens:,})"
            )
            print(f"    Cost: ${data.cost:.4f}")

    print("\n" + "=" * 50)

    # Optional: show a specific agent's aggregated usage
    if agent is not None:
        agent_usage = await agent.get_token_usage()
        if agent_usage:
            print("\nAgent Usage:")
            print(f"  Agent: {agent.name}")
            print(f"  Total tokens: {agent_usage.total_tokens:,}")
            print(f"  Input tokens: {agent_usage.input_tokens:,}")
            print(f"  Output tokens: {agent_usage.output_tokens:,}")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    start = time.time()
    asyncio.run(example_usage())
    end = time.time()
    t = end - start

    print(f"Total run time: {t:.2f}s")

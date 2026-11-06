"""Chat-client factories for the MAF engine.

MafPlanner mutates per-client settings (iteration limit), so every factory call
returns a new GeminiChatClient. The underlying google-genai client is shared within
one factory's lifetime and closed when the context exits.
"""

from contextlib import asynccontextmanager


@asynccontextmanager
async def maf_gemini_client_factory(api_key: str, model: str):
    from agent_framework.gemini import GeminiChatClient
    from google.genai import Client

    client = Client(api_key=api_key)
    try:
        yield lambda: GeminiChatClient(client=client, model=model)
    finally:
        try:
            await client.aio.aclose()
        finally:
            client.close()


def maf_gemini_client(api_key: str, model: str):
    """Standalone client for long-lived apps that create one client per request."""
    from agent_framework.gemini import GeminiChatClient

    return GeminiChatClient(api_key=api_key, model=model)

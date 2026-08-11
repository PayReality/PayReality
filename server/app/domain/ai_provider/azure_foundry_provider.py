"""Azure AI Foundry-backed AIProvider. Authenticates with Managed
Identity via DefaultAzureCredential -- no API key, matching this
program's own security requirement and the identity-first model already
established for every other Azure service in this platform (Key Vault,
Storage, Postgres).

Uses the Azure AI Model Inference API (`azure-ai-inference`), which
exposes an OpenAI-compatible chat-completions-with-tool-calling surface
against a Foundry model deployment -- the minimal SDK for a single
inference need, deliberately not the heavier `azure-ai-projects`/Hub
client, which is built for multi-project ML Studio scenarios this
program's single-deployment use case doesn't have.
"""

import json

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.identity import DefaultAzureCredential

from app.config import settings


class AzureFoundryProviderError(Exception):
    """Raised when the model does not return the forced tool call at
    all -- treated as a hard failure by callers (the same posture
    claude_provider.py already takes: an extraction with no result is
    not a valid empty result, it's an error)."""


class AzureAIFoundryProvider:
    def __init__(self, client: ChatCompletionsClient | None = None):
        self._client = client or ChatCompletionsClient(
            endpoint=settings.azure_ai_foundry_endpoint,
            credential=DefaultAzureCredential(),
            credential_scopes=["https://cognitiveservices.azure.com/.default"],
        )

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_content: str,
        json_schema: dict,
        schema_name: str,
        max_tokens: int = 8192,
    ) -> dict:
        response = self._client.complete(
            model=settings.azure_ai_foundry_deployment_name,
            messages=[
                SystemMessage(content=system_prompt),
                UserMessage(content=user_content),
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": schema_name,
                        "description": f"Record {schema_name}.",
                        "parameters": json_schema,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": schema_name}},
            max_tokens=max_tokens,
        )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            if call.function.name == schema_name:
                return json.loads(call.function.arguments)

        raise AzureFoundryProviderError(
            f"Azure AI Foundry did not return a {schema_name!r} tool call"
        )

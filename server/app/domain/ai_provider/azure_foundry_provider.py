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

Endpoint shape (Phase 2 finding, confirmed live): the deployed Cognitive
Services account is `kind = "OpenAI"`, not the newer `"AIServices"` kind
(forced by the pinned azurerm provider version -- see
AZURE_MIGRATION/terraform/modules/ai-foundry/main.tf). A `kind = "OpenAI"`
resource does not expose the unified Foundry "Models" inference route
(`{endpoint}/chat/completions`) at all -- only the classic, deployment-
scoped Azure OpenAI route does. Live testing (Phase 2) confirmed this
directly: constructing the client with the bare resource endpoint 404s
("Resource not found"); constructing it with the deployment path appended
and a classic-compatible api_version reaches the same underlying model
correctly. The `azure-ai-inference` SDK supports both shapes -- this is
an endpoint-construction fix, not a different SDK or a new dependency.

Token parameter (Phase 2 finding, confirmed live): gpt-5-mini is a
reasoning model and rejects `max_tokens` outright ("Unsupported
parameter... Use 'max_completion_tokens' instead"). It also spends part
of whatever budget it's given on invisible `reasoning_tokens` before any
visible content/tool-call output -- confirmed live: a 20-token budget
produced zero visible output, all 20 spent on reasoning. `max_tokens` is
therefore never sent (it stays out of the request body when None); the
budget is passed as `max_completion_tokens` via `model_extras`, the SDK's
documented pass-through mechanism for parameters outside its fixed
signature.
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
            endpoint=f"{settings.azure_ai_foundry_endpoint.rstrip('/')}/openai/deployments/{settings.azure_ai_foundry_deployment_name}",
            credential=DefaultAzureCredential(),
            credential_scopes=["https://cognitiveservices.azure.com/.default"],
            api_version="2024-06-01",
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
            model_extras={"max_completion_tokens": max_tokens},
        )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            if call.function.name == schema_name:
                return json.loads(call.function.arguments)

        raise AzureFoundryProviderError(
            f"Azure AI Foundry did not return a {schema_name!r} tool call"
        )

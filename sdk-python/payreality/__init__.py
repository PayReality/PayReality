"""PayReality: authorize an AI agent's action in one call.

    from payreality import Agent

    agent = Agent(api_key="...", private_key="...", organization_id="...")
    decision = agent.authorize(
        principal="Finance Manager",
        operation="Approve",
        resource="Vendor Payment",
        resource_data={"amount": 85000, "vendor": "ABC Ltd"},
    )
    if decision.allowed:
        execute()
    else:
        stop()

See SDK_QUICKSTART.md to get started, SDK_REFERENCE.md for the full
API, SDK_ARCHITECTURE.md for how this maps onto PayReality's actual
HTTP API, and SDK_SECURITY.md for how signing and key storage work.
"""

from .agent import Agent
from .exceptions import (
    ApiError,
    AuthenticationError,
    AuthorizationDenied,
    ConfigurationError,
    HumanReviewRequired,
    InvalidSignature,
    NetworkError,
    PayRealityError,
    ResolutionTimeoutError,
)
from .integration import Adapter, ContractShape
from .models import Capability, ConsumedCapability, Decision, RegisteredAgent, Resolution

__version__ = "0.5.0"

__all__ = [
    "Agent",
    "Adapter",
    "ContractShape",
    "Capability",
    "ConsumedCapability",
    "Decision",
    "RegisteredAgent",
    "Resolution",
    "PayRealityError",
    "ConfigurationError",
    "AuthenticationError",
    "InvalidSignature",
    "NetworkError",
    "ApiError",
    "AuthorizationDenied",
    "HumanReviewRequired",
    "ResolutionTimeoutError",
    "__version__",
]

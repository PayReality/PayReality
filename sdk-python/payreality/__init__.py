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

from importlib.metadata import PackageNotFoundError, version as _pkg_version

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

# Single source of truth is pyproject.toml's own `version` -- resolved
# from the installed package's real metadata (works for a wheel/sdist
# install, and for `pip install -e .`, which also writes real metadata).
# The literal fallback only matters if this package is ever imported
# WITHOUT having been installed at all (e.g. `sys.path` manipulation in
# a test harness) -- kept in sync with pyproject.toml by hand for that
# one narrow case, same discipline this file already held itself to
# before this fix, just no longer duplicated a second time in agent.py.
try:
    __version__ = _pkg_version("payreality")
except PackageNotFoundError:
    __version__ = "0.5.1"

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

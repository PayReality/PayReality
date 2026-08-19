# payreality

Official Python SDK for PayReality. Authorize an AI agent's action in one call, no manual signing.

```python
from payreality import Agent

agent = Agent(api_key="your-operator-key")
agent.register(name="AP Automation Bot", principal="Finance Manager")

decision = agent.authorize(
    principal="Finance Manager",
    operation="Approve",
    resource="Vendor Payment",
    resource_data={"amount": 85000, "vendor": "ABC Ltd"},
)

if decision.allowed:
    execute_payment()
```

No timestamps, nonces, signatures, or headers to build by hand. `register()` generates an ED25519 keypair and stores it locally; `authorize()` signs and submits automatically.

## Authentication

`authorize()` and `heartbeat()` need neither: they authenticate purely via the agent's own certificate signature. `register()`, `rotate_keys()`, `retire()`, and `get_decision()` are administrative and need one of:

- `bearer_token`: a session token (`POST /v1/auth/login`) or a scoped API key (`POST /v1/organization/api-keys`) -- a real, scoped, auditable identity. Preferred for anything beyond local development.
  ```python
  agent = Agent(bearer_token="pr_live_...")
  ```
- `api_key` + `organization_id`: the platform-wide Operator Key, which authenticates as an admin bypass rather than a scoped identity, and must name its target organization explicitly since it belongs to none.
  ```python
  agent = Agent(api_key="your-operator-key", organization_id="org-id")
  ```

## Install

```bash
pip install -e .
```

## Docs

- [`../SDK_QUICKSTART.md`](../SDK_QUICKSTART.md): get running in under 5 minutes
- [`../SDK_REFERENCE.md`](../SDK_REFERENCE.md): every class, method, and exception
- [`../SDK_ARCHITECTURE.md`](../SDK_ARCHITECTURE.md): how this maps onto PayReality's real API today
- [`../SDK_SECURITY.md`](../SDK_SECURITY.md): what gets signed, where keys live, what `api_key` really is

## Examples

See [`examples/`](examples/): `register_agent.py`, `approve_payment.py`, `approve_invoice.py`, `custom_operation.py`.

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

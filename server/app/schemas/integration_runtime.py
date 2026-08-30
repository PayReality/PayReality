from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AttestedIntentRequest(BaseModel):
    """The Adapter-signed request shape for the Trusted Integration
    Architecture's Phase 2 runtime path. Mirrors SubmitIntentRequest's
    universal fields (schemas/intent.py) but replaces agent_id with the
    Adapter-specific identity fields the brief requires: the request
    names the Binding and the origin Agent explicitly rather than
    relying on the signer's own identity to imply either (only Adapter
    identity itself is implied by the signature, per
    verify_integration_identity_signature). Every field the Adapter
    attests is bound by the same signature that authenticates this
    request -- the whole raw body is what gets verified, not a
    reconstructed subset of it."""

    integration_identity_id: UUID
    enforcement_binding_id: UUID
    origin_agent_id: UUID
    source_operation: str
    action: str
    resource: str | None = None
    amount: float | None = None
    currency: str | None = None
    counterparty: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime
    nonce: str
    correlation_id: str | None = None
    # Trusted Integration Architecture, Phase 3 (business-operation
    # identity): required, never defaulted -- the SDK's own Adapter
    # class requires the caller to supply this explicitly for the same
    # reason (a silently-generated value on every retry would defeat
    # the entire point of idempotency). The customer Adapter is
    # responsible for a value that remains stable across retries of the
    # same real external operation (an ERP transaction id, an
    # orchestrator execution id, a tool-call execution id, or a value
    # the Adapter itself constructs deterministically when the source
    # system provides none). Bounds/emptiness are validated server-side
    # (operation_identity_service.validate_external_operation_id) --
    # never format-restricted (no numeric/UUID requirement) and never
    # case-normalized: treated as an opaque identifier throughout.
    external_operation_id: str

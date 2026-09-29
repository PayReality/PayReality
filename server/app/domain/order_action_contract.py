"""Product lifecycle vertical slice (EVIDENCEBOUND-PAYREALITY-RECOVERY-V01
follow-up): the versioned, explicit order-action contract this milestone's
brief asks for -- distinct from domain/canonical_action.py's own generic,
integration-configurable contract (whatever a caller's Integration Contract
Version happens to declare in context_bindings, with no field ever
REQUIRED, only optionally bound if present).

This module is narrower and stricter, on purpose: for a synthetic order
submission specifically, five fields are declared material, with no
excluded field and no ambiguity about which:

  supplier            -- who the order is placed with. A silent supplier
                          substitution after approval is a different real-
                          world transaction, not a detail.
  quantity             -- how much. Changes the order's actual scope.
  buyer_account        -- which account is charged. The exact analogue of
                          "recipient account" in a payment; substituting it
                          is the canonical fraud/error pattern this whole
                          product exists to catch.
  delivery_location    -- where it goes. Changes the real-world effect of
                          fulfillment, independent of price or quantity.
  unit_price            -- what it costs per unit. Previously EXCLUDED from
                          the EvidenceBound interoperability report's
                          synthetic contract (see
                          test_interop_evidencebound_recovery_v01.py's own
                          test_material_fields_undeclared_field_change_
                          not_caught) -- that was a test-harness choice
                          exposing a real gap, not a product decision that
                          price doesn't matter. This module closes it:
                          unit_price is required and material here.

No field is excluded. If a future caller genuinely needs a non-material
order field (e.g. a free-text purchase-order note), it does not belong in
this contract's required set -- it would be carried the same way any other
non-material passthrough already is elsewhere in this codebase (declared_
task_reference on CanonicalAction, detail on ExecutionReceipt): present,
recorded, never hashed.

Fails closed on a missing required field, mirroring canonical_action.py's
and execution_receipt.py's own build_*() constructors exactly -- the same
"one constructor, fails closed, never silently builds a digest that can't
be meaningfully compared" discipline, not a fourth, different one.
"""

from __future__ import annotations

import decimal
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

ORDER_ACTION_CONTRACT_SCHEMA_VERSION = 1
_SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

REQUIRED_MATERIAL_FIELDS = ("supplier", "quantity", "buyer_account", "delivery_location", "unit_price")


class UnsupportedOrderActionSchemaVersionError(Exception):
    def __init__(self, schema_version: Any):
        self.schema_version = schema_version
        super().__init__(f"unsupported order action schema_version={schema_version!r}")


class MissingRequiredOrderActionFieldError(Exception):
    """Raised for ANY of the five required material fields, not only
    some -- there is no partially-valid OrderAction. The field_name is
    reported precisely so a rejected submission is actionable, not just
    a generic failure."""

    def __init__(self, field_name: str):
        self.field_name = field_name
        super().__init__(f"missing required order action field: {field_name}")


def _normalize_unit_price(unit_price) -> str:
    """Mirrors canonical_action._normalize_amount's own Decimal-quantize
    approach exactly, for the same reason: a float-rounding comparison
    would reintroduce the binary-imprecision digest instability this
    exists to avoid. 42.5 and 42.50 normalize identically."""
    return str(decimal.Decimal(str(unit_price)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP))


@dataclass(frozen=True)
class OrderAction:
    """The order-action contract, v1. `material_fields()`/`digest()`
    cover exactly REQUIRED_MATERIAL_FIELDS plus schema_version and
    external_operation_id (the operation identity itself, so two
    different operations never collide on digest even with identical
    order content) -- organization_id is deliberately NOT hashed into
    the digest, matching canonical_action.py's own material_fields()
    which DOES include it; the difference is intentional: this digest
    is compared for EQUALITY across the approval-to-consumption window
    within one already-tenant-scoped operation record, never looked up
    globally across tenants, so including organization_id here would
    only ever be redundant, not protective. observed_at is non-material
    (when, not what), matching every other *_action/*_receipt module in
    this codebase."""

    schema_version: int
    external_operation_id: str
    supplier: str
    quantity: int
    buyer_account: str
    delivery_location: str
    unit_price: str
    observed_at: datetime

    def material_fields(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "external_operation_id": self.external_operation_id,
            "supplier": self.supplier,
            "quantity": self.quantity,
            "buyer_account": self.buyer_account,
            "delivery_location": self.delivery_location,
            "unit_price": self.unit_price,
        }

    def digest(self) -> str:
        canonical = json.dumps(self.material_fields(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_order_action(
    *,
    external_operation_id: str,
    supplier: str,
    quantity: int,
    buyer_account: str,
    delivery_location: str,
    unit_price,
    observed_at: datetime | None = None,
    schema_version: int = ORDER_ACTION_CONTRACT_SCHEMA_VERSION,
) -> OrderAction:
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedOrderActionSchemaVersionError(schema_version)

    required = {
        "external_operation_id": external_operation_id,
        "supplier": supplier,
        "buyer_account": buyer_account,
        "delivery_location": delivery_location,
    }
    for name, value in required.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            raise MissingRequiredOrderActionFieldError(name)
    if quantity is None:
        raise MissingRequiredOrderActionFieldError("quantity")
    if unit_price is None:
        raise MissingRequiredOrderActionFieldError("unit_price")

    observed_at = observed_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    return OrderAction(
        schema_version=schema_version,
        external_operation_id=external_operation_id,
        supplier=supplier,
        quantity=quantity,
        buyer_account=buyer_account,
        delivery_location=delivery_location,
        unit_price=_normalize_unit_price(unit_price),
        observed_at=observed_at,
    )

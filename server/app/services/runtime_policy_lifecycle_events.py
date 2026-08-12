"""Runtime Policy Lifecycle (Phase 5, RUNTIME_POLICY_LIFECYCLE.md): a
single, small, standalone module for writing one immutable
RuntimePolicyLifecycleEvent row. Deliberately kept separate from both
services/runtime_policy_service.py (the existing, unmodified transition
functions) and services/runtime_policy_lifecycle_service.py (this
phase's new orchestration) so that the existing module can call this one
defensively without creating a circular import with the new one, which
itself imports FROM the existing module to reuse its transition
functions.

Every call here is best-effort: a failure to write an audit row must
never block or fail the real transition it's describing, the same
"defensive, opt-in, never block the critical path" posture already
established in Phase 1 (app/services/ai_authority_builder_service.py's
own Blob/Search calls).
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import RuntimePolicyLifecycleEvent
from app.domain.evidence.signing import payload_hash

logger = logging.getLogger("payreality.runtime_policy_lifecycle")


def record_lifecycle_event(
    db: Session,
    policy_key: uuid.UUID,
    version: int,
    event_type: str,
    actor: str | None = None,
    reason: str | None = None,
    payload: dict | None = None,
) -> None:
    """Appends one immutable row. Never raises -- logs and continues on
    any failure, so a database hiccup on the audit write can never
    prevent (or appear to roll back) the actual create/edit/approve/
    compile/activate/etc. transition that already succeeded."""
    try:
        event_payload = payload or {}
        event_hash = payload_hash(
            {
                "policy_key": str(policy_key), "version": version, "event_type": event_type,
                "actor": actor, "reason": reason, "payload": event_payload,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        db.add(
            RuntimePolicyLifecycleEvent(
                id=uuid.uuid4(), policy_key=policy_key, version=version, event_type=event_type,
                actor=actor, reason=reason, payload=event_payload, event_hash=event_hash,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "runtime_policy_lifecycle_event_write_failed policy_key=%s version=%s event_type=%s",
            policy_key, version, event_type,
        )

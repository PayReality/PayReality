import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    # Every Mapped[datetime] column becomes a real TIMESTAMPTZ, not the bare
    # (server-timezone-dependent) TIMESTAMP. The local Postgres install's
    # server timezone defaulted to Africa/Johannesburg (UTC+2) at initdb
    # time; without this, a timezone-aware Python datetime silently gets
    # converted to server-local wall-clock time on write and loses its
    # offset on read, which broke Mandate valid_from/valid_to comparisons
    # against Intent timestamps in the Rego bundle (both looked like naive
    # ISO strings, but represented different instants).
    type_annotation_map = {datetime: DateTime(timezone=True)}


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class BusinessUnit(Base):
    """Phase 1 (PHASE_1_AUTHORITY_MODEL.md): one level of the Authority
    Model's org hierarchy, above Department. Belongs to exactly one
    Organization; new and additive, referenced nowhere in the existing
    enforcement path yet."""

    __tablename__ = "business_units"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Department(Base):
    """Phase 1: belongs to exactly one BusinessUnit. Kept as a distinct
    level (not collapsed into BusinessUnit) so a customer with no
    department-level subdivision simply never populates this table,
    rather than every customer being forced into a two-level hierarchy."""

    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = uuid_pk()
    business_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_units.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Team(Base):
    """Phase 1: belongs to exactly one Department; the level a Principal
    is most often actually assigned to day-to-day. Optional in the
    hierarchy, same reasoning as Department."""

    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = uuid_pk()
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Resource(Base):
    """Phase 1: promotes the previously-informational-only AuthorityResource
    concept into something the enforcement path can actually reference.
    RuntimePolicy.scope.resource remains a plain string for backward
    compatibility -- this table is additive, never required."""

    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(Text)
    owner_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id")
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Principal(Base):
    __tablename__ = "principals"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id")
    )
    # Phase 1 (PHASE_1_AUTHORITY_MODEL.md): additive, all nullable -- every
    # existing Principal row, and every existing match against
    # Principal.name (RuntimePolicy.scope.principal, Agent lookup), is
    # completely unaffected until these are actually populated. Not a
    # separate Role table: no current requirement demonstrates a need for
    # role-to-role relationships beyond a label.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_units.id")
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id")
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"))
    role: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # spec 12.4 Stage 1: store the byte-identical artifact, never
    # transformed. In the database, not local disk: a container's local
    # filesystem doesn't survive a redeploy or restart, and on the
    # zero-cost pilot deployment it's also owned by root and unwritable
    # by the app's non-root user regardless. Both hit for real running
    # this in production, not theoretical.
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('extraction_pending','extracted','extraction_failed')",
            name="ck_documents_status",
        ),
    )


class Authority(Base):
    __tablename__ = "authorities"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Authority-as-a-continuous-object, Stage G: nullable, was NOT NULL.
    # This table predates the AI Authority Builder's corpus pipeline,
    # which has its own, separate document table (authority_corpus_
    # documents) and no row in `documents` at all. An Authority now cites
    # EITHER a legacy single document OR a corpus (see corpus_id below
    # and ck_authorities_has_a_source), never neither.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id")
    )
    corpus_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id")
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id"), nullable=False
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    limit_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[int | None]
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-text identifier, not a FK; there is no user/auth system yet in
    # Phase 1 (see plan's frontend-integration notes); becomes a real FK
    # once login exists.
    reviewer_id: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None]
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    # extracted_* retain the original AI output untouched, per spec 13.7,
    # even after a reviewer edits limit_amount/currency/conditions above.
    extracted_limit_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    extracted_currency: Mapped[str | None] = mapped_column(String(3))
    extracted_conditions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_review','approved','rejected')",
            name="ck_authorities_status",
        ),
        CheckConstraint(
            "(document_id IS NOT NULL) OR (corpus_id IS NOT NULL)",
            name="ck_authorities_has_a_source",
        ),
        Index("idx_authorities_document", "document_id"),
        Index("idx_authorities_corpus", "corpus_id"),
        Index("idx_authorities_status", "status"),
    )


class Policy(Base):
    """The compiled OPA bundle row -- NOT the same object as RuntimePolicy
    (below, table `runtime_policy_records`, Policy Studio's authoring
    domain object). This table holds exactly one 'active' row at a time
    (see the partial unique index below) and is read on every single
    Intent evaluation via intent_service._DbPolicyStore.get_active(); a
    RuntimePolicy is compiled into one of these at deploy time
    (runtime_policy_service.deploy_policy). The two names colliding is a
    known, deliberately-deferred naming issue (Stage K): this table sits
    on the hottest path in the system, so renaming it is a bigger-blast-
    radius change than its cosmetic payoff justifies today."""

    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_hash: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_uri: Mapped[str] = mapped_column(Text, nullable=False)
    compiled_at: Mapped[datetime | None]
    activated_at: Mapped[datetime | None]
    retired_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','compiled','active','retired')",
            name="ck_policies_status",
        ),
        UniqueConstraint("version", name="uq_policies_version"),
        # Partial unique index enforcing "exactly one active Policy" (spec 12.4 Stage 9 / 20.2).
        Index(
            "idx_policies_single_active",
            "status",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )


class Mandate(Base):
    __tablename__ = "mandates"

    id: Mapped[uuid.UUID] = uuid_pk()
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policies.id"), nullable=False
    )
    authority_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authorities.id"), nullable=False
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id"), nullable=False
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    max_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    review_threshold: Mapped[float | None] = mapped_column(Numeric(18, 2))
    valid_from: Mapped[datetime] = mapped_column(nullable=False)
    valid_to: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        Index("idx_mandates_policy", "policy_id"),
        Index("idx_mandates_principal_scope", "principal_id", "scope"),
    )


class Constraint(Base):
    __tablename__ = "constraints"

    id: Mapped[uuid.UUID] = uuid_pk()
    mandate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mandates.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (Index("idx_constraints_mandate", "mandate_id"),)


class Agent(Base):
    """Phase 9 (AGENT_LIFECYCLE.md): an Agent is now a full enterprise
    identity with a lifecycle, not a static record. `status` gained two
    new values (`registered`, `retired`) alongside the original three;
    every other column below is additive metadata/ownership, all
    nullable so existing rows (and the existing create_agent flow other
    callers may still rely on) are unaffected without a data backfill."""

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    acting_for_principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id"), nullable=False
    )
    owner: Mapped[str | None] = mapped_column(Text)
    business_unit: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    description: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    runtime: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    sdk_version: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None]
    rotation_requested_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('registered','active','suspended','revoked','retired')",
            name="ck_agents_status",
        ),
    )


class Certificate(Base):
    """Phase 9 (CERTIFICATE_ROTATION.md): status gained `issued` (a
    certificate provisioned at registration but not yet activated) and
    `expired` (set when its agent retires). `activated_at`/`rotated_at`/
    `expires_at` are additive and nullable; existing certificate rows
    (all created directly as `active`) are unaffected."""

    __tablename__ = "certificates"

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(server_default=func.now())
    activated_at: Mapped[datetime | None]
    rotated_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            "status IN ('issued','active','rotated','expired','revoked')",
            name="ck_certificates_status",
        ),
        Index("idx_certificates_agent", "agent_id"),
        # Phase 9: "Only ONE active certificate allowed" was previously only a
        # code-comment convention (agent_service.py), not enforced. A partial
        # unique index closes that gap at the database level, following the
        # same pattern as Policy's idx_policies_single_active.
        Index(
            "idx_certificates_single_active",
            "agent_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )


class AgentAuditEvent(Base):
    """Phase 9 (AGENT_LIFECYCLE.md): the lifecycle audit ledger. Every
    lifecycle transition (created, activated, suspended, reactivated,
    revoked, retired, certificate rotated, owner changed) becomes one
    signed, immutable row here, following the exact same canonicalize +
    ED25519-sign pattern as Decision Evidence (domain/evidence/signing.py,
    reused unchanged). Deliberately a separate table from `evidence`
    rather than relaxing evidence.decision_id to nullable: Evidence is
    specifically the record of an Intent's evaluation, and the Agent
    Detail Page's own spec already lists "Decision History", "Evidence",
    and "Audit" as three distinct sections, not one. Heartbeats do NOT
    produce a row here (they'd flood this ledger at 10,000+-agent scale
    for no auditing value); they only update Agent.last_seen_at."""

    __tablename__ = "agent_audit_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("idx_agent_audit_events_agent", "agent_id"),)


_ROLE_VALUES = "'owner','governance_admin','agent_admin','reviewer','auditor','executive'"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="UTC")
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    default_language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    # Everything in Organisation Settings that isn't its own column (Runtime
    # Authority defaults, Notifications config, Audit retention, MFA
    # requirement, etc.) lives here rather than as a wide, ever-growing set
    # of nullable columns -- these are operator preferences, not entities
    # other tables need to join against or index on.
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    mfa_enabled: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    must_reset_password: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_users_organization_email"),
        CheckConstraint(f"role IN ({_ROLE_VALUES})", name="ck_users_role"),
        CheckConstraint("status IN ('active','disabled')", name="ck_users_status"),
        Index("idx_users_organization", "organization_id"),
    )


class UserSession(Base):
    """Named UserSession, not Session, so it never collides with
    sqlalchemy.orm.Session -- every service/router in this codebase already
    imports that as `Session` for the DB session type."""

    __tablename__ = "sessions"

    # The session id doubles as the bearer token handed to the client: no
    # separate opaque-token column and no JWT, so validating a session is
    # always one indexed primary-key lookup against a value the DB can
    # revoke instantly (delete/expire the row), never a signature check
    # against a token that stays valid until it expires on its own.
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None]

    __table_args__ = (Index("idx_sessions_user", "user_id"),)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 of the raw key, not bcrypt: the raw key is a high-entropy
    # generated secret (not a human-guessable password), so a slow salted
    # hash buys nothing here and would cost a hash on every authenticated
    # request instead of only at login. A fast digest with an exact-match
    # lookup is the same tradeoff Stripe/GitHub-style API keys make.
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        CheckConstraint(f"role IN ({_ROLE_VALUES})", name="ck_api_keys_role"),
        Index("idx_api_keys_organization", "organization_id"),
    )


class SigningKey(Base):
    """A registry of every Ed25519 key ever used to sign Evidence and
    Agent Lifecycle audit events. Before this table existed, every
    verification checked the payload against whatever
    EVIDENCE_SIGNING_KEY_B64 happened to be configured *right now*
    (`evidence_service.verify_evidence`, `agent_service.verify_audit_event`),
    which meant rotating that key would have silently made every
    previously-signed record unverifiable -- a severe gap for a platform
    whose entire pitch is independently verifiable evidence.

    `key_id` is the natural primary key (it's already how a key is
    identified everywhere else, `Evidence.key_id`/`AgentAuditEvent.key_id`),
    not a surrogate UUID: there is nothing else this row could be looked
    up by. Rows are never deleted, including retired ones, for the same
    "nothing is deleted" reason every other evidentiary table in this
    schema follows. See EVIDENCE_KEY_ROTATION.md for the operational
    rotation flow this table enables."""

    __tablename__ = "signing_keys"

    key_id: Mapped[str] = mapped_column(Text, primary_key=True)
    public_key_b64: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    retired_at: Mapped[datetime | None]


class EnterpriseSystem(Base):
    """Authority-as-a-continuous-object, Stage A/J: a minimal, honest
    representation of the systems Runtime Authority protects (ERP, CRM,
    Finance, HR, Procurement, ...), distinct from the AI-provider/infra
    rows Organisation Settings' Integrations tab already lists. This
    table does not model an actual integration -- no connector code
    exists for any row here -- it only lets a Decision say which class of
    downstream system an allowed action ultimately reaches. `status`
    defaults to 'configuration_required' and stays there until real
    connector work exists, following the same no-fabrication pattern the
    Integrations tab already uses for Azure OpenAI/AWS Bedrock."""

    __tablename__ = "enterprise_systems"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="configuration_required")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "type IN ('erp','crm','finance','hr','procurement','legal','manufacturing','other')",
            name="ck_enterprise_systems_type",
        ),
        CheckConstraint(
            "status IN ('configuration_required','connected')",
            name="ck_enterprise_systems_status",
        ),
        Index("idx_enterprise_systems_organization", "organization_id"),
    )


class Intent(Base):
    __tablename__ = "intents"

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    correlation_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    counterparty: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False)
    nonce: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(nullable=False)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("idx_intents_agent", "agent_id"),
        UniqueConstraint("agent_id", "nonce", name="uq_intents_agent_nonce"),
    )


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intents.id"), nullable=False
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policies.id")
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    # Despite its name, this has never referenced the real `mandates`
    # table -- bundle_builder.py's own comment admits the name is reused,
    # not accurate; it actually holds matched RuntimePolicy ids. Left
    # untouched and still the source of truth read by every existing
    # caller. See evaluated_mandate_ids below for its replacement.
    evaluated_mandates: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Authority-as-a-continuous-object, Stage A: the correctly-named
    # replacement for evaluated_mandates above, holding real `mandates.id`
    # values. Written by intent_service.submit_intent (Stage H, via
    # runtime_policy_service.resolve_mandate_ids) and read by
    # resolution_service/routers/intents.py; empty for any matched policy
    # that has no Stage G-created Mandate yet.
    evaluated_mandate_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # Stage J: which protected system this action, if allowed, ultimately
    # reaches. Written by intent_service.submit_intent (Phase 5, Release
    # 2, via runtime_policy_service.resolve_enterprise_system, which reads
    # a reviewer-configured Constraints.enterprise_system_id back off the
    # matched RuntimePolicy) -- null whenever the matched policy never
    # configured one, or configured one that no longer exists.
    enterprise_system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprise_systems.id")
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('ALLOW','DENY','HUMAN_REVIEW')", name="ck_decisions_outcome"
        ),
        Index("idx_decisions_intent", "intent_id"),
        Index("idx_decisions_policy", "policy_id"),
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    # spec 8.2 EvidenceRecord: VERIFIED|PENDING|REJECTED.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Phase 5 (PHASE_5_EVIDENCE.md): the Evidence chain's scope key,
    # resolved via Agent -> Principal -> organization_id at creation
    # time (same path Runtime Authority Context, Phase 2, already
    # resolves). A real, indexed column rather than only living inside
    # `payload`, since finding "the most recent prior record in this
    # scope" needs to be a fast, targeted query on every single Evidence
    # write, not a re-join through Decision/Intent/Agent/Principal every
    # time. NULL (no organisation set on the Principal yet) is itself a
    # valid, consistent chain scope -- every such record chains together,
    # rather than chaining being a no-op until real org data exists.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )

    __table_args__ = (
        Index("idx_evidence_decision", "decision_id"),
        Index("idx_evidence_organization_created", "organization_id", "created_at"),
        CheckConstraint(
            "status IN ('VERIFIED','PENDING','REJECTED')", name="ck_evidence_status"
        ),
    )


class DecisionResolution(Base):
    """Addition beyond the literal spec: closes the HUMAN_REVIEW loop without
    mutating the immutable Decision row (spec 8.2's lifecycle guarantee).
    See plan section "The one addition: resolving HUMAN_REVIEW"."""

    __tablename__ = "decision_resolutions"

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=False, unique=True
    )
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    # Free text, kept exactly as-is: still what's read/rendered by every
    # existing caller. See resolved_by_user_id below for its replacement.
    resolved_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence.id")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Authority-as-a-continuous-object, Stage A: the real, authenticated
    # user behind this resolution, once Stage D wires it up. Null
    # whenever the Operator Key bypass (no session) was used instead,
    # which remains a fully supported path.
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    __table_args__ = (
        CheckConstraint(
            "resolution IN ('approved','denied')", name="ck_decision_resolutions_resolution"
        ),
    )


class RuntimePolicyRecord(Base):
    """Persistence for domain/runtime_policy/runtime_policy.py's
    RuntimePolicy (Policy Studio, POLICY_STUDIO_ARCHITECTURE.md). One row
    per version, never mutated after creation, matching RuntimePolicy's
    own immutability: editing produces a new row with an incremented
    version, not an update to an existing one.

    `content` stores the full RuntimePolicy via
    domain/runtime_policy/schema.py's to_dict()/from_dict(), the single
    source of truth for that shape; this table does not re-declare
    RuntimePolicy's fields as separate columns; policy_key/version/status
    are pulled out only because they're what the Policy List, Review
    Queue, and version-history queries actually filter and sort on."""

    __tablename__ = "runtime_policy_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    policy_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    bundle_id: Mapped[str | None] = mapped_column(Text)
    bundle_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','pending_review','approved','rejected','compiled','active','retired')",
            name="ck_runtime_policy_records_status",
        ),
        UniqueConstraint(
            "policy_key", "version", name="uq_runtime_policy_records_key_version"
        ),
        Index("idx_runtime_policy_records_policy_key", "policy_key"),
        Index("idx_runtime_policy_records_status", "status"),
    )


class PolicyExtractionUpload(Base):
    """AI Policy Builder (AI_POLICY_BUILDER_ARCHITECTURE.md): one row per
    uploaded document. `content` stores the byte-identical original in
    Postgres, the same reason `documents.content` already does: local
    disk does not survive a redeploy and is root-owned in this
    container. Independent of `documents`/`authorities`: that pipeline
    extracts Authority claims for the legacy Mandate model; this one
    extracts RuntimePolicy candidates. Conflating the two tables would
    couple two independent domains for no benefit."""

    __tablename__ = "policy_extraction_uploads"

    id: Mapped[uuid.UUID] = uuid_pk()
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "format IN ('pdf','docx','xlsx','csv','text')",
            name="ck_policy_extraction_uploads_format",
        ),
        CheckConstraint(
            "status IN ('uploaded','extracted','failed')",
            name="ck_policy_extraction_uploads_status",
        ),
    )


class PolicyExtractionCandidate(Base):
    """One row per candidate RuntimePolicy extracted from one upload
    (AI_EXTRACTION_PIPELINE.md Stage 4). `content` is stored in exactly
    schemas/runtime_policy.py's RuntimePolicyRequest JSON shape
    (RUNTIME_POLICY_MAPPING.md), directly editable, directly promotable
    into a real RuntimePolicy via the unmodified
    runtime_policy_service.create_policy. `confidence`/`missing_fields`
    describe the extraction, not the policy, so they live here, not in
    `content`."""

    __tablename__ = "policy_extraction_candidates"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Nullable, plus corpus_id below: a candidate belongs to exactly one of
    # a single-document upload (the original AI Policy Builder) or a
    # multi-document corpus (AI Authority Builder,
    # AI_AUTHORITY_BUILDER_ARCHITECTURE.md), never both, never neither,
    # enforced by the CHECK constraint below. Every row created by the
    # original AI Policy Builder still always sets upload_id, unaffected.
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_extraction_uploads.id")
    )
    corpus_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id")
    )
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    missing_fields: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    promoted_policy_key: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Explainability Model (Phase 3): the "extracted threshold" category
    # from EXPLAINABILITY_MODEL.md -- same four columns as the Authority
    # Graph's own entity/relationship tables, kept at the row level here
    # for the same reason confidence/source_excerpt/source_location
    # already are: `content`'s JSON shape is the RuntimePolicyRequest
    # itself (RUNTIME_POLICY_MAPPING.md), not an extension point for
    # extraction metadata.
    clause_reference: Mapped[str | None] = mapped_column(Text)
    extraction_reasoning: Mapped[str | None] = mapped_column(Text)
    detected_assumptions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    ambiguity_flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_review','promoted','dismissed')",
            name="ck_policy_extraction_candidates_status",
        ),
        CheckConstraint(
            "(upload_id IS NOT NULL) != (corpus_id IS NOT NULL)",
            name="ck_policy_extraction_candidates_exactly_one_owner",
        ),
        Index("idx_policy_extraction_candidates_upload", "upload_id"),
        Index("idx_policy_extraction_candidates_corpus", "corpus_id"),
        Index("idx_policy_extraction_candidates_status", "status"),
    )


class AuthorityCorpus(Base):
    """AI Authority Builder (AI_AUTHORITY_BUILDER_ARCHITECTURE.md): one or
    many documents, uploaded and analyzed together as a single body of
    evidence about one organisation's authority structure. Independent of
    `policy_extraction_uploads` (the original, still-unmodified AI Policy
    Builder's single-document table)."""

    __tablename__ = "authority_corpora"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Authority-as-a-continuous-object, Stage A: additive, nullable so
    # every existing corpus (uploaded before an organisation could be
    # attributed) is unaffected. Stage E's resolver is what starts
    # actually setting this on new uploads; nothing reads it before then.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded','extracted','failed')",
            name="ck_authority_corpora_status",
        ),
        Index("idx_authority_corpora_organization", "organization_id"),
    )


class AuthorityCorpusDocument(Base):
    """One uploaded file within a corpus. `content` stored in Postgres for
    the same reason every other document/upload table in this platform
    already does (documents.content, policy_extraction_uploads.content).

    `blob_path` (Authority Intelligence Program, Phase 1): set when this
    document was also written to Blob Storage. Additive, not a
    replacement -- `content` keeps being written on every upload
    regardless, so nothing about this table's existing read path
    changes for any environment that never configures Blob Storage."""

    __tablename__ = "authority_corpus_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    blob_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Coverage Analysis (Phase 3, EXPLAINABILITY_MODEL.md): deterministic
    # counts from the text-extraction step itself (domain/ai_policy_builder/
    # text_extraction.py's extract_text_with_coverage), never an LLM's
    # self-report -- a reviewer's "how much of this document did the
    # system actually see" question has to be answered by real parsing
    # statistics, not a model's guess about its own completeness. All
    # nullable: every document uploaded before this phase, and every
    # document whose extraction predates this column existing, simply has
    # no coverage figures rather than a fabricated zero.
    clauses_analysed: Mapped[int | None]
    clauses_ignored: Mapped[int | None]
    tables_extracted: Mapped[int | None]
    images_skipped: Mapped[int | None]

    __table_args__ = (
        CheckConstraint(
            "format IN ('pdf','docx','xlsx','csv','text')",
            name="ck_authority_corpus_documents_format",
        ),
        Index("idx_authority_corpus_documents_corpus", "corpus_id"),
    )


class AuthorityPrincipal(Base):
    """A discovered authority holder (AI_AUTHORITY_BUILDER_ARCHITECTURE.md's
    Authority Graph). Authority-as-a-continuous-object, Stage E: this now
    does promote into a real, first-class Principal -- see
    `resolved_principal_id` below and
    ai_authority_builder_service.resolve_principal(), the only code path
    allowed to set it. A reviewer can still reference this discovery by
    name directly in a promoted RuntimePolicy's scope.principal (a
    free-form string) when no resolution exists yet; that path is
    unchanged, not the only one anymore."""

    __tablename__ = "authority_principals"

    id: Mapped[uuid.UUID] = uuid_pk()
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str | None] = mapped_column(Text)
    reports_to: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(nullable=False)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Authority-as-a-continuous-object, Stage A: the eventual link to the
    # real, canonical Principal this discovery resolves to (Stage E).
    # Null means "discovered, not yet matched or promoted" -- the same
    # meaning AuthorityRelationship's from_principal_id/to_principal_id
    # already carry for the same reason.
    resolved_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id")
    )
    # Explainability Model (Authority Intelligence Program, Phase 3,
    # EXPLAINABILITY_MODEL.md): first-class columns, not fields buried
    # inside a JSON blob of raw LLM output -- a reviewer's "why was this
    # extracted" question is answered by a real column, queryable and
    # displayable the same way source_excerpt/source_location already are.
    clause_reference: Mapped[str | None] = mapped_column(Text)
    extraction_reasoning: Mapped[str | None] = mapped_column(Text)
    detected_assumptions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    ambiguity_flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    __table_args__ = (Index("idx_authority_principals_corpus", "corpus_id"),)


class AuthorityResource(Base):
    """A discovered business object (a Resource, in the universal
    vocabulary sense of RESOURCE_MODEL.md). Informational only in this
    phase: see AI_AUTHORITY_BUILDER_ARCHITECTURE.md."""

    __tablename__ = "authority_resources"

    id: Mapped[uuid.UUID] = uuid_pk()
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(nullable=False)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Explainability Model (Phase 3) -- see AuthorityPrincipal's comment.
    clause_reference: Mapped[str | None] = mapped_column(Text)
    extraction_reasoning: Mapped[str | None] = mapped_column(Text)
    detected_assumptions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    ambiguity_flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    __table_args__ = (Index("idx_authority_resources_corpus", "corpus_id"),)


class AuthorityOperation(Base):
    """A discovered verb (an Operation, in the universal vocabulary sense
    of OPERATION_MODEL.md). Informational only in this phase."""

    __tablename__ = "authority_operations"

    id: Mapped[uuid.UUID] = uuid_pk()
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(nullable=False)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Explainability Model (Phase 3) -- see AuthorityPrincipal's comment.
    clause_reference: Mapped[str | None] = mapped_column(Text)
    extraction_reasoning: Mapped[str | None] = mapped_column(Text)
    detected_assumptions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    ambiguity_flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    __table_args__ = (Index("idx_authority_operations_corpus", "corpus_id"),)


class AuthorityRelationship(Base):
    """A discovered link between two named principals: delegation,
    escalation, or inheritance. Model-reported, reviewed by a human, not
    a formally verified graph edge."""

    __tablename__ = "authority_relationships"

    id: Mapped[uuid.UUID] = uuid_pk()
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    from_principal: Mapped[str] = mapped_column(Text, nullable=False)
    to_principal: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(nullable=False)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Phase 1 (PHASE_1_AUTHORITY_MODEL.md): from_principal/to_principal
    # above stay exactly as they are -- they're the AI-extraction
    # provenance (what the source document literally said), never
    # silently overwritten by a resolved FK. These are the real,
    # enforceable edge: null means "extracted but not yet resolved to a
    # known Principal," populated means a real, traversable edge.
    from_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id")
    )
    to_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id")
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id")
    )
    operation: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[datetime | None]
    valid_to: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="proposed")
    # Cross-Organisation Authority (PHASE_1_AUTHORITY_MODEL.md): a
    # delegation edge whose two principals resolve to different
    # organizations is not honored in traversal unless explicitly
    # flagged -- fail-closed default, never silently possible just
    # because a name happened to resolve across an org boundary.
    cross_org_approved: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # Explainability Model (Phase 3) -- see AuthorityPrincipal's comment.
    clause_reference: Mapped[str | None] = mapped_column(Text)
    extraction_reasoning: Mapped[str | None] = mapped_column(Text)
    detected_assumptions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    ambiguity_flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    __table_args__ = (
        CheckConstraint(
            "kind IN ('delegation','escalation','inheritance')",
            name="ck_authority_relationships_kind",
        ),
        CheckConstraint(
            "status IN ('proposed','active','revoked','expired')",
            name="ck_authority_relationships_status",
        ),
        Index("idx_authority_relationships_corpus", "corpus_id"),
    )


class AuthorityConflict(Base):
    """A contradiction or duplication the model noticed across the
    corpus. Model-reported (AI_AUTHORITY_BUILDER_ARCHITECTURE.md: "never
    oversell a heuristic"), never a formal constraint-satisfaction
    proof; always surfaced for human review, never auto-resolved."""

    __tablename__ = "authority_conflicts"

    id: Mapped[uuid.UUID] = uuid_pk()
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Conflict Workspace (Phase 3, EXPLAINABILITY_MODEL.md): conflict_type
    # is the model's own classification (extraction_shared.py's tool
    # schema); circular_delegation conflicts may also be added
    # independently by deterministic graph analysis
    # (ai_authority_builder_service.detect_circular_delegations), never by
    # the model guessing at a cycle across principals it can't see the
    # whole graph for. reviewer_recommendation is NEVER asked of the
    # model -- it's computed deterministically from conflict_type/
    # confidence in the service layer, so this column is always populated
    # from auditable Python logic, never a second, opaque round of AI
    # judgment (Phase 3's own "only deterministic evidence stored"
    # security principle).
    conflict_type: Mapped[str | None] = mapped_column(Text)
    reviewer_recommendation: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "conflict_type IS NULL OR conflict_type IN "
            "('authority','threshold','role','policy','delegation','circular_delegation')",
            name="ck_authority_conflicts_conflict_type",
        ),
        Index("idx_authority_conflicts_corpus", "corpus_id"),
    )


class AuthorityGap(Base):
    """Missing information the model expected to find and didn't: an
    undefined approver, an unstated limit, a resource mentioned but
    never scoped."""

    __tablename__ = "authority_gaps"

    id: Mapped[uuid.UUID] = uuid_pk()
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("idx_authority_gaps_corpus", "corpus_id"),)


class AuthorityQuestion(Base):
    """A clarification question generated for a human reviewer. Not
    confidence-scored: a question is a request for information, not a
    claim to be confident or unconfident about."""

    __tablename__ = "authority_questions"

    id: Mapped[uuid.UUID] = uuid_pk()
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    answered: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    answer: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("idx_authority_questions_corpus", "corpus_id"),)


class AuthorityGraphApproval(Base):
    """Approval Audit (Authority Intelligence Program, Phase 3,
    EXPLAINABILITY_MODEL.md): one immutable row per "approve this
    corpus's Authority Graph" reviewer action
    (ai_authority_builder_service.approve_graph). Never updated or
    deleted, same discipline as `evidence` and `agent_audit_events`.

    This is an ADDITIVE audit record layered on top of the existing,
    unmodified per-item approval workflow (resolve_principal/
    resolve_relationship/activate_relationship,
    ai_policy_builder_service.promote_candidate) -- it does not change
    what any of those functions do, and approving a graph here does not
    itself promote or activate anything. It exists so a reviewer's
    decision to treat a corpus as reviewed is itself a permanent,
    independently-verifiable record, the same way an Evidence row is a
    permanent record of a Decision.

    `graph_hash` reuses domain/evidence/signing.py's canonicalize()/
    payload_hash() pattern unchanged -- SHA-256 of the sorted-key,
    whitespace-free JSON of `evidence_snapshot` -- rather than inventing
    a second hashing scheme for the same purpose."""

    __tablename__ = "authority_graph_approvals"

    id: Mapped[uuid.UUID] = uuid_pk()
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_corpora.id"), nullable=False
    )
    reviewer: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    approval_reason: Mapped[str | None] = mapped_column(Text)
    graph_hash: Mapped[str] = mapped_column(Text, nullable=False)
    approved_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("corpus_id", "version", name="uq_authority_graph_approvals_corpus_version"),
        Index("idx_authority_graph_approvals_corpus", "corpus_id"),
    )

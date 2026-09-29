import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, Numeric, String, Text, UniqueConstraint
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
    domain object). This table holds exactly one 'active' row per
    organization at a time (see the partial unique index below) and is
    read on every single Intent evaluation via
    intent_service._DbPolicyStore.get_active(); a RuntimePolicy is
    compiled into one of these at deploy time
    (runtime_policy_service.deploy_policy). The two names colliding is a
    known, deliberately-deferred naming issue (Stage K): this table sits
    on the hottest path in the system, so renaming it is a bigger-blast-
    radius change than its cosmetic payoff justifies today.

    Milestone 2 (Multi-Tenant Foundation, MILESTONE_2_MULTI_TENANT_FOUNDATION_SUMMARY.md
    Phase B1/B2, Option 2): `organization_id` is nullable specifically so
    this migration is safe against every existing single-tenant
    deployment (backfilled to that deployment's one real Organization,
    never left to a judgment call) -- the partial unique index was
    widened from "exactly one active Policy platform-wide" to "exactly
    one active Policy per organization," which are mathematically
    identical constraints for any deployment with exactly one
    organization, and only diverge once a second one is onboarded. Each
    organization now compiles to, and is read from, its own OPA package
    (runtime_policy_service._org_package_path) -- never the single
    shared `payreality.authorization` package every organization used
    to share unconditionally."""

    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_hash: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_uri: Mapped[str] = mapped_column(Text, nullable=False)
    compiled_at: Mapped[datetime | None]
    activated_at: Mapped[datetime | None]
    retired_at: Mapped[datetime | None]
    # Historical Policy Binding: the exact set of RuntimePolicyRecords
    # (by id + version, each immutable) compiler_v2.compile_bundle
    # already assembled into this bundle at deploy time
    # (PolicyBundle.manifest) -- previously computed, then discarded.
    # Null on every row created before this column existed; there is no
    # way to backfill one for those, the in-memory manifest at their own
    # deploy time is gone (see the migration's own docstring).
    bundle_manifest: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','compiled','active','retired')",
            name="ck_policies_status",
        ),
        UniqueConstraint("version", name="uq_policies_version"),
        # Milestone 2: widened from a single-column partial unique index
        # ("exactly one active Policy platform-wide") to a two-column one
        # ("exactly one active Policy per organization") -- see the class
        # docstring for why this is a safe, lossless widening for every
        # deployment that exists today.
        Index(
            "idx_policies_single_active_per_org",
            "organization_id",
            "status",
            unique=True,
            postgresql_where="status = 'active'",
        ),
        Index("idx_policies_organization", "organization_id"),
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
    # Milestone 3 (Enterprise Surface Isolation): the Organization
    # Lifecycle. 'active' is the only status prior to this milestone, so
    # every pre-existing row backfills to it -- the sole correct value,
    # since nothing before this could deactivate or archive an
    # Organization at all. Deactivation and archival are deliberately
    # sequential (see organization_lifecycle_service.archive_organization):
    # an Organization must be deactivated before it can be archived, the
    # same "retire, don't skip states" discipline Agent/RuntimePolicy
    # lifecycles already hold themselves to.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    deactivated_at: Mapped[datetime | None]
    deactivated_by: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None]
    archived_by: Mapped[str | None] = mapped_column(Text)
    # Developer Distribution & Sandbox v1: a real Organization on the same
    # backend, same authority pipeline, distinguished only by this label --
    # never a second, simplified engine. 'production' is the only value
    # prior to this milestone, so every pre-existing row backfills to it,
    # the sole correct value since nothing before this could create a
    # sandbox Organization at all. Used for: (a) the dashboard's "Sandbox"
    # badge, (b) sandbox-only resource caps (see agent_service.
    # register_agent and friends), (c) stale-sandbox cleanup (see
    # organization_lifecycle_service.list_stale_sandbox_organizations).
    # Deliberately NOT a security boundary of its own -- tenant isolation
    # is, and always was, by organization_id, regardless of this label.
    environment: Mapped[str] = mapped_column(Text, nullable=False, server_default="production")

    __table_args__ = (
        CheckConstraint("status IN ('active','deactivated','archived')", name="ck_organizations_status"),
        CheckConstraint("environment IN ('production','sandbox')", name="ck_organizations_environment"),
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


class OrganizationInvitation(Base):
    """Milestone 3 (Enterprise Surface Isolation), Organization Lifecycle:
    invite a new member into an existing Organization by email, accepted
    once via a one-time token -- the real email-and-accept flow the prior
    `POST /v1/users` (still supported, unchanged) never was: that endpoint
    creates the User directly with a temporary password shown once in the
    response, no email delivery, no separate accept step.

    `token_hash` follows api_keys.key_hash's exact pattern: SHA-256 of a
    high-entropy generated secret, not bcrypt -- the raw token is shown
    to the inviter exactly once (to send however they choose; this
    platform sends no email itself) and never stored. New table, so
    organization_id is NOT NULL from the start -- unlike every additive
    organization_id column elsewhere in this codebase, there are no
    pre-existing rows here to backfill against."""

    __tablename__ = "organization_invitations"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    invited_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    accepted_at: Mapped[datetime | None]
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    __table_args__ = (
        CheckConstraint(f"role IN ({_ROLE_VALUES})", name="ck_organization_invitations_role"),
        CheckConstraint(
            "status IN ('pending','accepted','revoked','expired')",
            name="ck_organization_invitations_status",
        ),
        UniqueConstraint("token_hash", name="uq_organization_invitations_token_hash"),
        Index("idx_organization_invitations_organization", "organization_id"),
    )


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


class FactSource(Base):
    """Trusted Enterprise Facts (PAYREALITY_FUTURE_VISION.md Part A):
    the identity a source system attests facts under, mirroring
    Agent/Certificate's own registration pattern exactly -- a source
    generates its own Ed25519 keypair and hands PayReality only the
    public half, the same trust model already used for Agent identity.
    `status` deliberately mirrors Certificate's active/revoked pair, not
    the full Agent lifecycle enum: a fact source has no "suspended" or
    "retired" state distinct from revoked at this stage, since nothing
    yet demonstrates a need for one."""

    __tablename__ = "fact_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint("status IN ('active','revoked')", name="ck_fact_sources_status"),
        Index("idx_fact_sources_organization", "organization_id"),
    )


class EnterpriseFact(Base):
    """Trusted Enterprise Facts: a named, typed, time-bound assertion
    about enterprise reality (ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md's
    already-decided data model -- subject, key, value, source,
    timestamp, expiry, optional attestation), implemented here for the
    first time. `expires_at` is deliberately NOT NULL: no fact type gets
    an unbounded default, per that document's Decision 4 (stale/missing
    -> unknown -> fail closed, never a default-forever trust).

    `attestation_type` distinguishes a source-signed attestation
    (verified against FactSource.public_key via the exact same
    domain/evidence/signing.py machinery already used for Evidence and
    Agent Lifecycle audit events) from a merely connector-authenticated
    one (no signature, trust rests on the caller's own authenticated
    session instead) -- Decision 3's "attestation-first where possible,
    connector-identity otherwise."

    Replay protection mirrors Intent's own `UNIQUE(agent_id, nonce)`
    pattern exactly: a previously accepted attestation cannot be
    resubmitted as if it were a fresh assertion."""

    __tablename__ = "enterprise_facts"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fact_sources.id"), nullable=False
    )
    # Nullable: some facts are org-wide rather than scoped to one
    # specific subject (e.g. a blanket "maintenance_window_active"
    # fact), matching the architecture doc's own "each scoped to one
    # subject" language without forcing a subject where none exists.
    subject: Mapped[str | None] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    attestation_type: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str | None] = mapped_column(Text)
    key_id: Mapped[str | None] = mapped_column(Text)
    nonce: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "attestation_type IN ('signed','connector_identity')",
            name="ck_enterprise_facts_attestation_type",
        ),
        UniqueConstraint("source_id", "nonce", name="uq_enterprise_facts_source_nonce"),
        Index("idx_enterprise_facts_organization", "organization_id"),
        Index("idx_enterprise_facts_lookup", "organization_id", "subject", "key", "expires_at"),
    )


class CapabilityToken(Base):
    """Capability Authorization Protocol (PAYREALITY_FUTURE_VISION.md
    Part C): the issuance-and-consumption record for a short-lived,
    signed capability bound to one ALLOW decision. Deliberately stores
    only a hash of the full signed token, never the token itself --
    "prefer hashes/references where storing full cryptographic artifacts
    would unnecessarily duplicate sensitive material" -- so a leaked
    database row cannot itself be replayed as a bearer credential.

    `nonce` is unique per row (mirroring Intent's own replay-defense
    constraint) and `consumed_at` is set exactly once, atomically, by
    the verify-and-consume path -- this row IS the single-use ledger,
    not a separate table, since an issuance record with no consumption
    yet and a consumed one are the same lifecycle object, not two kinds
    of thing.

    Trusted Integration Architecture, Phase 5.1 (Capability Issuance
    Idempotency): `decision_id` is also unique per row. One authority
    authorization lifecycle -- one ALLOW decision, or one approved
    HUMAN_REVIEW resolution -- produces at most one Capability, ever;
    repeated or concurrent issuance requests against the same Decision
    reuse or reject against this one row rather than minting a second,
    independently valid one. See services/capability_service.py's own
    module docstring for the full reasoning and the three distinct
    "a capability already exists for this decision" outcomes."""

    __tablename__ = "capability_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=False
    )
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    consumed_at: Mapped[datetime | None]
    issued_by: Mapped[str | None] = mapped_column(Text)

    # Trusted Integration Architecture, Phase 5: nullable, additive
    # provenance for the trusted-Adapter capability path only -- every
    # Agent-direct capability, and every capability issued before this
    # migration, leaves all five NULL. Mirrors Intent's own Phase 2/3
    # additive-provenance columns exactly, so a verifier (or a human
    # reading the Receipt) can see which Runtime Connection, Action
    # Mapping version, and business operation a capability was actually
    # bound to, not just which Decision.
    integration_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_identities.id")
    )
    enforcement_binding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enforcement_bindings.id")
    )
    integration_contract_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_contract_versions.id")
    )
    environment: Mapped[str | None] = mapped_column(Text)
    external_operation_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("nonce", name="uq_capability_tokens_nonce"),
        # Phase 5.1: replaces the earlier plain (non-unique) index on
        # decision_id -- a unique constraint already provides the index,
        # so this is not an addition alongside the old one, it is what
        # the old one should have been from the start.
        UniqueConstraint("decision_id", name="uq_capability_tokens_decision"),
        Index("idx_capability_tokens_organization", "organization_id"),
        Index("idx_capability_tokens_enforcement_binding", "enforcement_binding_id"),
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
    # Domain Generalization Milestone: the generic successor to
    # `counterparty` (finance-specific), populated end to end into the
    # OPA input as `intent.resource` so a RuntimePolicy authored with
    # Scope.resource (already supported by the compiler/Rego generator,
    # see runtime_policy.py's Scope docstring) can actually match a real
    # Intent -- previously it never could. Opaque, organization-defined
    # string ("invoice:INV-4821", "account:USR-829"); no ontology is
    # imposed here or anywhere else in this platform.
    resource: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False)
    nonce: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(nullable=False)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Product Experience Remediation Milestone 1 (Decision Provenance):
    # self-declared by the caller at submission time, not cryptographically
    # enforced -- the signing key alone cannot distinguish a genuine agent
    # process from a browser holding that same private key (the manual
    # Test Decision UI's own trust model), so this is honest about being a
    # declared channel, not a proof. "runtime" is the service-layer default
    # for any caller that omits it (real SDK integrations); the manual
    # submission UI explicitly sends "manual_test" instead. Nullable, with
    # NO server_default: every row written before this column existed is
    # genuinely NULL, never silently backfilled to "runtime" -- the
    # frontend renders NULL as an honest "Unknown (recorded before
    # provenance tracking)" state, never as a claim either way. Distinct
    # from a *policy simulation* (Policy Studio's dry-run, the standalone
    # Runtime Policy Simulator): those evaluate against OPA directly and
    # never create an Intent/Decision/Evidence row at all, so they need no
    # provenance value here -- there is nothing to tag.
    source: Mapped[str | None] = mapped_column(Text)

    # Trusted Integration Architecture, Phase 2: nullable, additive
    # provenance for the trusted-Adapter runtime path -- every existing
    # Agent-direct Intent, and every new one submitted through
    # POST /v1/intents unchanged, leaves all four of these NULL. Immutable
    # after creation (nothing in this codebase's Phase 2 code ever writes
    # to these columns a second time). `agent_id` above keeps its one,
    # permanent meaning regardless of path: the logical autonomous Agent
    # whose organizational authority is being evaluated -- for an
    # Adapter-mediated Intent, `agent_id` is still that same logical
    # Agent (Adapter-attested, allow-list-authorized, never independently
    # re-signed on this request), never the authenticated IntegrationIdentity
    # itself; that identity is recorded separately, here.
    integration_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_identities.id")
    )
    enforcement_binding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enforcement_bindings.id")
    )
    integration_contract_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_contract_versions.id")
    )
    # Copied from EnforcementBinding.environment at submission time --
    # never reconstructed later from whatever the Binding's environment
    # says today, since a Binding's environment is itself immutable once
    # ACTIVE (see EnforcementBinding's own docstring) this is belt-and-
    # braces historical pinning, matching this codebase's established
    # "pin what was actually evaluated, never recompute from a live row"
    # discipline (policy_version/policy_bundle_hash/principal_name all
    # already follow this same rule).
    environment: Mapped[str | None] = mapped_column(Text)

    # Trusted Integration Architecture, Phase 3 (business-operation
    # identity, operation_identity_service.py): all three nullable and
    # additive, present only for the trusted-Adapter runtime path --
    # every Agent-direct Intent, and every pre-Phase-3 Adapter-mediated
    # one, leaves all three NULL. `integration_id` is server-derived
    # from the resolved EnforcementBinding/Contract version, never
    # caller-chosen -- immutable historical provenance, and (together
    # with `environment` above) the actual DB-level idempotency scope;
    # deliberately NOT `enforcement_binding_id` (a Binding is replaceable
    # configuration, section 10) and NOT `integration_identity_id` (Adapter
    # rotation must not reset idempotency, section 11).
    # `canonical_operation_fingerprint` is the authority-relevant meaning
    # snapshot (operation_identity_service.compute_canonical_operation_
    # fingerprint) used only to detect a genuine meaning conflict on a
    # retry sharing the same external_operation_id -- never used to
    # re-derive or reinterpret anything about this historical row itself.
    external_operation_id: Mapped[str | None] = mapped_column(Text)
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id")
    )
    canonical_operation_fingerprint: Mapped[str | None] = mapped_column(Text)
    # Post-audit implementation, Priority 3 (app/domain/canonical_action.py):
    # additive, nullable, present only for the Adapter-mediated path --
    # every Agent-direct Intent, and every Adapter-mediated one created
    # before this column existed, leaves both NULL. Deliberately a
    # DIFFERENT value from canonical_operation_fingerprint above (a
    # broader digest, over more fields, for a different purpose --
    # binding a future Capability/execution-receipt/reconciliation record
    # to the exact canonical action, not detecting a same-meaning replay)
    # -- adding it never changes, and can never invalidate,
    # canonical_operation_fingerprint's own already-persisted values.
    canonical_action_schema_version: Mapped[int | None] = mapped_column()
    canonical_action_digest: Mapped[str | None] = mapped_column(Text)

    # Closeout pass, section 1: both nullable and additive, present only
    # when the caller opts into lifecycle protection for this submission
    # -- every existing Agent-direct Intent and every Adapter-mediated
    # one that omits them leaves both NULL, exactly today's default
    # behaviour (no Operation is ever created for it). DELIBERATELY
    # distinct fields from external_operation_id/integration_id above --
    # see BusinessOperationIdentity's own docstring (app/db/models.py)
    # for why a business_operation_id must be allowed to repeat across
    # several genuinely separate Intents where external_operation_id
    # cannot. Both are required together or omitted together (validated
    # in integration_runtime_service.submit_attested_intent, not by a DB
    # constraint here, matching how amount/currency/resource's own
    # contract-declared-path requirements are validated in that same
    # function rather than in the schema).
    business_operation_id: Mapped[str | None] = mapped_column(Text)
    intended_destination: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_intents_agent", "agent_id"),
        UniqueConstraint("agent_id", "nonce", name="uq_intents_agent_nonce"),
        # Trusted Integration Architecture, Phase 2: Agent-direct nonce
        # replay protection (above) is unchanged and untouched. This is a
        # SEPARATE, additive invariant scoped to the actual authenticated
        # signer of an Adapter-mediated request -- the same nonce reused
        # by the same IntegrationIdentity must be rejected, independent of
        # whatever Agent it happened to name as the logical actor. Partial
        # (WHERE integration_identity_id IS NOT NULL) so it is silently
        # absent -- never violated, never relevant -- for every existing
        # Agent-direct Intent.
        Index(
            "idx_intents_integration_identity_nonce",
            "integration_identity_id", "nonce",
            unique=True,
            postgresql_where="integration_identity_id IS NOT NULL",
        ),
        # Trusted Integration Architecture, Phase 3: at most one committed
        # business operation per (integration, environment,
        # external_operation_id) -- the real, DB-enforced invariant
        # section 17 requires. `environment` and `external_operation_id`
        # are only ever set together with `integration_id` in the same
        # INSERT (never independently), so a single `external_operation_id
        # IS NOT NULL` predicate is sufficient; organization scoping is
        # implicit, since `integration_id` already belongs to exactly one
        # organization (see this table's own Phase 3 docstring above).
        Index(
            "idx_intents_external_operation_scope",
            "integration_id", "environment", "external_operation_id",
            unique=True,
            postgresql_where="external_operation_id IS NOT NULL",
        ),
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
    # Root cause of a real, if narrow, ordering ambiguity (found via a CI
    # flake in test_history_returns_newest_first_and_paginates): with only
    # `server_default=func.now()`, SQLite's CURRENT_TIMESTAMP has 1-second
    # resolution, so several Decisions created in quick succession land on
    # the exact same value and "newest first" ordering becomes
    # database-tie-break-dependent, not chronological. An explicit,
    # microsecond-precision Python-side default removes the ambiguity on
    # every backend (SQLite in tests, Postgres in production), rather than
    # papering over it with a query-level tiebreaker that can't actually
    # recover the true creation order.
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), server_default=func.now())
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
    # PayReality 1.0 Audit finding G01: a genuine, monotonic per-
    # organization write-ordinal, assigned by append_evidence itself
    # (services/intent_service.py) under the same organization row lock
    # that now serializes concurrent appends -- never assigned by the
    # database. Exists because `created_at` alone is not a reliable
    # chain-order tiebreaker: two records appended close together can
    # share the same timestamp (certain under SQLite's one-second
    # CURRENT_TIMESTAMP resolution; possible, if rarer, even under
    # Postgres's microsecond resolution), and the previous tiebreaker --
    # `Evidence.id`, a random UUID -- has no relationship whatsoever to
    # true write order. verify_chain and _previous_chain_hash both now
    # order by this column first. NULL for every historical row written
    # before this column existed -- never backfilled or guessed (no
    # migration may fabricate a write order that was never actually
    # recorded); those rows keep falling back to created_at/id exactly
    # as before, the same ambiguity that already existed for them.
    sequence: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        Index("idx_evidence_decision", "decision_id"),
        Index("idx_evidence_organization_created", "organization_id", "created_at"),
        Index("idx_evidence_organization_sequence", "organization_id", "sequence"),
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
    # Runtime Policy Lifecycle (Phase 5, RUNTIME_POLICY_LIFECYCLE.md): all
    # nullable and additive -- every row created before this phase, and
    # every existing read of this table, is completely unaffected.
    # activated_*/effective_* are set only by
    # services/runtime_policy_lifecycle_service.py's activate_policy(),
    # layered on top of the existing, unmodified deploy_policy(); they
    # are never read by deploy_policy, reconcile_opa_with_active_policies,
    # or anything in the Runtime Authority Engine.
    activated_by: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None]
    activation_reason: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[datetime | None]
    effective_until: Mapped[datetime | None]
    # Set only by deprecate_policy() -- a label on an ACTIVE row, never a
    # status change: a deprecated-but-not-yet-retired policy must keep
    # being enforced (status stays "active") until its scheduled
    # retirement actually runs, or "scheduled for retirement" would mean
    # nothing.
    deprecated_at: Mapped[datetime | None]
    deprecation_reason: Mapped[str | None] = mapped_column(Text)
    # Set only by rollback_policy() on the NEW version it creates, so the
    # timeline can say "this version is a rollback to v{N}" without
    # guessing from content diffs.
    rollback_of_version: Mapped[int | None]
    # Milestone 2 (Multi-Tenant Foundation): nullable and additive, same
    # discipline as every column above -- backfilled to the deployment's
    # one real Organization for any pre-existing row
    # (MILESTONE_2_MULTI_TENANT_FOUNDATION_SUMMARY.md Phase B5). Set at
    # creation time (create_policy) and threaded, never re-derived, onto
    # every later version of the same policy_key (edit_policy) and onto
    # every RuntimePolicyLifecycleEvent/PolicyActivationSchedule that
    # references it -- the org a policy belongs to never changes across
    # its own version history.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    # Authority Freshness (PAYREALITY_FUTURE_VISION.md Part B): all
    # nullable and additive, same discipline as every other column on
    # this row. `last_attested_at`/`next_review_at` are a re-attestation
    # REMINDER, not an enforcement mechanism -- review-due never
    # disables anything on its own (see attest_policy's own docstring).
    # `authority_expires_at` is a materially different, separate
    # concept: an explicit hard expiry, checked at decision time for
    # high-risk policies specifically (intent_service.submit_intent),
    # never conflated with next_review_at.
    last_attested_at: Mapped[datetime | None]
    next_review_at: Mapped[datetime | None]
    review_cadence_days: Mapped[int | None]
    authority_expires_at: Mapped[datetime | None]
    # Authority Graph -> RuntimePolicy Compilation Gate: nullable and
    # additive, same discipline as every column above. Set once, at
    # create_policy time, only when this draft was produced by
    # ai_policy_builder_service.promote_candidate gating on a specific
    # AuthorityGraphApproval -- never set, and never backfilled, for a
    # manually-authored policy (Policy Studio's own create endpoint) or
    # a standalone (non-corpus) AI Policy Builder candidate. Pulled out
    # as a real, indexed column rather than left buried in `content`
    # JSONB (where the same fact is ALSO recorded on Metadata, for the
    # domain object's own self-containment) specifically so reverse
    # traceability ("which policies did this graph approval produce")
    # is a real, efficient query, not a JSONB scan -- the same
    # "pull out only what's filtered/queried on" convention policy_key/
    # version/status/bundle_hash already follow.
    source_graph_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_graph_approvals.id")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','pending_review','approved','rejected','compiled','active','retired','archived')",
            name="ck_runtime_policy_records_status",
        ),
        UniqueConstraint(
            "policy_key", "version", name="uq_runtime_policy_records_key_version"
        ),
        Index("idx_runtime_policy_records_policy_key", "policy_key"),
        Index("idx_runtime_policy_records_status", "status"),
        Index("idx_runtime_policy_records_organization", "organization_id"),
        Index("idx_runtime_policy_records_source_graph_approval", "source_graph_approval_id"),
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
    # Milestone 3 (Enterprise Surface Isolation): nullable and additive,
    # the same discipline every prior org-scoping column in this codebase
    # holds itself to. Confirmed unset before this milestone
    # (MULTI_TENANT_ARCHITECTURE_VERIFICATION.md) -- the single-document
    # pipeline had no organization concept at all. PolicyExtractionCandidate
    # deliberately does NOT get its own organization_id: a candidate
    # resolves its organization via exactly one of upload_id -> this
    # column, or corpus_id -> authority_corpora.organization_id, mirroring
    # the existing "resolve through the parent" convention.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )

    __table_args__ = (
        CheckConstraint(
            "format IN ('pdf','docx','xlsx','csv','text')",
            name="ck_policy_extraction_uploads_format",
        ),
        CheckConstraint(
            "status IN ('uploaded','extracted','failed')",
            name="ck_policy_extraction_uploads_status",
        ),
        Index("idx_policy_extraction_uploads_organization", "organization_id"),
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
    # Authority Graph Lineage & Versioning (issue #5): the immediate
    # previous approved version for this SAME corpus, stamped once at
    # insert time by approve_graph and never changed afterward -- same
    # immutability discipline as every other column here. Null only for
    # a corpus's first approved version. Deliberately one-directional:
    # "superseded by" is always derived by reverse lookup (which row, if
    # any, has this row's id as ITS predecessor_approval_id), never
    # stored, so there is no redundant bidirectional state that could
    # drift out of sync with itself.
    predecessor_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authority_graph_approvals.id")
    )

    __table_args__ = (
        UniqueConstraint("corpus_id", "version", name="uq_authority_graph_approvals_corpus_version"),
        Index("idx_authority_graph_approvals_corpus", "corpus_id"),
        Index("idx_authority_graph_approvals_predecessor", "predecessor_approval_id"),
    )


class SimulationScenario(Base):
    """Runtime Policy Simulator (Authority Intelligence Program, Phase 4,
    POLICY_SIMULATOR.md): a saved hypothetical Intent plus an expected
    outcome, so a reviewer can re-run "does this policy still do what we
    expect" after every edit.

    Only the scenario's DEFINITION is persisted here -- its most recent
    actual outcome and PASS/FAIL are computed live on every run
    (services/policy_simulation_service.run_scenario), never stored.
    This is deliberate, not an oversight: a scenario is a saved
    QUESTION, not a saved ANSWER, matching this phase's "never persist
    simulated decisions" principle exactly. `policy_key` is a bare UUID,
    not a foreign key -- the same convention `PolicyExtractionCandidate.
    promoted_policy_key` already established, since a policy_key groups
    RuntimePolicyRecord versions rather than identifying one single row."""

    __tablename__ = "simulation_scenarios"

    id: Mapped[uuid.UUID] = uuid_pk()
    policy_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expected_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Milestone 2 (Multi-Tenant Foundation): nullable and additive, same
    # discipline as RuntimePolicyRecord.organization_id above. A scenario
    # is always run against a specific policy_key's specific org, never
    # cross-org, so this is set once at creation from the referenced
    # policy's own organization_id, never re-derived.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )

    __table_args__ = (
        CheckConstraint(
            "expected_outcome IN ('ALLOW','DENY','HUMAN_REVIEW')",
            name="ck_simulation_scenarios_expected_outcome",
        ),
        Index("idx_simulation_scenarios_policy_key", "policy_key"),
        Index("idx_simulation_scenarios_organization", "organization_id"),
    )


class RuntimePolicyLifecycleEvent(Base):
    """Runtime Policy Lifecycle (Phase 5, RUNTIME_POLICY_LIFECYCLE.md):
    one immutable row per lifecycle transition on a RuntimePolicyRecord
    -- created, edited, submitted, approved, rejected, compiled,
    activated, activation_blocked (a safety check refused it),
    scheduled, rolled_back, deprecated, archived. Never updated or
    deleted, the same discipline `evidence`, `agent_audit_events`, and
    Phase 3's `authority_graph_approvals` already hold themselves to.

    This is simultaneously the Policy Timeline (read back in order,
    grouped by policy_key) and the Enterprise Audit trail (every
    transition, hashed) -- one mechanism serving both, not two separate
    tables recording the same facts twice.

    `event_hash` reuses domain/evidence/signing.py's canonicalize()/
    payload_hash() pattern unchanged, the same precedent
    `authority_graph_approvals.graph_hash` already established, rather
    than inventing a second hashing scheme.

    Written as a best-effort, defensive side effect from the existing,
    unmodified runtime_policy_service.py transition functions (see that
    module's own `_record_lifecycle_event` calls) -- a failure to write
    this row never blocks or fails the real transition it's recording."""

    __tablename__ = "runtime_policy_lifecycle_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    policy_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    event_hash: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Milestone 2 (Multi-Tenant Foundation): nullable and additive, same
    # discipline as every other column here. Threaded from the
    # referenced RuntimePolicyRecord at the moment each event is
    # recorded (record_lifecycle_event), never re-derived later -- an
    # audit trail's own organization attribution must never depend on a
    # live lookup that could disagree with what was true when the event
    # actually happened.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created','edited','submitted','approved','rejected',"
            "'compiled','activated','activation_blocked','scheduled','schedule_cancelled',"
            "'rolled_back','deprecated','archived','retired','attested')",
            name="ck_runtime_policy_lifecycle_events_event_type",
        ),
        Index("idx_runtime_policy_lifecycle_events_policy_key", "policy_key"),
        Index("idx_runtime_policy_lifecycle_events_organization", "organization_id"),
    )


class PolicyActivationSchedule(Base):
    """Runtime Policy Lifecycle (Phase 5): a future-dated activation or
    retirement, recorded now, executed later. Recording the schedule and
    executing it are deliberately two different actions
    (services/runtime_policy_lifecycle_service.py's schedule_activation/
    schedule_retirement vs. process_due_schedules) -- there is no
    background task runner anywhere in this platform, so this table is
    the durable record a periodic or manually-triggered call to
    process_due_schedules reads; nothing executes a schedule
    automatically on its own. See RUNTIME_POLICY_LIFECYCLE.md's "Known
    limitations" for this honestly stated."""

    __tablename__ = "policy_activation_schedules"

    id: Mapped[uuid.UUID] = uuid_pk()
    policy_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    executed_at: Mapped[datetime | None]
    execution_error: Mapped[str | None] = mapped_column(Text)
    # Milestone 2 (Multi-Tenant Foundation): nullable and additive, same
    # discipline as every other column here. Threaded from the
    # referenced RuntimePolicyRecord at schedule-creation time so
    # process_due_schedules can execute a due schedule as the correct
    # organization without a live re-lookup.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )

    __table_args__ = (
        CheckConstraint("action IN ('activate','retire')", name="ck_policy_activation_schedules_action"),
        CheckConstraint(
            "status IN ('pending','executed','failed','cancelled')",
            name="ck_policy_activation_schedules_status",
        ),
        Index("idx_policy_activation_schedules_policy_key", "policy_key"),
        Index("idx_policy_activation_schedules_status", "status"),
        Index("idx_policy_activation_schedules_organization", "organization_id"),
    )


class Integration(Base):
    """Trusted Integration Architecture, Phase 1 (TRUSTED_INTEGRATION_
    ARCHITECTURE.md): "this external enterprise system exists" -- nothing
    more. Deliberately minimal, the same restraint already established by
    EnterpriseSystem's own docstring: no connector credentials, no vendor
    schema, no discovery configuration, no runtime identity, and (unlike
    EnterpriseSystem) no status field at all, since Integration has no
    real Phase 1 lifecycle to track one for. `external_system_label` is
    a display label, not an identity -- IntegrationContractVersion below
    never has any reason to reinterpret its own history if this label is
    later renamed, since every version references `integration_id`, a
    stable id, never the label itself."""

    __tablename__ = "integrations"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    external_system_label: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("idx_integrations_organization", "organization_id"),)


class IntegrationContractVersion(Base):
    """Trusted Integration Architecture, Phase 1: one immutable-from-
    `validated`-onward row describing how one external system's one real
    operation (`source_operation`, e.g. "ChangeSupplierBankDetails")
    becomes PayReality's canonical meaning -- deterministic field
    extraction only, never a transformation language. Phase 1 stores and
    validates this; it is not yet consumed by any evaluation path
    (services/integration_contract_service.py's own module docstring
    covers this distinction in more depth).

    Stable identity is `(integration_id, source_operation)`, not a
    separate surrogate "IntegrationContract" table -- `version` is
    monotonic within that composite key, the exact same shape
    RuntimePolicyRecord's own `policy_key`+`version` already uses with no
    separate "Policy identity" table either (Trusted Integration
    Architecture report, corrected &sect;E). Editing the mapping for one
    `source_operation` can never reinterpret an unrelated one under the
    same Integration, because version scope is the full composite key,
    not the bare `integration_id`.

    Lifecycle: draft -> validated -> approved -> retired. There is no
    `active` status here -- Contract approval is not runtime deployment
    (Founder Decisions & Design Closure Addendum, corrected in this
    milestone): approving a new version never automatically retires a
    previously-approved sibling for the same operation. Multiple
    APPROVED versions of the same operation may legitimately coexist
    (e.g. production still pinned to v1 while staging trials v2) --
    Phase 2's EnforcementBinding is what will eventually select exactly
    one APPROVED version per binding; nothing in this table enforces
    that, by design, since no binding exists yet to need it.

    `content_hash` is computed once, at the draft-to-validated
    transition, over the mapping's *semantic* content only
    (source_operation, canonical_action, resource_path,
    fact_subject_path, amount_path, currency_path, context_bindings) --
    deliberately excluding `version` (which identifies the historical
    row, not what the mapping means) and every lifecycle/provenance
    field (status, created_at, approved_at, approved_by, retired_at,
    source_schema_fingerprint). Two separately-versioned rows with
    byte-equivalent semantic content hash identically.

    `source_schema_fingerprint` is provenance, not semantic content --
    excluded from content_hash on purpose. It exists only as a passive,
    optionally-populated hook for a future mapping-drift detector
    (explicitly not built in Phase 1); nothing reads it yet.

    `context_bindings` (JSONB, {canonical_context_key: source_field_path})
    is the ONLY channel through which caller-observed context is meant to
    reach Runtime Authority once Phase 2 wires runtime evaluation --
    locked in now as a schema/design decision, not yet enforced, since no
    runtime filter exists in Phase 1 to enforce it
    (services/integration_contract_service.py documents this same
    decision at the point Phase 2 will need to act on it)."""

    __tablename__ = "integration_contract_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    source_operation: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    canonical_action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_path: Mapped[str | None] = mapped_column(Text)
    fact_subject_path: Mapped[str | None] = mapped_column(Text)
    amount_path: Mapped[str | None] = mapped_column(Text)
    currency_path: Mapped[str | None] = mapped_column(Text)
    context_bindings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    content_hash: Mapped[str | None] = mapped_column(Text)
    source_schema_fingerprint: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    validated_at: Mapped[datetime | None]
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None]
    retired_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint(
            "integration_id", "source_operation", "version",
            name="uq_integration_contract_versions_identity",
        ),
        CheckConstraint(
            "status IN ('draft','validated','approved','retired')",
            name="ck_integration_contract_versions_status",
        ),
        Index("idx_integration_contract_versions_org", "organization_id"),
        Index("idx_integration_contract_versions_lookup", "integration_id", "source_operation"),
    )


class IntegrationIdentity(Base):
    """Trusted Integration Architecture, Phase 2: "a separately
    authenticated customer-operated workload permitted to attest
    external operations" -- a thin identity, deliberately not a second
    Agent model. It is never `Scope.principal`, holds no delegated
    organizational authority of its own, and is never the logical actor
    a RuntimePolicy evaluates; `Intent.agent_id` keeps that role
    permanently, for every Intent, regardless of which identity
    authenticated the request that created it.

    Lifecycle mirrors Agent's own five-state machine exactly
    (registered -> active -> suspended/revoked/retired) -- see
    services/integration_identity_service.py's own
    _ALLOWED_TRANSITIONS, a direct copy of agent_service.py's, since
    nothing about this identity's operational lifecycle differs from
    Agent's."""

    __tablename__ = "integration_identities"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="registered")
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('registered','active','suspended','revoked','retired')",
            name="ck_integration_identities_status",
        ),
        Index("idx_integration_identities_organization", "organization_id"),
    )


class IntegrationIdentityCertificate(Base):
    """Trusted Integration Architecture, Phase 2: the exact same
    cryptographic and rotation semantics as Agent's own `Certificate`
    (issued -> active -> rotated/expired/revoked, one active certificate
    at a time, old certificates never deleted) -- deliberately a
    SEPARATE table, not a shared row in `certificates`. Certificate.
    agent_id is NOT NULL and every existing Evidence/Intent/Decision
    reference and constraint around it assumes exactly one kind of
    owner; making that column nullable and adding a second, alternate
    owner FK would weaken an existing, proven constraint for every Agent
    certificate that has ever existed, to save one small table. Private
    keys never reach this table or anywhere else in this codebase --
    only the public key, exactly like Agent's own certificate model."""

    __tablename__ = "integration_identity_certificates"

    id: Mapped[uuid.UUID] = uuid_pk()
    integration_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_identities.id"), nullable=False
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
            name="ck_integration_identity_certificates_status",
        ),
        Index("idx_integration_identity_certificates_identity", "integration_identity_id"),
        Index(
            "idx_integration_identity_certificates_single_active",
            "integration_identity_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )


class EnforcementBinding(Base):
    """Trusted Integration Architecture, Phase 2: "this Adapter, in this
    environment, is approved to use this exact Integration Contract
    version for these explicitly allowed Agents" -- the runtime-
    deployment object. Contract approval (Phase 1) is deliberately
    deployment-neutral; THIS is where "approved meaning" becomes "the
    meaning currently permitted for this Adapter/environment." Despite
    the name, this does not make PayReality a PEP -- it is still only
    ever consulted by PayReality's own Runtime Authority evaluation, the
    same PDP boundary as everywhere else in this codebase.

    `integration_id`/`source_operation` are denormalized, immutable
    copies of the pinned Contract version's own identity, set once at
    creation and never updated -- purely so the single-ACTIVE-per-scope
    invariant below can be a real, DB-enforced partial unique index
    (the same idx_policies_single_active_per_org/idx_certificates_
    single_active shape already proven twice in this codebase), rather
    than a join-dependent constraint Postgres cannot express directly.

    Lifecycle: draft -> active -> retired. A DRAFT binding is fully
    mutable; once ACTIVE, its authority-relevant configuration
    (integration_identity_id, integration_contract_version_id,
    environment, and EnforcementBindingAgent membership) is immutable --
    changing any of it requires a new Binding. Activating a new Binding
    for the same (integration_identity_id, integration_id,
    source_operation, environment) scope atomically retires whichever
    Binding was previously ACTIVE for that exact scope (see
    services/enforcement_binding_service.py's activate_binding) -- this
    is deliberately NOT how Phase 1's Contract-version approval works
    (multiple APPROVED Contract versions may coexist forever); binding
    activation is the one place "exactly one current meaning" is a real
    invariant, because it is the one place Runtime Authority is actually
    reached."""

    __tablename__ = "enforcement_bindings"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    integration_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_identities.id"), nullable=False
    )
    integration_contract_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_contract_versions.id"), nullable=False
    )
    # Denormalized from the pinned IntegrationContractVersion at creation
    # time -- immutable, never independently supplied by a caller. See
    # class docstring for why: this is what makes the single-active-per-
    # scope index below a real DB constraint instead of a join.
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id"), nullable=False
    )
    source_operation: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    activated_at: Mapped[datetime | None]
    retired_at: Mapped[datetime | None]

    # Trusted Integration Architecture, Phase 5: a customer-declared,
    # never independently verified, label of what this Binding's own
    # downstream checkpoint claims to require. Only two real values --
    # ADVISORY (default: no declared requirement) and CAPABILITY_REQUIRED
    # (the customer declares their checkpoint requires a valid, consumed
    # Capability before it lets an action proceed). DECLARED_DECISION_CHECK,
    # VERIFIED, and REGISTERED_EXTERNAL_PEP are deliberately absent from
    # the CHECK constraint below: this phase never registers or
    # authenticates a distinct external PEP workload, so no code path may
    # claim any of those three levels (section 30/32's own instruction:
    # do not fake completeness to fill an enum). A declaration here is
    # never proof the checkpoint is non-bypassable.
    enforcement_assurance: Mapped[str] = mapped_column(Text, nullable=False, server_default="ADVISORY")

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','retired')", name="ck_enforcement_bindings_status",
        ),
        CheckConstraint(
            "enforcement_assurance IN ('ADVISORY','CAPABILITY_REQUIRED')",
            name="ck_enforcement_bindings_enforcement_assurance",
        ),
        Index("idx_enforcement_bindings_organization", "organization_id"),
        Index(
            "idx_enforcement_bindings_single_active_per_scope",
            "integration_identity_id", "integration_id", "source_operation", "environment",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )


class EnforcementBindingAgent(Base):
    """Trusted Integration Architecture, Phase 2: the explicit allow-
    list closing the origin-Agent binding invariant. An Adapter may
    attest origin only for an Agent explicitly enumerated here for the
    specific Binding it is presenting -- never "any Agent in the
    organization." Insert/delete only, no lifecycle of its own; adding
    or removing a row is itself only permitted while the owning Binding
    is still `draft` (services/enforcement_binding_service.py enforces
    this, not a DB constraint, matching this table's own pure-
    membership shape -- it carries no status to check)."""

    __tablename__ = "enforcement_binding_agents"

    id: Mapped[uuid.UUID] = uuid_pk()
    enforcement_binding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enforcement_bindings.id"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "enforcement_binding_id", "agent_id", name="uq_enforcement_binding_agents_membership",
        ),
        Index("idx_enforcement_binding_agents_binding", "enforcement_binding_id"),
    )


class ExecutionReceiptRecord(Base):
    """Post-audit implementation, Priority 5: the persisted row for one
    app/domain/execution_receipt.py ExecutionReceipt claim. Named
    ...Record, distinct from the domain module's own ExecutionReceipt
    dataclass, purely to avoid a same-name import collision between the
    two -- they are not the same object (this is the ORM row; that is the
    pure, DB-free material-fields/digest model it was built from).

    Append-only by construction, matching this whole codebase's Evidence-
    chain discipline: a state transition (ACCEPTED -> SUCCEEDED) is a NEW
    row, never an UPDATE of an existing one. `uq_execution_receipts_
    operation_status` below is what actually enforces "one row per
    (operation, status)" -- services/execution_receipt_service.py's own
    pre-check is a convenience, not the guarantee, exactly the same
    discipline capability_service.py/integration_runtime_service.py
    already apply to their own idempotency constraints.

    `integration_id`/`environment` are denormalized, immutable copies of
    the pinned EnforcementBinding's own scope at receipt-creation time --
    mirrors EnforcementBinding's own denormalization of integration_id/
    source_operation from its pinned Contract version, for the identical
    reason: it makes the natural dedup/conflict scope below a real,
    DB-enforced index, matching idx_intents_external_operation_scope's
    own (integration_id, environment, external_operation_id) scope
    exactly, rather than a narrower (and, for a multi-Integration
    organization, wrong) organization_id-only scope."""

    __tablename__ = "execution_receipts"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    integration_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_identities.id"), nullable=False
    )
    enforcement_binding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enforcement_bindings.id"), nullable=False
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id"), nullable=False
    )
    environment: Mapped[str] = mapped_column(Text, nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=False
    )
    capability_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capability_tokens.id")
    )
    canonical_action_digest: Mapped[str] = mapped_column(Text, nullable=False)
    external_operation_id: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_digest: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column()
    detail: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(server_default=func.now())
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence.id")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACCEPTED','SUCCEEDED','FAILED','PARTIALLY_SUCCEEDED','UNKNOWN')",
            name="ck_execution_receipts_status",
        ),
        UniqueConstraint(
            "integration_id", "environment", "external_operation_id", "status",
            name="uq_execution_receipts_operation_status",
        ),
        Index("idx_execution_receipts_organization", "organization_id"),
        Index("idx_execution_receipts_decision", "decision_id"),
    )


class ReconciliationResultRecord(Base):
    """Post-audit implementation, Priority 6: the minimal authorised-vs-
    executed reconciliation result for one Decision's Adapter-mediated
    execution. Append-only, exactly like ExecutionReceiptRecord: re-
    running reconciliation for the same Decision after new information
    arrives (e.g. a SUCCEEDED receipt following an earlier ACCEPTED-only
    state) appends a NEW row rather than rewriting a previous one -- the
    current reconciliation state for a Decision is simply its most recent
    row, ordered by computed_at. `result_digest` (over organization_id,
    decision_id, outcome, capability_id, latest_execution_receipt_id) is
    what makes re-running reconciliation with no new information a true
    no-op (services/execution_reconciliation_service.py's own
    idempotency check), never a pointless duplicate row on every call.

    Trust statement, unchanged from execution_receipt_service.py's own:
    this reconciles PayReality's own already-trusted records (the
    Decision, its Capability consumption, and its ingested execution
    receipts) against each other. It does not independently observe the
    external system -- see DECLARED_VS_OBSERVED_RECONCILIATION.md for the
    single-attester limitation this does not close."""

    __tablename__ = "reconciliation_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=False
    )
    capability_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capability_tokens.id")
    )
    latest_execution_receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_receipts.id")
    )
    canonical_action_digest: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    result_digest: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence.id")
    )
    computed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('MATCHED','MISMATCHED','EXECUTION_FAILED','PARTIAL','RECEIPT_MISSING','INDETERMINATE')",
            name="ck_reconciliation_results_outcome",
        ),
        Index("idx_reconciliation_results_organization", "organization_id"),
        Index("idx_reconciliation_results_decision", "decision_id"),
    )


class BusinessOperationIdentity(Base):
    """Closeout pass, section 1: the stable, trusted identity for a
    lifecycle-covered real-world business operation -- DISTINCT from
    Intent.external_operation_id (Trusted Integration Architecture Phase
    3's own per-SUBMISSION idempotency key, operation_identity_service.py).
    Those are different questions: external_operation_id dedupes an
    attempted SUBMISSION, and its own DB constraint
    (idx_intents_external_operation_scope) forbids ever reusing it for a
    second Intent -- so it structurally CANNOT identify "the same
    real-world operation, attempted again with a fresh authorization
    decision." business_operation_id identifies exactly that: the same
    real-world operation across genuinely separate attempts, each with
    its own Intent/Decision/Capability/Operation and necessarily its own,
    different external_operation_id.

    Composite identity, matching this section's own required definition:
      namespace    = integration_id (server-derived from the resolved
                      EnforcementBinding/Contract, never caller-chosen --
                      same reasoning Phase 3 already established for why
                      this, and not enforcement_binding_id or
                      integration_identity_id, is the correct boundary).
      tenant       = organization_id (implicit via integration_id, same
                      as Phase 3 -- not a redundant column there, but
                      explicit here since this table is looked up
                      directly, not only through Integration).
      destination  = the caller-DECLARED intended destination, required
                      at submission time (Intent.intended_destination) --
                      this table does not wait for dispatch evidence to
                      learn it, unlike Operation.destination for a
                      non-identity-covered operation.
      business_operation_id = the caller-supplied stable value, opaque,
                      compared byte for byte, never normalized (same
                      discipline as Phase 3's own
                      validate_external_operation_id, reused directly).

    Deliberately NOT keyed by material_action_digest or any other
    field-equality check: two legitimate, independent real-world orders
    can have byte-identical material fields (same supplier, quantity,
    buyer account, delivery location, unit price) without being the same
    operation. Identity here is asserted by the caller, never inferred
    from content -- and if a caller supplies a genuinely new business_
    operation_id for what a human would recognize as the same real-world
    action, that remains undetectable by design: this system claims no
    semantic duplicate detection across independently-identified intents.

    `current_operation_id` names the GOVERNING attempt -- the one
    evaluate_replacement_safety and issuance/consumption enforcement
    actually reason about. Advanced, never replaced, via the atomic
    conditional UPDATE in operation_identity_service.advance_current_
    attempt (the same "atomic conditional UPDATE, retry on rowcount==0"
    shape this codebase already established for CapabilityToken's own
    consume). Superseded attempts are never deleted -- see Operation.
    previous_attempt_operation_id for the preserved chain."""

    __tablename__ = "business_operation_identities"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id"), nullable=False
    )
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    business_operation_id: Mapped[str] = mapped_column(Text, nullable=False)
    current_operation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.id", use_alter=True, name="fk_boi_current_operation")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "integration_id", "destination", "business_operation_id",
            name="uq_business_operation_identity",
        ),
        Index("idx_business_operation_identities_organization", "organization_id"),
    )


class Operation(Base):
    """Product lifecycle vertical slice (EVIDENCEBOUND-PAYREALITY-RECOVERY-
    V01 follow-up): the durable record of one real-world attempted
    operation, tracked separately from its Capability -- a Capability is a
    single-use authorization artifact (it exists to be consumed exactly
    once, then is spent); an Operation is the persistent record of what
    was actually attempted and what is known about its outcome, which
    outlives the Capability's own consumption and must keep being
    queryable and updatable (via new observation evidence) long after.

    One row per Decision (`uq_operations_decision`), created at Capability
    issuance time (see services/operation_service.py's
    create_operation_for_decision) -- mirrors CapabilityToken's own
    decision_id uniqueness for the identical reason (Phase 5.1): one
    authorization lifecycle, one Operation, not a second independently
    valid one from a racing or repeated call. For a business-operation-
    identity-covered decision (section 1), a REPEATED identity does not
    reuse this row -- it creates a NEW Operation, chained via
    `previous_attempt_operation_id`, and becomes the identity's new
    `current_operation_id`; the original is preserved, never overwritten.

    Closeout pass, section 3: execution stage and outcome certainty are
    two independent axes, not one collapsed `state` string (the
    hardening pass's own single-column design let an observation that
    resolved to "outcome unknown" silently clobber whatever stage
    information -- CLAIMED vs. DISPATCHED -- existed before it; splitting
    them removes that bug entirely, not just documents around it).

    `execution_stage` -- what has been EVIDENCED about the attempt itself.
    Monotonic; only operation_service.record_claim / record_dispatch_
    evidence ever write it; observation/reconciliation logic never
    touches it, by construction:
        AUTHORIZED  -- a Capability exists; nothing attempted yet.
        CLAIMED     -- the Capability was atomically consumed -- an
                       execution attempt was authorized to proceed. Does
                       NOT establish the executor ever sent the
                       destination request.
        DISPATCHED  -- the executor explicitly reported having sent the
                       destination request (record_dispatch_evidence, a
                       distinct evidence event, never inferred from
                       CLAIMED alone).

    `outcome_status` -- what is known about the DESTINATION OUTCOME,
    independent of execution_stage (execution_stage=CLAIMED can coexist
    with outcome_status=UNKNOWN just as validly as execution_stage=
    DISPATCHED can -- the distinction between "unknown before dispatch
    evidence" and "unknown after evidenced dispatch" is preserved exactly
    because these are separate columns). Only operation_service.
    _finalize_observation_event / record_manual_adjudication ever write
    it:
        UNKNOWN                  -- the honest default. No receipt yet,
                                     a non-terminal receipt status only,
                                     evidence that doesn't cleanly resolve
                                     either way, OR (closeout pass,
                                     section 2) reconciliation evidence
                                     that WOULD resolve to a terminal
                                     conclusion but whose only source is
                                     an unsigned human relay -- see
                                     `evidence_assurance` below and this
                                     module's own evidence-acceptance-
                                     rules docstring. Never inferred as
                                     DISPATCHED-implies-failed or
                                     CLAIMED-implies-unknown-forever from
                                     a merely missing receipt.
        COMMITTED                -- sufficient evidence (signed Adapter
                                     report reconciling MATCHED, or an
                                     explicit manual adjudication)
                                     establishes the attempt succeeded.
        TERMINALLY_NOT_COMMITTED -- sufficient evidence establishes the
                                     attempt did not, and will not, commit.

    `evidence_assurance` -- section 2's own required, separate axis:
    what KIND of evidence outcome_status currently rests on, mechanically
    derived, never caller-set:
        NONE                -- no observation evidence recorded yet.
        REPORTED_UNVERIFIED -- an unsigned RBAC_HUMAN relay has reported
                                a claim (preserved in operation_evidence_
                                events), but alone it can only ever leave
                                outcome_status at UNKNOWN -- it is
                                evidence that something was CLAIMED to
                                have happened, never proof that it did.
        ADAPTER_REPORTED    -- a signature-verified Adapter reported it.
                                Proves what that Adapter reported, under
                                this platform's existing Trusted-Adapter
                                trust model -- not independent, third-
                                party destination verification, which no
                                integration contract in this codebase
                                currently establishes; if one ever does,
                                that is a stronger tier this column does
                                not yet have a value for, and none is
                                fabricated here.
        MANUAL_ADJUDICATED  -- an authorized human (Permission.
                                OPERATION_MANUAL_ADJUDICATE, a separate
                                permission from ordinary observation)
                                explicitly overrode/settled the outcome,
                                with a recorded rationale and evidence
                                references (operation_service.record_
                                manual_adjudication) -- a governance
                                decision, never a report of an external
                                fact, and never reachable through the
                                ordinary observation path.

    No column here enforces the transition graph (a CHECK constraint can
    only validate one row's current value, not its history) -- that
    discipline lives entirely in operation_service.py, which never issues
    a raw UPDATE against these columns from anywhere else in this
    codebase. AUTHORIZED and CLAIMED are never re-entered once left, and
    a Capability revoked (via its origin Agent) after CLAIMED does not,
    and structurally cannot, move an Operation's execution_stage
    backward -- there is no function anywhere that does that. Likewise,
    outcome_status never moves out of a terminal value once reached
    (Operation's own _TERMINAL_OUTCOMES set in operation_service.py).

    `material_action_digest` binds this Operation to the exact
    domain.order_action_contract.OrderAction (or, for a non-order action,
    whatever canonical-action digest applies) it was authorized against --
    the same "what, exactly, was decided" binding CapabilityToken.constraints
    already gives capability consumption, extended to survive past the
    Capability's own single-use lifetime."""

    __tablename__ = "operations"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=False
    )
    capability_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capability_tokens.id")
    )
    material_action_digest: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str | None] = mapped_column(Text)
    destination_operation_id: Mapped[str | None] = mapped_column(Text)
    execution_stage: Mapped[str] = mapped_column(Text, nullable=False, server_default="AUTHORIZED")
    outcome_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="UNKNOWN")
    evidence_assurance: Mapped[str] = mapped_column(Text, nullable=False, server_default="NONE")
    attempt_count: Mapped[int] = mapped_column(nullable=False, server_default="0")

    # Closeout pass, section 1: all four nullable and additive -- an
    # Operation with business_operation_identity_id NULL is not
    # identity-covered (the caller omitted business_operation_id/
    # intended_destination at submission, exactly today's default), and
    # gets none of this section's automatic resolution/enforcement --
    # only the pre-existing, explicit `replaces_operation_id` manual path
    # remains available to it (capability_service.py).
    business_operation_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_operation_identities.id")
    )
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id")
    )
    integration_contract_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_contract_versions.id")
    )
    # Self-referential: the identity's previously-governing Operation at
    # the moment THIS one was created (None for a genuine first attempt).
    # The original is never overwritten or deleted -- this is the
    # "preserve the original operation and record subsequent attempts
    # separately" chain, walkable end to end from any attempt.
    previous_attempt_operation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.id")
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "execution_stage IN ('AUTHORIZED','CLAIMED','DISPATCHED')",
            name="ck_operations_execution_stage",
        ),
        CheckConstraint(
            "outcome_status IN ('UNKNOWN','COMMITTED','TERMINALLY_NOT_COMMITTED')",
            name="ck_operations_outcome_status",
        ),
        CheckConstraint(
            "evidence_assurance IN ('NONE','REPORTED_UNVERIFIED','ADAPTER_REPORTED','MANUAL_ADJUDICATED')",
            name="ck_operations_evidence_assurance",
        ),
        UniqueConstraint("decision_id", name="uq_operations_decision"),
        Index("idx_operations_organization", "organization_id"),
        Index("idx_operations_destination_operation", "destination_operation_id"),
        Index("idx_operations_business_identity", "business_operation_identity_id"),
    )


class OperationEvidenceEvent(Base):
    """Hardening pass, section 5 (evidence provenance), extended by the
    closeout pass's section 2 (evidence acceptance rules): every dispatch
    report, observation, rejected conflicting report, or manual
    adjudication ever recorded against an Operation, kept as its own
    append-only log -- Operation.execution_stage/outcome_status are the
    current, collapsed summary; this table is the full, never-overwritten
    history of exactly who claimed what, with what assurance, that
    produced it (or, for OBSERVATION_CONFLICT_REJECTED, that did NOT
    produce it).

    `reporter_kind` distinguishes the three ways a fact can enter this
    table:
      SIGNED_ADAPTER_IDENTITY -- the real, production path (POST
        /v1/execution-receipts, gated by verify_integration_identity_
        signature): `signature_verified` is TRUE, because it genuinely
        was, by the time this row is written. Proves what that Adapter
        reported -- see Operation.evidence_assurance's own docstring for
        why this is deliberately not claimed as independent destination
        verification.
      RBAC_HUMAN -- the narrowly scoped recovery path (POST /v1/
        operations/{id}/observations or .../dispatch-evidence): an
        authenticated human's own session identity (app.dependencies.
        get_current_user_if_session), relaying a claim about an
        IntegrationIdentity it does NOT prove possession of.
        `signature_verified` is always FALSE here -- never inferred,
        never defaulted to true. Alone, this can never move Operation.
        outcome_status into a terminal value (section 2's own core
        finding: an unsigned relay must not automatically become
        verified destination truth).
      MANUAL_ADJUDICATION -- closeout pass, section 2: an authorized
        human's explicit, recorded governance decision to settle an
        outcome the automated evidence alone does not resolve --
        fundamentally different from RBAC_HUMAN (which relays a claimed
        EXTERNAL fact); this is a decision ABOUT the operation, gated by
        a separate permission (Permission.OPERATION_MANUAL_ADJUDICATE),
        and always carries `rationale` and `evidence_reference_ids`.

    `evidence_strength` is a short, human-readable label derived
    mechanically from reporter_kind + signature_verified (never a free
    string a caller can set to anything), so "the basis for any terminal
    conclusion" is always answerable by reading this table, not by
    trusting a claim.

    `reconciliation_outcome` preserves the real, computed execution_
    reconciliation_service result for THIS event even when it was not
    trusted enough to move outcome_status (section 2: "Reconciliation
    MATCHED establishes consistency with the authorized action; it does
    not independently prove destination commitment" -- both facts stay
    visible and separate, never conflated by only keeping the one that
    happened to win).

    `receipt_id` links to the real ExecutionReceiptRecord this event
    corresponds to, when there is one (every OBSERVATION event does; a
    DISPATCH_REPORTED, OBSERVATION_CONFLICT_REJECTED, or MANUAL_
    ADJUDICATION event does not)."""

    __tablename__ = "operation_evidence_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    reporter_kind: Mapped[str] = mapped_column(Text, nullable=False)
    integration_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_identities.id")
    )
    reported_by: Mapped[str] = mapped_column(Text, nullable=False)
    signature_verified: Mapped[bool] = mapped_column(nullable=False)
    destination: Mapped[str | None] = mapped_column(Text)
    destination_operation_id: Mapped[str | None] = mapped_column(Text)
    claimed_status: Mapped[str | None] = mapped_column(Text)
    reconciliation_outcome: Mapped[str | None] = mapped_column(Text)
    evidence_strength: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    evidence_reference_ids: Mapped[list | None] = mapped_column(JSONB)
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_receipts.id")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('DISPATCH_REPORTED','OBSERVATION','OBSERVATION_CONFLICT_REJECTED','MANUAL_ADJUDICATION')",
            name="ck_operation_evidence_events_type",
        ),
        CheckConstraint(
            "reporter_kind IN ('SIGNED_ADAPTER_IDENTITY','RBAC_HUMAN','MANUAL_ADJUDICATION')",
            name="ck_operation_evidence_events_reporter_kind",
        ),
        Index("idx_operation_evidence_events_organization", "organization_id"),
        Index("idx_operation_evidence_events_operation", "operation_id"),
    )


class DestinationDuplicatePreventionGuarantee(Base):
    """Product lifecycle vertical slice: the ONE other way (besides
    Operation.outcome_status == TERMINALLY_NOT_COMMITTED) a replacement
    attempt is ever reported safe by services/operation_service.py's
    evaluate_replacement_safety -- and deliberately a HUMAN-DOCUMENTED
    fact, never auto-inferred from anything a destination merely claims in
    passing (e.g. a generic "idempotent" flag on an adapter contract).
    Section 8's own instruction: "Do not treat a generic idempotency claim
    as sufficient without defining its scope and retention" -- `scope_
    description` and `retention_until` are both required, non-optional
    columns for exactly that reason; a guarantee with no stated scope or
    expiry is not representable in this table at all, by construction.

    Hardening pass, section 3: `restricted_to_integration_identity_id`
    and `restricted_to_enforcement_binding_id` are additive, nullable --
    when set, evaluate_replacement_safety's own enforcement hook (called
    from capability_service.issue_capability_for_decision's new, optional
    `replaces_operation_id` parameter) requires the REPLACEMENT decision's
    own identity/binding to match exactly, closing the gap where "any
    permitted attempt" could use an identity the guarantee never actually
    covered. Left NULL only for a genuinely destination-wide guarantee (a
    real but weaker case -- flagged as such wherever it's read, never
    treated as equivalent to a scoped one).

    One row per Operation (`uq_duplicate_prevention_operation`) -- a
    guarantee is specific to the exact operation_id it covers, never a
    blanket property of a destination or integration."""

    __tablename__ = "destination_duplicate_prevention_guarantees"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.id"), nullable=False
    )
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    scope_description: Mapped[str] = mapped_column(Text, nullable=False)
    retention_until: Mapped[datetime] = mapped_column(nullable=False)
    documented_by: Mapped[str] = mapped_column(Text, nullable=False)
    documented_at: Mapped[datetime] = mapped_column(server_default=func.now())
    restricted_to_integration_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_identities.id")
    )
    restricted_to_enforcement_binding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enforcement_bindings.id")
    )

    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_duplicate_prevention_operation"),
        Index("idx_duplicate_prevention_organization", "organization_id"),
    )



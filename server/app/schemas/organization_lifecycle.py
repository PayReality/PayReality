from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.users import UserResponse


class OrganizationLifecycleResponse(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime
    deactivated_at: datetime | None
    deactivated_by: str | None
    archived_at: datetime | None
    archived_by: str | None

    @classmethod
    def from_model(cls, organization):
        return cls(
            id=organization.id,
            name=organization.name,
            status=organization.status,
            created_at=organization.created_at,
            deactivated_at=organization.deactivated_at,
            deactivated_by=organization.deactivated_by,
            archived_at=organization.archived_at,
            archived_by=organization.archived_by,
        )


class CreateOrganizationRequest(BaseModel):
    name: str
    owner_email: str
    owner_name: str


class CreateOrganizationResponse(BaseModel):
    organization: OrganizationLifecycleResponse
    owner: UserResponse
    # Shown exactly once, at creation time -- the same disclosed,
    # no-email-delivery-yet pattern users.CreateUserResponse already
    # established for a newly created User's first credential.
    temporary_password: str


class OrganizationActionRequest(BaseModel):
    """Deactivate/reactivate/archive all take the same shape: an
    optional free-text actor, matching the Agent/RuntimePolicy lifecycle
    actions' own ActorReasonRequest-style bodies."""

    actor: str | None = None


class InvitationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    email: str
    role: str
    status: str
    invited_by: str | None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None

    @classmethod
    def from_model(cls, invitation):
        return cls(
            id=invitation.id,
            organization_id=invitation.organization_id,
            email=invitation.email,
            role=invitation.role,
            status=invitation.status,
            invited_by=invitation.invited_by,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
        )


class InviteMemberRequest(BaseModel):
    email: str
    role: str


class InviteMemberResponse(BaseModel):
    invitation: InvitationResponse
    # Shown exactly once -- this platform sends no email itself; the
    # inviter delivers this however they choose (see
    # organization_lifecycle_service.invite_member's own docstring).
    raw_token: str


class AcceptInvitationRequest(BaseModel):
    token: str
    name: str
    password: str


class AcceptInvitationResponse(BaseModel):
    user: UserResponse

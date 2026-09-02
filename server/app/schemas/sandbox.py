from pydantic import BaseModel


class CreateSandboxRequest(BaseModel):
    email: str
    name: str | None = None


class CreateSandboxResponse(BaseModel):
    """Everything a brand-new external developer needs in one response:
    an organization_id for reference, a ready-to-use API key (for the
    SDK), and a dashboard login (for anyone who wants the UI instead).
    Both credentials are shown exactly once, the same discipline every
    other newly minted secret in this codebase already holds itself to."""

    organization_id: str
    organization_name: str
    api_key: str
    owner_email: str
    owner_temporary_password: str
    starter_policy_key: str

"""SDK configuration and the local credential store.

An Agent's certificate_id and agent_id are server-assigned identifiers a
developer should never have to copy/paste or manage by hand
(SDK_SECURITY.md explains why they're stored locally rather than
re-derived every time). This module owns that small local JSON file;
nothing here ever leaves the machine it runs on.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .exceptions import ConfigurationError

DEFAULT_BASE_URL = "https://api.aisecurewatch.com"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_RETRY_COUNT = 3


def default_credentials_path() -> Path:
    return Path(os.environ.get("PAYREALITY_HOME", Path.home() / ".payreality")) / "credentials.json"


@dataclass
class Configuration:
    """Every knob `Agent(...)` accepts. `api_key` is the same operator
    credential every administrative action in this platform already
    uses (SDK_SECURITY.md); it is required only for `register()`, not
    for `authorize()`, which authenticates purely via the agent's own
    signature.

    `organization_id`: PayReality Enterprise v1.0 (Milestone 2, Multi-
    Tenant Foundation) made the operator key platform-admin-only -- it
    no longer belongs to, or defaults to, any single organization. Every
    operator-key-authenticated call now requires an explicit target
    organization (`X-PayReality-Organization-Id`); this SDK previously
    had no concept of "organization" at all (confirmed in
    MULTI_TENANT_ARCHITECTURE_VERIFICATION.md), so every `register()`
    call was silently broken against a real multi-tenant deployment
    until this field existed to carry it."""

    api_key: str | None = None
    private_key: str | None = None
    organization_id: str | None = None
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    retry_count: int = DEFAULT_RETRY_COUNT
    credentials_path: Path = field(default_factory=default_credentials_path)

    def __post_init__(self):
        if self.retry_count < 0:
            raise ConfigurationError("retry_count must be zero or greater.")
        if self.timeout <= 0:
            raise ConfigurationError("timeout must be greater than zero.")
        self.base_url = self.base_url.rstrip("/")


class CredentialStore:
    """One JSON file, keyed by public key, holding what `register()`
    learned from the server for that key: its agent_id, certificate_id,
    and which principal it acts for. Looking this up by public key
    (rather than by name) means it stays correct even if a developer
    reuses a private key across differently-named `Agent` instances."""

    def __init__(self, path: Path):
        self._path = path

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def get(self, public_key_b64: str) -> dict[str, Any] | None:
        return self._read().get(public_key_b64)

    def save(self, public_key_b64: str, record: dict[str, Any]) -> None:
        data = self._read()
        data[public_key_b64] = record
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass  # best-effort on platforms without POSIX permissions (e.g. Windows)

    def delete(self, public_key_b64: str) -> None:
        """Phase 9: used by Agent.rotate_keys() to drop the entry keyed
        by the old (now-rotated-away) public key once the new one is
        saved. Not an error if the key was never stored."""
        data = self._read()
        if public_key_b64 in data:
            del data[public_key_b64]
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

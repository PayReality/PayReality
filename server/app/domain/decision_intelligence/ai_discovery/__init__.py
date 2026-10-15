"""AI-assisted discovery of recurring uncertainty patterns and candidate
priority questions from real Decision Intelligence case data.

Follows the exact vendor-neutrality pattern already established by
domain/ai_policy_builder/ and domain/ai_authority_builder/: a `Protocol`
(provider.py) every provider implements, a deterministic `FakeDiscoveryProvider`
that needs no API key and no network access (fake_provider.py, the path
most deployments without ANTHROPIC_API_KEY actually run), and a real,
Claude-backed provider (claude_provider.py) behind the identical
runtime-selection logic the sibling features' own routers use (see
routers/decision_intelligence/discovery.py's `_provider()`).

The one hard, non-negotiable constraint repeated throughout this package
and its caller (services/di_discovery_service.py): a provider here NEVER
writes a real DIPattern or DIQuestion row, directly or indirectly. It only
ever produces in-memory candidate dataclasses; turning one into a real,
authoritative Pattern/Question happens exclusively through an explicit
human accept action (di_discovery_service.accept_suggestion)."""

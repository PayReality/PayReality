import pytest

from payreality.configuration import Configuration, CredentialStore
from payreality.exceptions import ConfigurationError


def test_configuration_defaults():
    config = Configuration()
    assert config.base_url == "https://api.aisecurewatch.com"
    assert config.timeout == 10.0
    assert config.retry_count == 3
    assert config.organization_id is None


def test_configuration_strips_trailing_slash_from_base_url():
    config = Configuration(base_url="https://example.com/")
    assert config.base_url == "https://example.com"


def test_configuration_rejects_negative_retry_count():
    with pytest.raises(ConfigurationError):
        Configuration(retry_count=-1)


def test_configuration_rejects_non_positive_timeout():
    with pytest.raises(ConfigurationError):
        Configuration(timeout=0)


def test_credential_store_round_trip(credentials_path):
    store = CredentialStore(credentials_path)
    assert store.get("pubkey-a") is None

    store.save("pubkey-a", {"agent_id": "1", "certificate_id": "2"})
    assert store.get("pubkey-a") == {"agent_id": "1", "certificate_id": "2"}
    assert store.get("pubkey-b") is None


def test_credential_store_handles_multiple_keys(credentials_path):
    store = CredentialStore(credentials_path)
    store.save("pubkey-a", {"agent_id": "1"})
    store.save("pubkey-b", {"agent_id": "2"})
    assert store.get("pubkey-a") == {"agent_id": "1"}
    assert store.get("pubkey-b") == {"agent_id": "2"}


def test_credential_store_survives_corrupt_file(credentials_path):
    credentials_path.write_text("not valid json {{{", encoding="utf-8")
    store = CredentialStore(credentials_path)
    assert store.get("anything") is None

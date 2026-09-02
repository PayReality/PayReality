"""Developer Distribution & Sandbox v1: a developer can determine their
installed SDK version, and the version is resolved from real package
metadata (single source of truth), not one of several hand-duplicated
literals that could silently drift apart.
"""

import re

import payreality
from payreality.agent import _SDK_VERSION


def test_top_level_version_attribute_is_a_real_semver_string():
    assert re.match(r"^\d+\.\d+\.\d+", payreality.__version__)


def test_version_is_exported_from_all():
    assert "__version__" in payreality.__all__


def test_agent_module_and_top_level_version_agree():
    """The one property that actually matters after removing the
    duplication: both resolve to the exact same value, because both now
    resolve it the same way (installed package metadata), not two
    hand-maintained literals that happened to still match."""
    assert _SDK_VERSION == payreality.__version__

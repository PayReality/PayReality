"""A real, ephemeral OPA server for integration tests in this directory.

Skips (rather than fails) when no `opa` binary can be found, so CI
environments without OPA installed get an honest "skipped: opa binary not
found," never a false pass from a mocked-out check pretending to be a
real one. Locate an OPA binary via PATH first (the portable path, and
what CI should use once server/.github workflow installs one), falling
back to the known WinGet install location on this Windows dev machine.
"""

import shutil
import socket
import subprocess
import time
import uuid

import httpx
import pytest

_WINDOWS_WINGET_OPA_FALLBACK = (
    r"C:\Users\user\AppData\Local\Microsoft\WinGet\Packages"
    r"\open-policy-agent.opa_Microsoft.Winget.Source_8wekyb3d8bbwe\opa.exe"
)


def _find_opa_binary() -> str | None:
    found = shutil.which("opa")
    if found:
        return found
    import os

    if os.path.exists(_WINDOWS_WINGET_OPA_FALLBACK):
        return _WINDOWS_WINGET_OPA_FALLBACK
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def opa_url():
    opa_binary = _find_opa_binary()
    if opa_binary is None:
        pytest.skip("opa binary not found on PATH or at the known local fallback location")

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [opa_binary, "run", "--server", "--addr", f"127.0.0.1:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(f"{base_url}/health", timeout=1)
                if resp.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            proc.terminate()
            pytest.skip("opa server did not become healthy in time")

        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# --- Real PostgreSQL (PayReality 1.0 Audit finding G01, verification-
# closure pass) -------------------------------------------------------------
#
# The G01 concurrency fix relies on a REAL row-level lock
# (SELECT ... FOR UPDATE), which SQLite cannot meaningfully exercise (it
# compiles the clause away as a no-op). This fixture points tests at the
# project's own existing docker-compose Postgres service -- reused, not a
# new, separate test-infrastructure invention -- creating one throwaway
# database per test session and migrating it with the project's real
# Alembic chain (so the schema under test, including the `evidence.sequence`
# column/index from migration 741abf7b0146, is identical to what a real
# deployment runs), then dropping it afterward.
#
# Skips (never fails) when Postgres isn't reachable, with the exact command
# to start it printed in the skip reason -- matching this file's own
# opa_url fixture's "skip honestly, don't fake it" convention. To run this
# for real:
#
#   docker compose up -d postgres
#   (from the repository root; ADMIN_API_KEY/EVIDENCE_SIGNING_KEY_B64 need
#   only be set to any placeholder value to satisfy compose's own
#   variable interpolation for the unrelated `server` service in the same
#   file -- postgres itself does not use them)
_POSTGRES_ADMIN_URL = "postgresql://payreality:payreality_dev@localhost:5432/payreality_dev"


def _postgres_reachable() -> bool:
    try:
        import psycopg

        with psycopg.connect(_POSTGRES_ADMIN_URL, connect_timeout=2):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def postgres_url():
    if not _postgres_reachable():
        pytest.skip(
            "Real PostgreSQL not reachable at "
            f"{_POSTGRES_ADMIN_URL} -- start it with `docker compose up -d postgres` "
            "from the repository root (ADMIN_API_KEY/EVIDENCE_SIGNING_KEY_B64 env vars "
            "need any placeholder value to satisfy compose's own interpolation)."
        )

    import psycopg

    db_name = f"payreality_test_{uuid.uuid4().hex[:12]}"
    admin_conn = psycopg.connect(_POSTGRES_ADMIN_URL, autocommit=True)
    try:
        admin_conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        admin_conn.close()

    test_url = f"postgresql+psycopg://payreality:payreality_dev@localhost:5432/{db_name}"
    import os
    import sys
    from pathlib import Path

    server_dir = Path(__file__).resolve().parents[2]  # .../server/tests/integration/conftest.py -> .../server
    full_env = dict(os.environ)
    full_env["DATABASE_URL"] = test_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(server_dir),
        env=full_env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Clean up the half-migrated throwaway database before failing loudly.
        cleanup_conn = psycopg.connect(_POSTGRES_ADMIN_URL, autocommit=True)
        try:
            cleanup_conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        finally:
            cleanup_conn.close()
        raise RuntimeError(f"alembic upgrade head failed against {db_name}:\n{result.stdout}\n{result.stderr}")

    try:
        yield test_url
    finally:
        cleanup_conn = psycopg.connect(_POSTGRES_ADMIN_URL, autocommit=True)
        try:
            cleanup_conn.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (db_name,))
            cleanup_conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        finally:
            cleanup_conn.close()

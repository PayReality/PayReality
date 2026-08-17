"""Unit tests for the Authority Intelligence Service (Authority
Intelligence Program, Phase 1): the safe-no-op behaviour when Azure AI
Search / Blob Storage aren't configured (the default for every
environment that hasn't had modules/ai-foundry / modules/ai-search
applied), and the request-building logic against injected fake clients
-- the same dependency-injection convention this whole codebase already
uses, not a mocking library. The real, configured path against a live
Azure Storage account / Search service is verified against the real
deployed resources instead (see test_ai_authority_builder.py's own
docstring for the same split already established for Postgres)."""

import uuid

from app.services import authority_intelligence_service as svc


# --- Safe no-op when unconfigured (the default for every environment) --


def test_upload_document_to_blob_returns_none_when_unconfigured():
    assert svc.upload_document_to_blob(uuid.uuid4(), uuid.uuid4(), "f.txt", b"data") is None


def test_index_document_does_nothing_when_unconfigured():
    # Must not raise -- that's the entire guarantee.
    svc.index_document(uuid.uuid4(), uuid.uuid4(), "f.txt", "text", "content", None)


def test_retrieve_corpus_text_returns_none_when_unconfigured():
    assert svc.retrieve_corpus_text(uuid.uuid4()) is None


def test_ensure_search_index_does_nothing_when_unconfigured():
    svc.ensure_search_index()


# --- Request-building logic, against injected fake clients ------------


class _FakeContainerClient:
    def __init__(self):
        self.uploaded = []

    def upload_blob(self, *, name, data, overwrite):
        self.uploaded.append({"name": name, "data": data, "overwrite": overwrite})


class _FakeBlobServiceClient:
    def __init__(self):
        self.container = _FakeContainerClient()

    def get_container_client(self, name):
        self.container_name_requested = name
        return self.container


def test_upload_document_to_blob_uses_a_deterministic_path_and_the_configured_container():
    """Milestone 3 (Enterprise Surface Isolation): "unscoped" is the
    literal organization segment for the "no organization set" legacy
    scope -- never a real UUID an organization_id could equal, the same
    "None is its own valid scope" convention every other org-scoping
    function in this codebase already follows."""
    client = _FakeBlobServiceClient()
    corpus_id, document_id = uuid.uuid4(), uuid.uuid4()

    blob_path = svc.upload_document_to_blob(corpus_id, document_id, "memo.pdf", b"bytes", client=client)

    assert blob_path == f"authority-corpora/unscoped/{corpus_id}/{document_id}-memo.pdf"
    assert client.container.uploaded[0]["name"] == blob_path
    assert client.container.uploaded[0]["data"] == b"bytes"


def test_upload_document_to_blob_prefixes_the_path_with_the_given_organization():
    client = _FakeBlobServiceClient()
    corpus_id, document_id, organization_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    blob_path = svc.upload_document_to_blob(
        corpus_id, document_id, "memo.pdf", b"bytes", organization_id=organization_id, client=client
    )

    assert blob_path == f"authority-corpora/{organization_id}/{corpus_id}/{document_id}-memo.pdf"


class _RaisingBlobServiceClient:
    def get_container_client(self, name):
        raise RuntimeError("simulated Azure outage")


def test_upload_document_to_blob_returns_none_on_failure_instead_of_raising():
    result = svc.upload_document_to_blob(
        uuid.uuid4(), uuid.uuid4(), "f.txt", b"data", client=_RaisingBlobServiceClient()
    )
    assert result is None


class _FakeSearchClient:
    def __init__(self, search_results=None):
        self.uploaded_documents = []
        self._search_results = search_results or []
        self.last_search_filter = None

    def upload_documents(self, *, documents):
        self.uploaded_documents.extend(documents)

    def search(self, *, search_text, filter):
        self.last_search_filter = filter
        return self._search_results


def test_index_document_uploads_the_expected_fields():
    client = _FakeSearchClient()
    corpus_id, document_id = uuid.uuid4(), uuid.uuid4()

    svc.index_document(corpus_id, document_id, "memo.pdf", "pdf", "extracted text", "some/blob/path", client=client)

    assert client.uploaded_documents == [
        {
            "id": str(document_id),
            "corpus_id": str(corpus_id),
            "organization_id": "",
            "document_id": str(document_id),
            "filename": "memo.pdf",
            "format": "pdf",
            "content": "extracted text",
            "blob_path": "some/blob/path",
        }
    ]


def test_index_document_stamps_the_given_organization_id():
    client = _FakeSearchClient()
    corpus_id, document_id, organization_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    svc.index_document(
        corpus_id, document_id, "memo.pdf", "pdf", "extracted text", "some/blob/path",
        organization_id=organization_id, client=client,
    )

    assert client.uploaded_documents[0]["organization_id"] == str(organization_id)


def test_retrieve_corpus_text_filters_by_corpus_id_and_organization_id_and_concatenates_with_file_headers():
    corpus_id = uuid.uuid4()
    client = _FakeSearchClient(
        search_results=[
            {"filename": "doa.txt", "content": "The Controller may approve up to $50,000.", "corpus_id": str(corpus_id), "organization_id": ""},
            {"filename": "matrix.csv", "content": "role,limit\nController,75000", "corpus_id": str(corpus_id), "organization_id": ""},
        ]
    )

    text = svc.retrieve_corpus_text(corpus_id, client=client)

    assert client.last_search_filter == f"corpus_id eq '{corpus_id}' and organization_id eq ''"
    assert "=== FILE: doa.txt ===" in text
    assert "=== FILE: matrix.csv ===" in text
    assert "$50,000" in text
    assert text.index("doa.txt") < text.index("matrix.csv")


def test_retrieve_corpus_text_filters_by_the_given_organization_id():
    corpus_id, organization_id = uuid.uuid4(), uuid.uuid4()
    client = _FakeSearchClient(search_results=[
        {"filename": "doa.txt", "content": "text", "corpus_id": str(corpus_id), "organization_id": str(organization_id)}
    ])

    svc.retrieve_corpus_text(corpus_id, organization_id=organization_id, client=client)

    assert client.last_search_filter == f"corpus_id eq '{corpus_id}' and organization_id eq '{organization_id}'"


# --- Milestone 15 (Workstream 11 hardening): the defense-in-depth check ---
# that no longer trusts the query-side filter alone -------------------------


def test_retrieve_corpus_text_drops_a_result_whose_organization_id_does_not_match():
    """Simulates the index's own filter being bypassed or misconfigured --
    a cross-tenant result must never reach the caller even if the Search
    query itself somehow returned it."""
    corpus_id, organization_id, other_org_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    client = _FakeSearchClient(search_results=[
        {"filename": "mine.txt", "content": "mine", "corpus_id": str(corpus_id), "organization_id": str(organization_id)},
        {"filename": "not-mine.txt", "content": "someone else's", "corpus_id": str(corpus_id), "organization_id": str(other_org_id)},
    ])

    text = svc.retrieve_corpus_text(corpus_id, organization_id=organization_id, client=client)

    assert "mine.txt" in text
    assert "not-mine.txt" not in text
    assert "someone else's" not in text


def test_retrieve_corpus_text_drops_a_result_whose_corpus_id_does_not_match():
    corpus_id, other_corpus_id, organization_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    client = _FakeSearchClient(search_results=[
        {"filename": "wrong-corpus.txt", "content": "wrong", "corpus_id": str(other_corpus_id), "organization_id": str(organization_id)},
    ])

    text = svc.retrieve_corpus_text(corpus_id, organization_id=organization_id, client=client)

    assert text is None


def test_retrieve_corpus_text_returns_none_not_empty_string_when_nothing_indexed():
    """None (not "") distinguishes "fall back to Postgres" from "this
    corpus genuinely has no text," which would otherwise be
    indistinguishable to run_extraction's caller."""
    client = _FakeSearchClient(search_results=[])
    assert svc.retrieve_corpus_text(uuid.uuid4(), client=client) is None


class _RaisingSearchClient:
    def search(self, *, search_text, filter):
        raise RuntimeError("simulated Azure outage")


def test_retrieve_corpus_text_returns_none_on_failure_instead_of_raising():
    assert svc.retrieve_corpus_text(uuid.uuid4(), client=_RaisingSearchClient()) is None

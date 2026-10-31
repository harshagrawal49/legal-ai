"""Document routes with the database and LLM replaced by fakes."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_case
from app.db import get_db
from app.llm.schemas import DocumentFacts, SourceRef
from app.main import app
from app.models import Case
from app.services import documents
from eval.samples import SAMPLES, make_pdf
from eval.scans import make_photo, make_scanned_pdf


class FakeOcr:
    """Stands in for Tesseract/PaddleOCR: returns the receipt text, as a good scan would."""

    name = "fake"

    def read(self, image):
        from app.services.ocr import OcrResult

        return OcrResult(SAMPLES["advance_receipt.pdf"][0], 91.0, self.name)


class FakeSession:
    def commit(self):
        pass


@pytest.fixture
def case(monkeypatch):
    case = Case(id=uuid.uuid4(), user_id="dev-user", fact_sheet={})
    case.documents = []
    app.dependency_overrides[get_case] = lambda: case
    app.dependency_overrides[get_db] = lambda: FakeSession()

    def fake_structured(output_format, system, user, **kwargs):
        assert output_format is DocumentFacts and '<page number="1">' in user
        return DocumentFacts(
            document_type="receipt", document_date="2023-03-15",
            document_date_source=SourceRef(page=1, excerpt="Date: 15/03/2023"),
            parties=[], property_identifiers=[], amounts=[], events=[], clauses=[],
            referenced_documents=[], uncertainties=[],
        )

    monkeypatch.setattr(documents, "structured", fake_structured)

    def extract_now(document_id, pdf=None):  # the real one opens its own DB session
        doc = next(d for d in case.documents if d.id == document_id)
        if pdf is not None:
            documents.run_ocr(doc, pdf, engine=FakeOcr())
        if doc.status == "processing":
            documents._run_extraction(doc)

    monkeypatch.setattr(documents, "extract_in_background", extract_now)
    yield case
    app.dependency_overrides.clear()


client = TestClient(app)


def _upload(case, data: bytes, name="r.pdf", content_type="application/pdf"):
    return client.post(f"/cases/{case.id}/documents", files={"file": (name, data, content_type)})


def test_upload_extract_list_get_delete(case):
    resp = _upload(case, make_pdf(SAMPLES["advance_receipt.pdf"]))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Text is ready at once; facts are extracted in the background.
    assert body["status"] == "processing" and body["page_count"] == 1
    doc_id = body["id"]
    detail = client.get(f"/cases/{case.id}/documents/{doc_id}").json()
    assert detail["status"] == "processed"
    assert detail["facts"]["document_date_source"]["verified"] is True

    assert [d["id"] for d in client.get(f"/cases/{case.id}/documents").json()] == [doc_id]
    assert "123/A" in client.get(f"/cases/{case.id}/documents/{doc_id}").json()["pages"][0]
    evidence = client.get(f"/cases/{case.id}/evidence").json()
    assert evidence["timeline"][0]["source"]["document_id"] == doc_id

    assert client.delete(f"/cases/{case.id}/documents/{doc_id}").status_code == 204
    assert client.get(f"/cases/{case.id}/documents").json() == []
    assert client.get(f"/cases/{case.id}/documents/{doc_id}").status_code == 404


def test_non_pdf_is_rejected_and_not_stored(case):
    resp = _upload(case, b"plain text", name="notes.txt", content_type="text/plain")
    assert resp.status_code == 415
    assert resp.json()["detail"] == "Only PDF, JPG or PNG files are supported."
    assert case.documents == []


def test_damaged_pdf_is_stored_as_failed(case):
    resp = _upload(case, b"%PDF-1.7 broken")
    assert resp.status_code == 201
    assert resp.json()["status"] == "failed" and "damaged" in resp.json()["error"]


@pytest.fixture
def ocr_installed(monkeypatch):
    monkeypatch.setattr(documents.ocr, "get_engine", lambda: FakeOcr())


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_photo_upload_is_ocrd_in_the_background(case, ocr_installed, fmt):
    resp = _upload(case, make_photo("receipt photo"), name=f"receipt.{fmt.lower()}", content_type=f"image/{fmt.lower()}")
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "processing" and resp.json()["page_info"] == [{"source": "ocr_pending"}]
    detail = client.get(f"/cases/{case.id}/documents/{resp.json()['id']}").json()
    assert detail["status"] == "processed" and detail["ocr_pages"] == 1
    assert detail["page_info"] == [{"source": "ocr", "engine": "fake", "confidence": 91.0}]
    assert "123/A" in detail["pages"][0]
    # The evidence pack says the page came from OCR, and every source on it is marked.
    evidence = client.get(f"/cases/{case.id}/evidence").json()
    assert any(f["kind"] == "ocr_used" for f in evidence["flags"])
    assert evidence["timeline"][0]["source"]["from_ocr"] is True


def test_scanned_pdf_upload(case, ocr_installed):
    resp = _upload(case, make_scanned_pdf(SAMPLES["advance_receipt.pdf"]), name="scan.pdf")
    doc = client.get(f"/cases/{case.id}/documents/{resp.json()['id']}").json()
    assert doc["status"] == "processed" and doc["ocr_pages"] == 1


def test_routes_are_in_openapi():
    paths = app.openapi()["paths"]
    assert "/cases/{case_id}/documents" in paths
    assert "/cases/{case_id}/evidence" in paths
    assert "/cases/{case_id}/brief" in paths

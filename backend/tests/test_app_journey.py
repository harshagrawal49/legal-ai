"""The Android app's main journey against the real API handlers, in the order the screens call them.

Database and LLM are faked (no Postgres or API key needed). After each call, the response is checked
for every field the app's Kotlin model requires (android/.../data/Models.kt), so a backend change that
would break decoding in the app fails here.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_case
from app.db import get_db
from app.llm.schemas import BriefSuggestions, DocumentFacts, DocumentUnderstanding, SourceRef
from app.main import app
from app.models import Case, ChatMessage
from app.services import advisor, brief, documents, ocr, understanding
from eval.samples import SAMPLES, make_pdf
from eval.scans import make_photo

MODELS_KT = Path(__file__).resolve().parents[2] / "android/app/src/main/java/com/nyaya/legal/data/Models.kt"


def required_fields(kotlin_class: str) -> set[str]:
    """JSON names of the fields a Kotlin @Serializable class requires (no default value)."""
    src = MODELS_KT.read_text()
    m = re.search(rf"data class {kotlin_class}\(\n(.*?)\n\)", src, re.S) or re.search(rf"data class {kotlin_class}\(([^\n]*)\)", src)
    assert m, kotlin_class
    out = set()
    for part in re.split(r",\s*\n|,\s+(?=@|val )", m.group(1)):
        f = re.match(r'\s*(?:@SerialName\("([^"]+)"\)\s*)?val (\w+):\s*[^=]+$', part.split("//")[0].strip().rstrip(","))
        if f:
            out.add(f.group(1) or f.group(2))
    return out


def decodes(payload: dict, kotlin_class: str) -> None:
    missing = required_fields(kotlin_class) - set(payload)
    assert not missing, f"{kotlin_class} would fail to decode: missing {missing}"


class FakeOcr:
    name = "fake"

    def read(self, image):
        return ocr.OcrResult(SAMPLES["advance_receipt.pdf"][0], 90.0, self.name)


class FakeSession:
    def add(self, obj):
        obj.created_at = obj.updated_at = datetime.now(timezone.utc)

    def commit(self):
        pass


@pytest.fixture
def world(monkeypatch):
    case = Case(id=uuid.uuid4(), user_id="dev-user", title="Plot dispute", status="intake", fact_sheet={},
                intake_inputs=[], created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    case.documents, case.results, case.messages = [], [], []

    def fake_structured(fmt, system, user, **kwargs):
        if fmt is DocumentFacts:
            return DocumentFacts(
                document_type="receipt", document_date="2023-03-15", document_date_source=SourceRef(page=1, excerpt="Date: 15/03/2023"),
                parties=[], property_identifiers=[], amounts=[], events=[], clauses=[], referenced_documents=[], uncertainties=[],
            )
        if fmt is DocumentUnderstanding:
            return DocumentUnderstanding(
                one_line="A receipt for an advance of Rs. 5,50,000.",
                summary=[{"text": "Meera Iyer paid Rs. 5,50,000 as advance.", "pages": [1], "quote": "a sum of Rs. 5,50,000/-"}],
                clause_explanations=[], terms_in_context=[], things_to_check=[],
            )
        if fmt is BriefSuggestions:
            return BriefSuggestions(advocate_questions=["Is the advance refundable?"], checklist=["Find the agreement"])
        raise AssertionError(f"unexpected LLM call for {fmt}")

    for module in (documents, understanding, brief):
        monkeypatch.setattr(module, "structured", fake_structured)
    monkeypatch.setattr(ocr, "get_engine", lambda: FakeOcr())

    def extract_now(document_id, pdf=None):  # the real background task opens its own DB session
        doc = next(d for d in case.documents if d.id == document_id)
        if pdf is not None:
            documents.run_ocr(doc, pdf, engine=FakeOcr())
        if doc.status == "processing":
            documents._run_extraction(doc)
        if doc.status == "processed":
            understanding.ensure_understanding(doc, "en")

    monkeypatch.setattr(documents, "extract_in_background", extract_now)
    app.dependency_overrides[get_case] = lambda: case
    app.dependency_overrides[get_db] = lambda: FakeSession()
    yield case
    app.dependency_overrides.clear()


def test_journey_upload_explain_evidence_brief_chat(world, monkeypatch):
    case = world
    client = TestClient(app)
    base = f"/cases/{case.id}"

    # My documents: upload a PDF and a phone photo (Uploads.kt sends multipart field "file").
    pdf = client.post(f"{base}/documents", files={"file": ("receipt.pdf", make_pdf(SAMPLES["advance_receipt.pdf"]), "application/pdf")})
    photo = client.post(f"{base}/documents", files={"file": ("photo.jpg", make_photo("x"), "image/jpeg")})
    assert pdf.status_code == photo.status_code == 201
    for r in (pdf, photo):
        decodes(r.json(), "DocumentDetail")

    # The list the screen polls, then a document's detail page.
    listed = client.get(f"{base}/documents").json()
    assert [d["status"] for d in listed] == ["processed", "processed"]
    assert all(d["understood"] for d in listed)
    for d in listed:
        decodes(d, "DocumentSummary")
    detail = client.get(f"{base}/documents/{listed[1]['id']}").json()
    assert detail["ocr_pages"] == 1 and detail["page_info"][0]["source"] == "ocr"

    # Explained: cached English, then Hinglish generated on demand.
    for lang in ("en", "hinglish"):
        u = client.get(f"{base}/documents/{listed[0]['id']}/understanding", params={"lang": lang})
        assert u.status_code == 200, u.text
        body = u.json()
        decodes(body, "Understanding")
        assert body["status"] == "complete" and body["language"] == lang
        for p in body["summary"]:
            decodes(p, "ExplainedPoint")
        for t in body["terms"]:
            decodes(t, "TermExplained")
    assert client.get(f"{base}/documents/{listed[0]['id']}/understanding", params={"lang": "mr"}).status_code == 422

    # Timeline & flags, and the brief.
    ev = client.get(f"{base}/evidence").json()
    decodes(ev, "Evidence")
    for f in ev["flags"]:
        decodes(f, "Flag")
        for s in f["sources"]:
            decodes(s, "SourceRef")
    br = client.post(f"{base}/brief")
    assert br.status_code == 200, br.text
    decodes(br.json(), "Brief")
    for d in br.json()["documents"]:
        decodes(d, "BriefDocument")

    # Chat: an @ mention of a real document is accepted; the reply's sources come back in history.
    monkeypatch.setattr(advisor, "stream_reply", lambda *a, **k: iter(['event: done\ndata: {"sources": []}\n\n']))
    ok = client.post(f"{base}/chat", json={"message": f"@receipt.pdf isme kitna amount likha hai?", "mentions": [listed[0]["id"]]})
    assert ok.status_code == 200 and "event: done" in ok.text
    case.messages = [
        ChatMessage(id=1, role="user", message={}, display_text="@receipt.pdf isme kitna amount likha hai?", mentions=[listed[0]["id"]], sources=[],
                    created_at=datetime.now(timezone.utc)),
        ChatMessage(id=2, role="assistant", message={}, display_text=f"Rs. 5,50,000 [[D:{listed[0]['id']}:p1]]", mentions=[],
                    sources=advisor.sources_for(case, [{"document_id": listed[0]["id"], "page": 1}], []), created_at=datetime.now(timezone.utc)),
    ]
    history = client.get(f"{base}/chat").json()
    for m in history:
        decodes(m, "ChatMessage")
    assert history[1]["sources"][0] == {"type": "document", "document_id": listed[0]["id"], "filename": "receipt.pdf", "page": 1}
    decodes(history[1]["sources"][0], "ChatSource")

    # Delete from My documents.
    assert client.delete(f"{base}/documents/{listed[1]['id']}").status_code == 204
    assert len(client.get(f"{base}/documents").json()) == 1


def test_required_fields_parser_sees_the_app_models():
    # Guard against this test silently checking nothing if Models.kt is reformatted.
    assert {"id", "filename", "status"} <= required_fields("DocumentSummary")
    assert {"type"} == required_fields("ChatSource")
    assert {"disclaimer"} <= required_fields("Brief")

"""The case fact sheet built from the user's text AND their documents: rule-based NLP (English, Hindi), the cross-check
of LLM extraction, provenance checking, conflicts and documents-only cases (no LLM or DB needed)."""

import uuid

import pytest

from app.llm.schemas import FactSheet, IntakeResult
from app.models import Case, CaseDocument
from app.services import brief, intake, nlp
from eval.samples import SAMPLES
from eval.scans import DEVANAGARI_SAMPLES

AGREEMENT_PAGES = SAMPLES["agreement_to_sell.pdf"]
RECEIPT_PAGES = SAMPLES["advance_receipt.pdf"]


def _src(page: int, excerpt: str = "x") -> dict:
    return {"page": page, "excerpt": excerpt, "verified": True}


def _receipt() -> CaseDocument:
    return CaseDocument(
        id=uuid.uuid4(), filename="receipt.pdf", status="processed", pages=RECEIPT_PAGES, page_info=[{"source": "ocr", "confidence": 88}],
        facts={
            "document_type": "receipt", "document_date": "2023-03-15", "document_date_source": _src(1, "Date: 15/03/2023"),
            "parties": [{"name": "Meera Iyer", "stated_role": "payer", "source": _src(1)},
                        {"name": "Ravi Kulkarni", "stated_role": "recipient", "source": _src(1)}],
            "property_identifiers": [{"kind": "survey number", "value": "123/A", "source": _src(1)}],
            "amounts": [{"kind": "advance_or_earnest_money", "description": "advance", "value": "Rs. 5,50,000/-",
                         "currency": "INR", "source": _src(1)}],
            "events": [{"kind": "payment", "date": "2023-03-15", "date_as_written": "15/03/2023",
                        "description": "Advance paid by cheque", "source": _src(1)}],
            "clauses": [], "referenced_documents": [], "uncertainties": [],
            "unverified_example": None,
        },
    )


# ---------- Rule-based NLP ----------


def test_extracts_amounts_dates_and_identifiers_in_english():
    found = {(m.kind, m.normalized) for m in nlp.extract(AGREEMENT_PAGES)}
    assert ("amount", "4500000") in found and ("amount", "500000") in found and ("amount", "4000000") in found
    assert ("date", "2023-03-15") in found and ("date", "2023-09-15") in found
    assert ("property_identifier", "1234") in found


@pytest.mark.parametrize("name, expected", [
    ("rasid_hindi.pdf", {("amount", "500000"), ("date", "2023-03-15"), ("property_identifier", "1234")}),
    ("anubandh_hindi.pdf", {("amount", "4500000"), ("amount", "500000"), ("date", "2023-03-15"), ("property_identifier", "1234")}),
])
def test_extracts_from_hindi(name, expected):
    assert expected <= {(m.kind, m.normalized) for m in nlp.extract(DEVANAGARI_SAMPLES[name])}


def test_date_formats_and_impossible_dates():
    text = ["Paid on 15th March, 2023 and again on March 20, 2023 and on 01-04-2023. Not a date: 31/02/2023."]
    dates = [m.normalized for m in nlp.extract(text) if m.kind == "date"]
    assert dates == ["2023-04-01", "2023-03-15", "2023-03-20"]


def test_indian_amount_words():
    assert nlp.amount_value("Rs 4.5 lakh") == 450000
    assert nlp.amount_value("रुपये ५ लाख") == 500000
    assert nlp.amount_value("₹ 1.2 crore") == 12000000


def test_cross_check_marks_corroborated_and_possibly_missed():
    facts = {
        "document_date": "2023-03-15",
        "amounts": [{"value": "Rs. 45,00,000/-"}, {"value": "Rs. 9,99,999"}],  # the second isn't in the text
        "events": [{"date": "2023-09-15"}],
        "property_identifiers": [{"value": "Survey No. 123/4"}],
    }
    nlp.cross_check(facts, AGREEMENT_PAGES)
    assert [a["corroborated"] for a in facts["amounts"]] == [True, False]
    assert facts["events"][0]["corroborated"] and facts["property_identifiers"][0]["corroborated"]
    missed = {(m["kind"], m["value"]) for m in facts["possibly_missed"]}
    assert ("amount", "Rs. 5,00,000/-") in missed and ("amount", "Rs. 40,00,000/-") in missed
    assert all(m["source"]["page"] in (1, 2) for m in facts["possibly_missed"])


# ---------- Document facts in the intake prompt ----------


def test_document_facts_block_has_refs_and_ocr_marker():
    doc = _receipt()
    block = intake.document_facts_block([doc])
    assert f"[D:{doc.id}:p1] amount (advance or earnest money): advance: Rs. 5,50,000/- (read by OCR)" in block
    assert f"[D:{doc.id}:p1] property: survey number: 123/A" in block


# ---------- Provenance checking ----------


def test_check_sources_keeps_only_refs_supported_by_the_page():
    doc = _receipt()
    ref = f"D:{doc.id}:p1"
    sheet = {
        "parties": [{"name": "Meera Iyer", "role": "buyer", "sources": ["user", ref]},
                    {"name": "Sunil Patil", "role": "other buyer", "sources": [ref]}],  # not on the receipt
        "amounts": [{"description": "advance", "value": "Rs 5.5 lakh", "sources": [ref]},  # same value, other wording
                    {"description": "advance", "value": "Rs 6 lakh", "sources": [ref, f"D:{uuid.uuid4()}:p1"]}],
        "events": [{"date": "2023-03-15", "description": "advance paid", "sources": [ref]},
                   {"date": "2024-01-10", "description": "heard of second sale", "sources": [ref, "user"]}],
        "conflicts": [{"description": "advance", "user_says": "Rs 6 lakh", "documents_say": "Rs. 5,50,000/-", "sources": [ref]},
                      {"description": "made up", "user_says": "x", "documents_say": "y", "sources": ["D:bogus:p1"]}],
    }
    out = intake.check_sources(sheet, [doc], user_spoke=True)
    assert out["parties"][0]["sources"] == ["user", ref]
    assert out["parties"][1]["sources"] == ["unverified"]
    assert out["amounts"][0]["sources"] == [ref]
    assert out["amounts"][1]["sources"] == ["unverified"]  # neither ref supports Rs 6 lakh
    assert out["events"][0]["sources"] == [ref]
    assert out["events"][1]["sources"] == ["user"]
    assert [c["description"] for c in out["conflicts"]] == ["advance"]


def test_user_source_dropped_when_the_user_said_nothing():
    doc = _receipt()
    sheet = {"parties": [{"name": "Meera Iyer", "role": "buyer", "sources": ["user"]}], "events": [], "amounts": []}
    assert intake.check_sources(sheet, [doc], user_spoke=False)["parties"][0]["sources"] == ["unverified"]


# ---------- Running intake from text + documents ----------


def _fake_result(doc: CaseDocument) -> IntakeResult:
    ref = f"D:{doc.id}:p1"
    return IntakeResult(
        case_title="Advance paid, plot sold twice",
        fact_sheet=FactSheet(
            summary="The buyer paid an advance; the seller allegedly agreed to sell to someone else.",
            parties=[{"name": "Ravi Kulkarni", "role": "seller", "sources": [ref]}],
            events=[{"date": "2023-03-15", "description": "Advance paid", "sources": ["user", ref]}],
            amounts=[{"description": "advance", "value": "Rs. 5,50,000/-", "sources": [ref]}],
            documents=["receipt"], actions_taken=[], relief_sought=None, location="Pune", issues=[], legal_areas=[],
            search_queries=["refund of advance agreement to sell"], missing_info=[],
            conflicts=[{"description": "advance amount", "user_says": "Rs 6 lakh", "documents_say": "Rs. 5,50,000/-", "sources": [ref]}],
        ),
        questions=["The receipt says Rs 5,50,000 but you said Rs 6 lakh. Which is correct?"],
        ready_to_confirm=False,
    )


def test_intake_uses_documents_and_text(monkeypatch):
    doc = _receipt()
    case = Case(id=uuid.uuid4(), user_id="u", fact_sheet={}, intake_inputs=[{"role": "user", "text": "I paid Rs 6 lakh advance."}])
    case.documents = [doc]
    prompts_seen = []

    def fake_structured(fmt, system, user, **kwargs):
        prompts_seen.append(user)
        return _fake_result(doc)

    monkeypatch.setattr(intake, "structured", fake_structured)
    intake.run_intake(case)
    assert "I paid Rs 6 lakh" in prompts_seen[0] and f"[D:{doc.id}:p1]" in prompts_seen[0]
    assert case.fact_sheet["amounts"][0]["sources"] == [f"D:{doc.id}:p1"]
    assert case.fact_sheet["conflicts"][0]["user_says"] == "Rs 6 lakh"
    # Re-running replaces the unanswered questions instead of adding a second set.
    intake.run_intake(case)
    assert [i["role"] for i in case.intake_inputs] == ["user", "assistant"]


def test_documents_only_case(monkeypatch):
    doc = _receipt()
    case = Case(id=uuid.uuid4(), user_id="u", fact_sheet={}, intake_inputs=[])
    case.documents = []
    monkeypatch.setattr(intake, "structured", lambda *a, **k: pytest.fail("no LLM call without input"))
    assert intake.run_intake(case) is None  # nothing to build from yet

    case.documents = [doc]
    monkeypatch.setattr(intake, "structured", lambda fmt, system, user, **k: _fake_result(doc))
    intake.run_intake(case)
    # The model said "user" for the event, but the user wrote nothing: only the document ref survives.
    assert case.fact_sheet["events"][0]["sources"] == [f"D:{doc.id}:p1"]


def test_refresh_after_document_commits_and_survives_failures(monkeypatch):
    doc = _receipt()
    case = Case(id=uuid.uuid4(), user_id="u", fact_sheet={}, intake_inputs=[])
    case.documents = [doc]

    class FakeDB:
        commits = rollbacks = 0

        def get(self, model, key):
            return case

        def commit(self):
            FakeDB.commits += 1

        def rollback(self):
            FakeDB.rollbacks += 1

    monkeypatch.setattr(intake, "structured", lambda fmt, system, user, **k: _fake_result(doc))
    intake.refresh_after_document(FakeDB(), case.id)
    assert FakeDB.commits == 1 and case.title == "Advance paid, plot sold twice"

    def broken(*a, **k):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(intake, "structured", broken)
    intake.refresh_after_document(FakeDB(), case.id)  # must not raise
    assert FakeDB.rollbacks == 1


# ---------- Brief and evidence ----------


def test_brief_separates_user_only_statements_and_shows_conflicts():
    doc = _receipt()
    ref = f"D:{doc.id}:p1"
    case = Case(id=uuid.uuid4(), user_id="u", fact_sheet={
        "events": [{"date": "2023-03-15", "description": "Advance paid", "sources": ["user", ref]},
                   {"date": "2024-01", "description": "Heard the plot was sold again", "sources": ["user"]}],
        "amounts": [{"description": "advance", "value": "Rs. 5,50,000/-", "sources": [ref]}],
        "conflicts": [{"description": "advance amount", "user_says": "Rs 6 lakh", "documents_say": "Rs. 5,50,000/-", "sources": [ref]}],
    })
    case.documents = [doc]
    assert brief._user_account(case) == ["2024-01: Heard the plot was sold again"]
    (flag,) = brief.conflict_flags(case)
    assert flag["kind"] == "user_document_conflict" and "You said: Rs 6 lakh" in flag["message"]
    assert flag["sources"][0]["page"] == 1 and flag["sources"][0]["from_ocr"] is True


# ---------- API: creating a case from documents only ----------


def test_create_case_without_description_makes_no_llm_call(monkeypatch):
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    class FakeSession:
        def add(self, obj):
            obj.created_at = obj.updated_at = datetime.now(timezone.utc)
            obj.status = obj.status or "intake"
            obj.fact_sheet = obj.fact_sheet or {}

        def commit(self):
            pass

    monkeypatch.setattr(intake, "structured", lambda *a, **k: pytest.fail("no LLM call for an empty description"))
    app.dependency_overrides[get_db] = lambda: FakeSession()
    try:
        client = TestClient(app)
        resp = client.post("/cases", json={})
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "New case (from documents)" and resp.json()["pending_questions"] == []
        short = client.post("/cases", json={"description": "plot dispute"})
        assert short.status_code == 422 and "few more words" in short.json()["detail"]
    finally:
        app.dependency_overrides.clear()

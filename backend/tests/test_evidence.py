"""Chronology, flags and the brief, built from hand-written extracted facts (no LLM)."""

import uuid
from decimal import Decimal

from app.models import Case, CaseDocument
from app.services import brief
from app.services.advisor import DOC_CITATION_RE, split_document_citations
from app.services.evidence import build_flags, build_timeline, parse_amount


def _src(page: int, excerpt: str = "x", verified: bool = True) -> dict:
    return {"page": page, "excerpt": excerpt, "verified": verified}


def _doc(filename: str, facts: dict, status: str = "processed", pages: int = 2) -> CaseDocument:
    base = {
        "document_type": "other", "document_date": None, "document_date_source": None, "parties": [],
        "property_identifiers": [], "amounts": [], "events": [], "clauses": [], "referenced_documents": [],
        "uncertainties": [], "truncated_after_page": None,
    }
    return CaseDocument(id=uuid.uuid4(), filename=filename, status=status, error=None,
                        pages=["text"] * pages, facts={**base, **facts} if status == "processed" else {})


AGREEMENT = _doc("agreement.pdf", {
    "document_type": "agreement_to_sell",
    "document_date": "2023-03-15",
    "document_date_source": _src(1, "made at Pune on 15 March 2023"),
    "parties": [{"name": "Ravi Kulkarni", "stated_role": "seller", "source": _src(1)}],
    "property_identifiers": [{"kind": "Survey number", "value": "123/4", "source": _src(1)}],
    "amounts": [{"kind": "advance_or_earnest_money", "description": "advance", "value": "Rs. 5,00,000/-",
                 "currency": "INR", "source": _src(1)}],
    "events": [{"kind": "deadline", "date": "2023-09-15", "date_as_written": "15 September 2023",
                "description": "Balance due", "source": _src(2)},
               {"kind": "other", "date": None, "date_as_written": None, "description": "Possession on registration",
                "source": _src(2)}],
    "referenced_documents": [{"description": "Annexure A (receipt)", "source": _src(1)},
                             {"description": "Encumbrance certificate", "source": _src(1)}],
})
RECEIPT = _doc("receipt.pdf", {
    "document_type": "receipt",
    "document_date": "2023-03-15",
    "property_identifiers": [{"kind": "survey number", "value": "123/A", "source": _src(1)}],
    "amounts": [{"kind": "advance_or_earnest_money", "description": "advance", "value": "Rs 5.5 lakh",
                 "currency": "INR", "source": _src(1, "Rs 5.5 lakh", verified=False)}],
}, pages=1)
SCAN = CaseDocument(id=uuid.uuid4(), filename="scan.pdf", status="failed", error="No selectable text was found.",
                    pages=[], facts={})


def _kinds(flags):
    return [f["kind"] for f in flags]


def test_parse_amount_handles_indian_formats():
    assert parse_amount("Rs. 5,00,000/-") == Decimal(500000)
    assert parse_amount("Rs 5.5 lakh") == Decimal(550000)
    assert parse_amount("INR 1.2 crore") == Decimal(12000000)
    assert parse_amount("five lakh") is None
    assert parse_amount("Rs 5,00,000 and Rs 40,00,000") is None


def test_timeline_is_chronological_with_undated_last_and_sourced():
    timeline = build_timeline([RECEIPT, AGREEMENT, SCAN])
    assert [t["date"] for t in timeline] == ["2023-03-15", "2023-03-15", "2023-09-15", None]
    assert timeline[-1]["description"] == "Possession on registration"
    assert all(t["source"]["document_id"] for t in timeline)
    assert timeline[2]["source"] == {"document_id": str(AGREEMENT.id), "filename": "agreement.pdf", "page": 2,
                                    "excerpt": "x", "verified": True}


def test_flags_identifier_and_amount_differences_across_documents():
    flags = build_flags([AGREEMENT, RECEIPT])
    kinds = _kinds(flags)
    assert "property_identifier_difference" in kinds
    assert "amount_difference" in kinds
    pid = next(f for f in flags if f["kind"] == "property_identifier_difference")
    assert {s["filename"] for s in pid["sources"]} == {"agreement.pdf", "receipt.pdf"}
    # Never a conclusion, only something to check.
    assert all("fraud" not in f["message"].lower() for f in flags)


def test_same_values_written_differently_are_not_flagged():
    other = _doc("notice.pdf", {
        "property_identifiers": [{"kind": "Survey Number", "value": "123 / 4", "source": _src(1)}],
        "amounts": [{"kind": "advance_or_earnest_money", "description": "advance", "value": "Rs 5 lakh",
                     "currency": "INR", "source": _src(1)}],
    })
    kinds = _kinds(build_flags([AGREEMENT, other]))
    assert "property_identifier_difference" not in kinds
    assert "amount_difference" not in kinds


def test_flags_failures_unverified_refs_and_unmatched_references():
    flags = build_flags([AGREEMENT, RECEIPT, SCAN])
    kinds = _kinds(flags)
    assert "extraction_failure" in kinds
    assert "unverified_reference" in kinds
    unmatched = [f["message"] for f in flags if f["kind"] == "referenced_document_not_found"]
    # "Annexure A (receipt)" matches the uploaded receipt; the certificate wasn't uploaded.
    assert len(unmatched) == 1 and "Encumbrance certificate" in unmatched[0]


def test_flags_missing_property_identifier():
    doc = _doc("letter.pdf", {"document_type": "correspondence"})
    assert "missing_property_identifier" in _kinds(build_flags([doc]))


def test_document_citations_must_point_to_real_pages():
    text = f"See [[D:{AGREEMENT.id}:p2]] and [[D:{AGREEMENT.id}:p9]] and [[D:{uuid.uuid4()}:p1]]."
    valid, invalid = split_document_citations([AGREEMENT], DOC_CITATION_RE.findall(text))
    assert valid == [{"document_id": str(AGREEMENT.id), "page": 2}]
    assert len(invalid) == 2


def test_brief_separates_sections_and_falls_back_without_llm(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("no LLM")

    monkeypatch.setattr(brief, "structured", unavailable)
    case = Case(user_id="u", fact_sheet={
        "summary": "I paid an advance; the seller agreed to sell to someone else.",
        "events": [{"date": "2024-01", "description": "Heard the plot was sold to another buyer"}],
        "amounts": [], "relief_sought": "Execution of sale deed",
    })
    case.documents = [AGREEMENT, RECEIPT, SCAN]
    out = brief.build_brief(case)

    assert out["status"] == "draft" and "does not decide ownership" in out["disclaimer"]
    assert [d["status"] for d in out["documents"]] == ["processed", "processed", "failed"]
    # The receipt's amount reference wasn't verified, so it is not listed as a supported fact.
    supported = [f["text"] for f in out["document_supported_facts"]]
    assert "advance: Rs. 5,00,000/-" in supported
    assert "advance: Rs 5.5 lakh" not in supported
    assert out["user_account_not_verified"] == [
        "2024-01: Heard the plot was sold to another buyer", "Relief sought: Execution of sale deed",
    ]
    assert out["legal_sources"] == []
    assert out["suggestions_ai_generated"] is False
    assert out["advocate_questions"] and out["checklist"]

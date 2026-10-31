"""Document understanding (plain-language explanation with code checks) and chat @-mentions/sources.
The LLM is faked; what's tested is the checking around it."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.llm.schemas import DocumentUnderstanding
from app.models import Case, CaseDocument
from app.services import advisor, understanding
from eval.samples import SAMPLES

PAGES = SAMPLES["agreement_to_sell.pdf"]


def _doc() -> CaseDocument:
    return CaseDocument(
        id=uuid.uuid4(), filename="agreement.pdf", status="processed", pages=PAGES,
        page_info=[{"source": "text"}, {"source": "ocr", "confidence": 90}],
        facts={"document_type": "agreement_to_sell", "document_date": "2023-03-15", "parties": [{"name": "Ravi Kulkarni", "source": {"page": 1, "excerpt": "Ravi Kulkarni", "verified": True}}],
               "property_identifiers": [], "amounts": [], "events": [], "clauses": [], "uncertainties": [], "possibly_missed": []},
        understanding={},
    )


def _fake(**overrides) -> DocumentUnderstanding:
    base = dict(
        one_line="An agreement to sell a plot in Pune for Rs. 45,00,000.",
        summary=[
            {"text": "The total price is Rs. 45,00,000.", "pages": [1], "quote": "total sale consideration is Rs. 45,00,000"},
            {"text": "The advance was Rs. 7,00,000.", "pages": [1], "quote": "advance of Rs. 7,00,000"},  # not in the document
            {"text": "You will win this case easily.", "pages": [1], "quote": None},  # advice
            {"text": "The balance is due by 15 September 2023.", "pages": [2, 9], "quote": "on or before 15 September 2023"},
        ],
        clause_explanations=[{"label": "Clause 5: refund", "meaning": "If the seller doesn't complete the sale, the advance is refunded with interest at 12% per year.",
                              "pages": [2], "quote": "refund the advance with interest"}],
        terms_in_context=[{"term_id": "earnest_money", "why_here": "The buyer paid an advance on signing."},
                          {"term_id": "benami", "why_here": "made up"}],  # not in the document
        things_to_check=[{"text": "The agreement mentions Annexure A, a receipt.", "pages": [1], "quote": "attached as Annexure A"}],
    )
    return DocumentUnderstanding(**{**base, **overrides})


@pytest.fixture
def llm(monkeypatch):
    calls = []

    def fake(fmt, system, user, **kwargs):
        calls.append((system, user))
        return _fake()

    monkeypatch.setattr(understanding, "structured", fake)
    return calls


def test_explanation_is_checked_against_the_document(llm):
    u = understanding.build_understanding(_doc(), "en")
    texts = [p["text"] for p in u["summary"]]
    assert texts == ["The total price is Rs. 45,00,000.", "The balance is due by 15 September 2023."]
    assert {d["reason"].split(":")[0] for d in u["dropped"]} == {"advice", "values not in the document"}
    assert u["summary"][0]["verified"] is True and u["summary"][0]["from_ocr"] is False
    assert u["summary"][1]["pages"] == [2] and u["summary"][1]["from_ocr"] is True  # page 9 doesn't exist
    assert u["clauses"][0]["verified"] is True
    assert u["status"] == "complete" and u["document_type"] == "agreement_to_sell" and u["type_check"]["agrees"]


def test_terms_come_from_the_glossary_not_the_model(llm):
    u = understanding.build_understanding(_doc(), "en")
    terms = {t["id"]: t for t in u["terms"]}
    assert "benami" not in terms  # the model named it, but it isn't in the document
    assert terms["earnest_money"]["in_this_document"] == "The buyer paid an advance on signing."
    assert terms["earnest_money"]["meaning"].startswith("A part payment")  # curated text
    assert terms["agreement_to_sell"]["page"] == 1 and terms["agreement_to_sell"]["hindi"] == "विक्रय अनुबंध"


def test_language_and_prompt(llm):
    understanding.build_understanding(_doc(), "hinglish")
    system, user = llm[0]
    assert "Hinglish" in system and '<page number="1">' in user and "earnest_money" in user
    with pytest.raises(ValueError):
        understanding.build_understanding(_doc(), "mr")


def test_llm_failure_still_returns_rule_based_parts(monkeypatch):
    def down(*a, **k):
        raise RuntimeError("no LLM")

    monkeypatch.setattr(understanding, "structured", down)
    doc = _doc()
    doc.facts["possibly_missed"] = [{"kind": "amount", "value": "Rs. 40,00,000/-", "source": {"page": 2, "excerpt": "x", "verified": True}}]
    u = understanding.build_understanding(doc, "en")
    assert u["status"] == "partial" and u["summary"] == []
    assert u["one_line"].startswith("Agreement to sell dated 2023-03-15")
    assert any(t["id"] == "agreement_to_sell" for t in u["terms"])
    assert any(c["kind"] == "possibly_missed" for c in u["things_to_check"])


def test_cached_per_language(llm):
    doc = _doc()
    understanding.ensure_understanding(doc, "en")
    understanding.ensure_understanding(doc, "en")
    assert len(llm) == 1
    understanding.ensure_understanding(doc, "hi")
    understanding.ensure_understanding(doc, "en", refresh=True)
    assert len(llm) == 3 and set(doc.understanding) == {"en", "hi"}


# ---------- Chat: @ mentions and sources ----------


def test_mention_block_contains_only_referenced_documents():
    a, b = _doc(), _doc()
    b.filename = "other.pdf"
    a.understanding = {"en": {"summary": [{"text": "The price is Rs. 45,00,000.", "pages": [1]}]}}
    case = Case(id=uuid.uuid4(), user_id="u")
    case.documents = [a, b]
    block = advisor.mention_block(case, [str(a.id)])
    assert f'document_id="{a.id}"' in block and "other.pdf" not in block
    assert "The price is Rs. 45,00,000. (p.1)" in block and '<page number="2">' in block
    assert "Untrusted" in block and advisor.mention_block(case, []) == ""


def test_sources_list_for_a_reply():
    a = _doc()
    case = Case(id=uuid.uuid4(), user_id="u")
    case.documents, case.results = [a], []
    sources = advisor.sources_for(case, [{"document_id": str(a.id), "page": 2}], ["sc-1"])
    assert sources[0] == {"type": "document", "document_id": str(a.id), "filename": "agreement.pdf", "page": 2}
    assert sources[1]["type"] == "judgment" and sources[1]["judgment_id"] == "sc-1"


def test_chat_rejects_mentions_from_another_case(monkeypatch):
    from app.api.deps import get_case
    from app.main import app

    case = Case(id=uuid.uuid4(), user_id="dev-user")
    case.documents = [_doc()]
    app.dependency_overrides[get_case] = lambda: case
    monkeypatch.setattr(advisor, "stream_reply", lambda *a, **k: iter(["event: done\ndata: {}\n\n"]))
    try:
        client = TestClient(app)
        bad = client.post(f"/cases/{case.id}/chat", json={"message": "isme kya likha hai?", "mentions": [str(uuid.uuid4())]})
        assert bad.status_code == 422
        ok = client.post(f"/cases/{case.id}/chat", json={"message": "isme kya likha hai?", "mentions": [str(case.documents[0].id)]})
        assert ok.status_code == 200
    finally:
        app.dependency_overrides.clear()

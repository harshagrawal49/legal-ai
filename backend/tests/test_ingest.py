"""Judgment ingestion: the property filter (including false positives seen in real data), the dataset
parsers, and the pipeline's incremental behaviour. No network, database or embedding model needed."""

import io
import uuid
from datetime import date

import pandas as pd
import pytest

from ingest import filters, pipeline, semantic, sources
from ingest.sources import Record
from ingest.store import MemoryStore


def rec(**kw) -> Record:
    base = dict(source="sc", key=str(uuid.uuid4()), partition="2024", title="A versus B", court="Supreme Court of India",
                pdf_key="data/pdf/x.pdf")
    return Record(**{**base, **kw})


# ---------- Stage 1: metadata ----------


@pytest.mark.parametrize("description", [
    "Issue for Consideration Whether the purchaser was entitled to specific performance of the agreement to sell.",
    "Issue arose as regards the shares of the parties in the disputed land and the order of the Deputy Director of Consolidation.",
    "Whether the present acquisition of the land for the expressway was valid and compensation adequate.",
    "Allotment of land to the respondent was cancelled by the development authority.",
])
def test_stage1_keeps_property_headnotes(description):
    assert filters.stage1(rec(description=description)).verdict == "candidate"


@pytest.mark.parametrize("description", [
    "Appeal against conviction for possession of ganja under the NDPS Act; recovery of contraband.",
    "Issue arose as regards the regularisation of services and seniority of employees.",
    "Petition under the Arbitration and Conciliation Act to appoint an arbitrator.",
])
def test_stage1_rejects_look_alikes(description):
    assert filters.stage1(rec(description=description)).verdict == "reject"


def test_stage1_high_court_case_types_and_acts():
    sa = rec(source="hc", title="SA/30/2024 of X Vs Y", case_type="SA")
    crma = rec(source="hc", title="CRMA/12/2025 of X Vs State", case_type="CRMA")
    assert filters.stage1(sa).verdict == "candidate"
    assert filters.stage1(crma).verdict == "reject"
    tpa = rec(source="hc", title="WP/9/2025 of X Vs Y", case_type="WP", acts=[{"act": "Transfer of Property Act", "section": "53A"}])
    assert filters.stage1(tpa).verdict == "candidate"
    # Seen in real data: "Limitation Act s.5" (condonation of delay) on its own is not a property signal.
    delay = rec(source="hc", title="MCA/5/2025 of X Vs Y", case_type="MCA", acts=[{"act": "Limitation Act", "section": "5"}])
    assert filters.stage1(delay).verdict == "reject"


def test_societies_registration_act_is_not_the_registration_act():
    # Seen in real data: a judicial employees' association "registered under the Societies Registration Act".
    assert "Registration Act" not in filters._statutes("a society registered under the Societies Registration Act, 1860")
    assert "Registration Act" in filters._statutes("the sale deed was not registered as required by the Registration Act")


# ---------- Stage 2: full text ----------

PROPERTY_TEXT = (
    "This second appeal arises from a suit for specific performance of an agreement to sell the suit property. "
    "The plaintiff paid earnest money and was ready and willing to pay the balance consideration. The defendant "
    "executed a sale deed in favour of a third party. Under Section 54 of the Transfer of Property Act and the "
    "Specific Relief Act, the plaintiff seeks a decree. The plaintiff also seeks a permanent injunction and "
    "recovery of possession of the suit land, survey number 123/4, and cancellation of the sale deed. " * 3
)
NDPS_TEXT = (
    "The appellant was convicted under the NDPS Act for possession of 20 kg of ganja recovered from his house. "
    "The contraband was seized in the presence of witnesses. The question is whether Section 50 was complied with. " * 3
)


def test_stage2_accepts_property_judgments_with_tags():
    d = filters.stage2(rec(), PROPERTY_TEXT)
    assert d.verdict == "accept"
    assert {"sale_contract", "title_ownership", "possession_injunction"} <= set(d.tags)
    assert "Transfer of Property Act" in d.statutes and "Specific Relief Act" in d.statutes
    assert 0.9 < filters.property_score(d.score) <= 1


def test_stage2_rejects_ndps_possession():
    d = filters.stage2(rec(), NDPS_TEXT)
    assert d.verdict == "reject" and any("NDPS" in r for r in d.reasons)


# ---------- Parsers ----------


def test_parsers():
    assert sources.case_type_from_title("SA/2/2020 of ANAND Vs X") == "SA"
    assert sources.case_type_from_title("W.P./396/2024 of X") == "WP"
    assert sources.parse_date("08-01-2026") == date(2026, 1, 8)
    assert sources.parse_date("2025-09-04 00:00:00") == date(2025, 9, 4)
    assert sources.parse_date("nan") is None
    acts = "[{'act': 'Constitution of India', 'section': '226'}\n {'act': 'Limitation Act', 'section': '5'}]"
    assert sources.parse_acts(acts) == [{"act": "Constitution of India", "section": "226"}, {"act": "Limitation Act", "section": "5"}]
    assert sources.parse_acts([{"act": "Transfer of Property Act", "section": None}]) == [{"act": "Transfer of Property Act", "section": None}]


def _parquet(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_parquet(buf)
    return buf.getvalue()


def test_sc_records_ignore_the_unreliable_language_flag(monkeypatch):
    rows = [{"path": "2026_2_107_127", "title": "A versus B", "description": "headnote", "decision_date": "08-01-2026",
             "available_languages": "", "case_id": "2026 INSC 40", "court": "Supreme Court of India"}]
    monkeypatch.setattr(sources, "fetch_versioned", lambda url, etag: _parquet(rows))
    (r,) = sources.sc_records(2026)
    assert r.pdf_key == "data/pdf/year=2026/english/2026_2_107_127_EN.pdf"  # kept although the flag is empty
    assert r.neutral_citation == "2026 INSC 40" and r.decision_date == date(2026, 1, 8)


def test_hc_records_join_case_details(monkeypatch):
    meta = [{"title": "SA/9/2024 of T Vs R", "description": "IN THE HIGH COURT OF BOMBAY AT GOA", "cnr": "HCBM01",
             "pdf_link": "court/cnrorders/hcbgoa/orders/HCBM01_1_2025-02-26.pdf", "decision_date": "2025-02-26 00:00:00",
             "court": "Bombay High Court", "pdf_exists": "False"}]
    monkeypatch.setattr(sources, "fetch_versioned", lambda url, etag: _parquet(meta))
    monkeypatch.setattr(sources, "hc_case_details", lambda c, b: {"HCBM01": {"case_type": "SA", "petitioner": "T",
                        "acts": "[{'act': 'Transfer of Property Act', 'section': '54'}]"}})
    (r,) = sources.hc_records(2025, "27_1", "hcbgoa")
    assert r.key == "hc_27_1_hcbgoa_HCBM01_1_2025-02-26"
    assert r.pdf_key == "data/pdf/year=2025/court=27_1/bench=hcbgoa/HCBM01_1_2025-02-26.pdf"  # pdf_exists ignored
    assert r.case_type == "SA" and r.acts[0]["act"] == "Transfer of Property Act" and r.petitioner == "T"


# ---------- Pipeline ----------


@pytest.fixture
def fake_world(monkeypatch):
    records = [
        rec(key="p1", title="Specific performance of agreement to sell", description="agreement to sell, sale deed, suit land"),
        rec(key="p2", title="Possession of the suit property", description="recovery of possession, injunction, land"),
        rec(key="x1", title="State versus Z", description="Appeal against conviction under the NDPS Act for possession of ganja."),
        rec(key="gone", title="Partition of ancestral property", description="partition suit, ancestral property, land"),
    ]
    texts = {"p1": PROPERTY_TEXT, "p2": PROPERTY_TEXT, "gone": None}
    monkeypatch.setattr(pipeline, "partitions", lambda cfg: [pipeline.Partition("sc/2024", "sc", "u", lambda etag: list(records))])
    monkeypatch.setattr(sources, "head", lambda url: ("etag-1", "Mon"))
    monkeypatch.setattr(pipeline, "_fetch", lambda r: (r, texts.get(r.key), None if texts.get(r.key) else "pdf not found (404)"))
    monkeypatch.setattr(semantic, "stage3", lambda r, t: ("reject", -0.1, ["seed"]))
    import app.services.embeddings as emb

    monkeypatch.setattr(emb, "embed_documents", lambda texts: [[0.0] * 384 for _ in texts])
    return records


def test_pipeline_stores_only_property_judgments(fake_world):
    store = MemoryStore()
    stats = pipeline.run(pipeline.Config(sources=["sc"]), store)
    assert set(store.judgments) == {"p1", "p2"}
    j = store.judgments["p1"]
    assert j["source"] == "sc" and j["summary"] == {} and j["summary_status"] == "none"
    assert "sale_contract" in j["topic_tags"] and j["paragraphs"] and j["filter_evidence"]["reasons"]
    assert store.items[("sc", "x1")]["status"] == "rejected" and store.items[("sc", "x1")]["stage"] == "metadata"
    assert store.items[("sc", "gone")]["status"] == "unavailable"
    assert stats.accepted == 2 and store.watermarks["sc/2024"] == "etag-1"


def test_rerun_is_incremental(fake_world):
    store = MemoryStore()
    pipeline.run(pipeline.Config(sources=["sc"]), store)
    again = pipeline.run(pipeline.Config(sources=["sc"]), store)
    assert again.unchanged == 1 and again.candidates == 0  # same ETag: partition skipped
    full = pipeline.run(pipeline.Config(sources=["sc"], full=True), store)
    assert full.already_done == 4 and full.candidates == 0  # re-scanned, but decided records aren't re-done


def test_limit_leaves_the_partition_open(fake_world):
    store = MemoryStore()
    first = pipeline.run(pipeline.Config(sources=["sc"], limit=1), store)
    assert first.candidates == 1 and "sc/2024" not in store.watermarks
    rest = pipeline.run(pipeline.Config(sources=["sc"]), store)
    assert rest.candidates == 2 and len(store.judgments) == 2


def test_dry_run_stores_nothing(fake_world):
    store = MemoryStore()
    stats = pipeline.run(pipeline.Config(sources=["sc"], dry_run=True), store)
    assert stats.accepted == 2 and store.judgments == {} and store.watermarks == {}


def test_failures_are_retried_then_given_up(fake_world, monkeypatch):
    monkeypatch.setattr(pipeline, "_fetch", lambda r: (r, None, "error: ConnectError"))
    store = MemoryStore()
    for _ in range(3):
        pipeline.run(pipeline.Config(sources=["sc"], full=True), store)
    assert store.items[("sc", "p1")]["attempts"] == 3
    last = pipeline.run(pipeline.Config(sources=["sc"], full=True), store)
    assert last.candidates == 0  # gave up after 3 attempts


# ---------- Lazy summaries ----------


def test_judgment_summary_is_written_on_first_open(monkeypatch):
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.llm.schemas import JudgmentSummary
    from app.main import app
    from app.models import Judgment, JudgmentParagraph
    import ingest.supreme_court as sc

    j = Judgment(id="j1", title="A v B", court="Supreme Court of India", source_url="u", summary={}, summary_status="none",
                 headnote="Issue for consideration: specific performance")
    j.paragraphs = [JudgmentParagraph(para_no=1, text="The appellant sought specific performance.")]

    class FakeDB:
        commits = 0

        def get(self, model, key):
            return j

        def commit(self):
            FakeDB.commits += 1

        def rollback(self):
            pass

    monkeypatch.setattr(sc, "summarise", lambda title, paras: JudgmentSummary(
        case_type="Civil appeal", facts="f", issues=["i"], holding="h", outcome="o", prevailing_party="partly",
        acts_cited=[], legal_areas=[], key_principles=[], key_paragraphs=[1]))
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        body = TestClient(app).get("/judgments/j1").json()
    finally:
        app.dependency_overrides.clear()
    assert body["summary"]["outcome"] == "o" and body["headnote"].startswith("Issue") and FakeDB.commits == 1


def test_sc_records_without_headnote_go_to_full_text():
    # Real data: SC metadata before 2024 has no headnote at all, so a bare title can't be judged.
    d = filters.stage1(rec(title="RAMACHANDRAN versus VIJAYAN", description=""))
    assert d.verdict == "candidate" and "judged on the full text" in d.reasons[-1]
    hc = filters.stage1(rec(source="hc", title="WP/1/2025 of X Vs Y", case_type="WP", description=""))
    assert hc.verdict == "reject"  # HC records have case types and acts to judge by


def test_filter_evaluation_from_hand_labels(tmp_path):
    from ingest.evaluate import LABEL, evaluate

    path = tmp_path / "d.csv"
    rows = [("accept", "fulltext", "y"), ("accept", "undecided", "n"), ("reject", "metadata", "y"), ("reject", "fulltext", "n"), ("accept", "fulltext", "")]
    with open(path, "w", newline="") as f:
        import csv

        w = csv.writer(f)
        w.writerow(["key", "partition", "decision", "stage", "score", "title", "reasons", LABEL])
        for i, (d, s, l) in enumerate(rows):
            w.writerow([i, "2024", d, s, 1, "t", "r", l])
    out = evaluate(str(path))
    assert "Labelled rows: 4" in out and "Precision: 50.0%" in out and "Recall:    50.0%" in out
    assert "undecided  FP: 1" in out and "metadata   FN: 1" in out

"""The scorecard's statistics and the synthetic case generator (eval/run_all.py, eval/generate_cases.py)."""

import pytest

from eval.generate_cases import generate, indian
from eval.run_all import Counts, wilson


def test_wilson_interval():
    low, high = wilson(20, 20)
    assert low == pytest.approx(0.839, abs=0.001) and high == 1.0  # 20/20 means "at least ~84%"
    low, high = wilson(50, 100)
    assert low == pytest.approx(0.404, abs=0.001) and high == pytest.approx(0.596, abs=0.001)
    assert wilson(0, 0) == (0.0, 0.0)


def test_counts_precision_recall_f1():
    c = Counts()
    c.add({"a", "b", "x"}, {"a", "b", "c", "d"})  # 2 right, 1 invented, 2 missed
    row = c.row("m")
    assert (row["tp"], row["fp"], row["fn"]) == (2, 1, 2)
    assert row["precision"] == pytest.approx(2 / 3) and row["recall"] == pytest.approx(0.5)
    assert row["f1"] == pytest.approx(2 * (2 / 3) * 0.5 / (2 / 3 + 0.5))


def test_generator_is_deterministic_and_labelled():
    a, b = generate(10, seed=3), generate(10, seed=3)
    assert [d.pages for c in a for d in c.documents] == [d.pages for c in b for d in c.documents]
    for case in a:
        receipt = case.documents[1]
        assert receipt.amounts and receipt.dates and receipt.ids and receipt.names
        if "property_identifier_difference" in case.planted:
            assert receipt.ids != case.documents[0].ids


def test_indian_grouping():
    assert indian(4500000) == "45,00,000" and indian(150000) == "1,50,000" and indian(999) == "999"


def test_understanding_scoring_with_a_fake_llm(monkeypatch):
    from app.llm.schemas import DocumentUnderstanding
    from app.services import understanding
    from eval.run_all import score_llm_understanding

    def fake(fmt, system, user, **kwargs):
        return DocumentUnderstanding(one_line="A document.", summary=[
            {"text": "It mentions an amount of Rs. 99,99,999.", "pages": [1], "quote": None},  # invented: dropped
            {"text": "It is a document about a plot.", "pages": [1], "quote": "SYNTHETIC SAMPLE"},
        ], clause_explanations=[], terms_in_context=[], things_to_check=[])

    monkeypatch.setattr(understanding, "structured", fake)
    rows = {r["metric"].split(" (")[0]: r for r in score_llm_understanding(generate(2))}
    kept = rows["Explanation statements kept"]
    assert kept["tp"] == kept["fp"]  # one kept, one dropped per document

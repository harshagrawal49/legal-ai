"""Tests that need neither a database nor an API key."""

from app.main import app
from app.services.advisor import CITATION_RE, JUDGMENT_ID_RE
from app.services.search import _keyword_tsquery
from ingest.pdf_text import split_paragraphs


def test_split_follows_judgment_numbering():
    text = "IN THE SUPREME COURT OF INDIA\nA v. B\n" + "\n".join(
        f"{n}. Paragraph {n} text\ncontinues here." for n in range(1, 8)
    )
    paras = split_paragraphs(text)
    assert [n for n, _ in paras] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert paras[0][1].startswith("IN THE SUPREME COURT")
    assert paras[3][1] == "3. Paragraph 3 text continues here."


def test_split_ignores_out_of_sequence_numbers():
    text = "\n".join(f"{n}. para {n}" for n in range(1, 7)) + "\n2. a numbered list inside para 6"
    paras = split_paragraphs(text)
    assert [n for n, _ in paras] == [1, 2, 3, 4, 5, 6]
    assert "numbered list" in paras[-1][1]


def test_split_falls_back_to_chunks_without_numbering():
    text = "\n\n".join("word " * 200 for _ in range(5))
    paras = split_paragraphs(text)
    assert [n for n, _ in paras] == list(range(1, len(paras) + 1))
    assert len(paras) > 1


def test_keyword_tsquery_is_or_of_safe_words():
    assert _keyword_tsquery("builder's delay: possession & refund!") == "builder | delay | possession | refund"
    assert _keyword_tsquery("a b") == ""


def test_citation_patterns():
    assert CITATION_RE.findall("See [[J:2023_16_872_887]] and [[J:x]].") == ["2023_16_872_887", "x"]
    assert JUDGMENT_ID_RE.findall('<judgment judgment_id="2023_1_2_3">') == ["2023_1_2_3"]


def test_openapi_builds():
    paths = app.openapi()["paths"]
    assert "/cases/{case_id}/chat" in paths
    assert "/judgments/{judgment_id}" in paths

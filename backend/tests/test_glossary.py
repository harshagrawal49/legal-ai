"""Legal term spotting, language identification and the rule-based document classifier (no LLM)."""

import json

import pytest

from app.services import glossary
from eval.samples import SAMPLES
from eval.scans import DEVANAGARI_SAMPLES


def test_glossary_file_is_well_formed():
    data = json.loads(glossary.GLOSSARY_PATH.read_text(encoding="utf-8"))
    ids = [t["id"] for t in data["terms"]]
    assert len(ids) == len(set(ids)) >= 40
    for t in data["terms"]:
        assert t["term"] and t["meaning"] and t["why"] and t["variants"] and t["names"]["hi"]
        assert set(t["names"]) == {"hi"}  # English/Hindi only (Marathi out of scope)


def test_finds_terms_in_english_and_hindi_with_pages():
    hits = {h.term_id: h for h in glossary.find_terms(SAMPLES["agreement_to_sell.pdf"])}
    assert {"agreement_to_sell", "earnest_money", "survey_number", "consideration"} <= set(hits)
    assert hits["agreement_to_sell"].page == 1 and "AGREEMENT TO SELL" in hits["agreement_to_sell"].excerpt
    hindi = {h.term_id for h in glossary.find_terms(DEVANAGARI_SAMPLES["anubandh_hindi.pdf"])}
    assert {"agreement_to_sell", "earnest_money", "survey_number", "vendor_purchaser"} <= hindi


def test_no_false_hits_on_ordinary_words():
    text = ["My client will take appropriate action. The seller sold it to someone. Advanced payment of taxes."]
    found = {h.term_id for h in glossary.find_terms(text)}
    assert "will_probate" not in found  # "will" as a verb
    assert "earnest_money" not in found  # "Advanced" is not "advance"


def test_longer_variant_wins():
    found = {h.term_id: h.matched for h in glossary.find_terms(["The encumbrance certificate shows no encumbrance."])}
    assert found["encumbrance_certificate"] == "encumbrance certificate"
    assert "encumbrance" in found  # the second, standalone mention still counts


@pytest.mark.parametrize("text, expected", [
    ("I paid an advance but the seller sold the plot to someone else", "en"),
    ("मैंने अग्रिम राशि दी थी लेकिन विक्रेता ने प्लॉट बेच दिया", "hi"),
    ("maine 5 lakh advance diya tha par seller ne plot kisi aur ko bech diya", "hinglish"),
    ("what is the par value of the property", "en"),
    ("", "en"),
])
def test_language(text, expected):
    assert glossary.detect_language(text) == expected


@pytest.mark.parametrize("name, expected", [
    ("agreement_to_sell.pdf", "agreement_to_sell"), ("advance_receipt.pdf", "receipt"), ("legal_notice.pdf", "legal_notice"),
])
def test_classify_samples(name, expected):
    assert glossary.classify(SAMPLES[name])[0] == expected


def test_classify_hindi_and_unknown():
    assert glossary.classify(DEVANAGARI_SAMPLES["rasid_hindi.pdf"])[0] == "receipt"
    assert glossary.classify(DEVANAGARI_SAMPLES["anubandh_hindi.pdf"])[0] == "agreement_to_sell"
    assert glossary.classify(["Lorem ipsum dolor sit amet."]) == ("other", 0.0)

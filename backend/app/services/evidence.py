"""Evidence pack: chronology and possible gaps/conflicts across a case's uploaded documents.

Plain code, no LLM, so every item is traceable to a document page. Flags point out things to check;
a difference between documents can be a typo, a different property, or a real discrepancy, so the
wording never draws a conclusion (fraud, ownership, liability) from it.
"""

import re
from decimal import Decimal, InvalidOperation

from app.config import get_settings
from app.models import CaseDocument

# Amount and event kinds where one case normally has a single value, so differences are worth a look.
SINGLE_VALUE_AMOUNTS = {"total_consideration", "advance_or_earnest_money"}
SINGLE_DATE_EVENTS = {"agreement_signed", "registration", "deadline"}
MULTIPLIERS = {"lakh": Decimal(100_000), "lakhs": Decimal(100_000), "lac": Decimal(100_000),
               "crore": Decimal(10_000_000), "crores": Decimal(10_000_000)}


def page_source(doc: CaseDocument, page: int | None) -> dict:
    """page_info entry for a 1-based page number ({} if unknown)."""
    info = doc.page_info or []
    return info[page - 1] if page and 1 <= page <= len(info) else {}


def source_ref(doc: CaseDocument, source: dict | None) -> dict:
    source = source or {}
    return {
        "document_id": str(doc.id),
        "filename": doc.filename,
        "page": source.get("page"),
        "excerpt": source.get("excerpt"),
        "verified": bool(source.get("verified")),
        # A matching quote proves where the text came from, not that OCR read the digits correctly.
        "from_ocr": page_source(doc, source.get("page")).get("source") == "ocr",
    }


def _pages_text(numbers: list[int]) -> str:
    return ("page " if len(numbers) == 1 else "pages ") + ", ".join(map(str, numbers))


def ocr_flags(doc: CaseDocument, min_confidence: float) -> list[dict]:
    """What OCR did to this document's pages, in plain words, each linked to the pages concerned."""
    by_source: dict[str, list[int]] = {}
    low: list[tuple[int, float]] = []
    for n, info in enumerate(doc.page_info or [], start=1):
        by_source.setdefault(info.get("source", "text"), []).append(n)
        if info.get("source") == "ocr" and info.get("confidence") is not None and info["confidence"] < min_confidence:
            low.append((n, info["confidence"]))

    def refs(numbers):
        return [source_ref(doc, {"page": n}) for n in numbers]

    flags = []
    if by_source.get("ocr"):
        engine = next(i.get("engine") for i in doc.page_info if i.get("source") == "ocr")
        flags.append(_flag(
            "ocr_used",
            f"{doc.filename}: {_pages_text(by_source['ocr'])} read from a scan (OCR, {engine}). "
            "Check amounts, dates, names and survey numbers against the original.",
            refs(by_source["ocr"]),
        ))
    for n, confidence in low:
        flags.append(_flag(
            "ocr_low_confidence",
            f"{doc.filename}: page {n} was read by OCR with low confidence ({confidence:.0f}%). "
            "Some words or numbers may be wrong; compare it with the original carefully.",
            refs([n]),
        ))
    messages = {
        "ocr_unreadable": "could not be read (the scan is too unclear)",
        "ocr_failed": "could not be read (OCR failed on this page)",
        "ocr_unavailable": "are scanned but OCR isn't available on this server" if len(by_source.get("ocr_unavailable", [])) > 1
        else "is scanned but OCR isn't available on this server",
        "ocr_skipped": "were not read: only the first pages of a long scan are OCR'd",
    }
    for source, message in messages.items():
        if by_source.get(source):
            flags.append(_flag("ocr_page_not_read", f"{doc.filename}: {_pages_text(by_source[source])} {message}.", refs(by_source[source])))
    return flags


def _processed(docs: list[CaseDocument]) -> list[CaseDocument]:
    return [d for d in docs if d.status == "processed" and d.facts]


OCR_GROUPING_DOT = re.compile(r"(?<=\d)\.(?=\d{2,3},)")


def parse_amount(value: str) -> Decimal | None:
    """'Rs. 5,00,000/-' -> 500000, 'Rs 4.5 lakh' -> 450000. None if there is no single clear number."""
    # OCR often reads a grouping comma as a dot ("5.50,000"). A dot followed by digits and then a
    # comma can't be a decimal point, so treat it as a comma.
    text = OCR_GROUPING_DOT.sub(",", value.lower()).replace(",", "")
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if len(numbers) != 1:
        return None
    try:
        amount = Decimal(numbers[0])
    except InvalidOperation:
        return None
    for word, factor in MULTIPLIERS.items():
        if re.search(rf"\b{word}\b", text):
            return amount * factor
    return amount


DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _norm_id(value: str) -> str:
    """'123 / 4' -> '1234'; Devanagari is kept, and its digits become ASCII ('१२३/अ' -> '123अ')."""
    return re.sub(r"[^a-z0-9\u0900-\u097f]", "", value.lower().translate(DEVANAGARI_DIGITS))


# ---------- Chronology ----------


def build_timeline(docs: list[CaseDocument]) -> list[dict]:
    """Dated events from all documents, oldest first; undated events at the end."""
    items = []
    for doc in _processed(docs):
        f = doc.facts
        if f.get("document_date"):
            items.append({
                "date": f["document_date"],
                "date_as_written": None,
                "kind": "document_dated",
                "description": f"{f.get('document_type', 'document').replace('_', ' ').capitalize()} dated",
                "source": source_ref(doc, f.get("document_date_source")),
            })
        for ev in f.get("events", []):
            items.append({
                "date": ev.get("date"),
                "date_as_written": ev.get("date_as_written"),
                "kind": ev.get("kind", "other"),
                "description": ev.get("description", ""),
                "source": source_ref(doc, ev.get("source")),
            })
    # ISO strings sort chronologically; "2023-03" sorts before "2023-03-15".
    return sorted(items, key=lambda i: (i["date"] is None, i["date"] or ""))


# ---------- Flags ----------


def _flag(kind: str, message: str, sources: list[dict]) -> dict:
    return {"kind": kind, "message": message, "sources": sources}


def _differing_values(groups: dict[str, list[tuple[str, dict]]]) -> list[tuple[str, list[tuple[str, dict]]]]:
    """Groups whose items have more than one distinct normalised value."""
    out = []
    for key, items in groups.items():
        if len({v for v, _ in items}) > 1:
            out.append((key, items))
    return out


def build_flags(docs: list[CaseDocument]) -> list[dict]:
    flags: list[dict] = []
    processed = _processed(docs)

    min_confidence = get_settings().ocr_min_confidence
    for doc in docs:
        if doc.page_info:
            flags += ocr_flags(doc, min_confidence)
        if doc.status == "processing":
            flags.append(_flag("still_processing", f"{doc.filename}: still being analysed. Refresh in a moment.", [source_ref(doc, None)]))
        elif doc.status != "processed":
            flags.append(_flag("extraction_failure", f"{doc.filename}: {doc.error or 'not processed'}", [source_ref(doc, None)]))
        elif doc.facts.get("truncated_after_page"):
            flags.append(_flag(
                "partially_processed",
                f"{doc.filename}: only pages 1-{doc.facts['truncated_after_page']} were analysed (document too long).",
                [source_ref(doc, None)],
            ))

    # Property identifiers of the same kind with different values.
    by_kind: dict[str, list[tuple[str, dict]]] = {}
    for doc in processed:
        for pid in doc.facts.get("property_identifiers", []):
            by_kind.setdefault(pid["kind"].strip().lower(), []).append(
                (_norm_id(pid["value"]), {**source_ref(doc, pid.get("source")), "value": pid["value"]})
            )
    for kind, items in _differing_values(by_kind):
        values = ", ".join(dict.fromkeys(src["value"] for _, src in items))
        flags.append(_flag(
            "property_identifier_difference",
            f"Different values for {kind} appear in the documents ({values}). "
            "This may be a typo, a different property, or a real discrepancy; check the originals.",
            [src for _, src in items],
        ))

    # Amounts of a kind that normally has one value, e.g. total consideration.
    by_amount: dict[str, list[tuple[str, dict]]] = {}
    for doc in processed:
        for amt in doc.facts.get("amounts", []):
            parsed = parse_amount(amt.get("value", ""))
            if amt.get("kind") in SINGLE_VALUE_AMOUNTS and parsed is not None:
                by_amount.setdefault(amt["kind"], []).append(
                    (str(parsed.normalize()), {**source_ref(doc, amt.get("source")), "value": amt["value"]})
                )
    for kind, items in _differing_values(by_amount):
        values = ", ".join(dict.fromkeys(src["value"] for _, src in items))
        flags.append(_flag(
            "amount_difference",
            f"The {kind.replace('_', ' ')} is stated differently ({values}). Check which figure each document refers to.",
            [src for _, src in items],
        ))

    # Dates of a kind that normally happens once, e.g. the agreement being signed.
    by_event: dict[str, list[tuple[str, dict]]] = {}
    for doc in processed:
        for ev in doc.facts.get("events", []):
            if ev.get("kind") in SINGLE_DATE_EVENTS and ev.get("date"):
                by_event.setdefault(ev["kind"], []).append(
                    (ev["date"], {**source_ref(doc, ev.get("source")), "value": ev["date"]})
                )
    for kind, items in _differing_values(by_event):
        values = ", ".join(dict.fromkeys(src["value"] for _, src in items))
        flags.append(_flag(
            "date_difference",
            f"Different dates are given for {kind.replace('_', ' ')} ({values}). They may describe different events; check the originals.",
            [src for _, src in items],
        ))

    # Documents that are mentioned but may not have been uploaded.
    uploaded_types = {d.facts.get("document_type", "").replace("_", " ") for d in processed}
    for doc in processed:
        for ref in doc.facts.get("referenced_documents", []):
            desc = ref.get("description", "")
            if any(t and t in desc.lower() for t in uploaded_types):
                continue
            flags.append(_flag(
                "referenced_document_not_found",
                f"'{desc}' is mentioned but could not be matched to an uploaded document. If you have it, upload it.",
                [source_ref(doc, ref.get("source"))],
            ))

    if processed and not any(d.facts.get("property_identifiers") for d in processed):
        flags.append(_flag(
            "missing_property_identifier",
            "No property identifier (survey, plot, khata or flat number) was found in the uploaded documents.",
            [],
        ))

    # Ambiguities the extraction noticed inside a single document.
    for doc in processed:
        for u in doc.facts.get("uncertainties", []):
            flags.append(_flag("uncertainty", f"{doc.filename}: {u.get('description', '')}", [source_ref(doc, u.get("source"))]))

    # Source references whose excerpt wasn't found on the stated page.
    for doc in processed:
        unverified = _unverified_refs(doc.facts)
        if unverified:
            flags.append(_flag(
                "unverified_reference",
                f"{doc.filename}: {len(unverified)} extracted item(s) could not be matched to the quoted page. Review them against the original.",
                [source_ref(doc, s) for s in unverified],
            ))
    return flags


def _unverified_refs(node) -> list[dict]:
    found = []
    if isinstance(node, dict):
        if "page" in node and "excerpt" in node and not node.get("verified"):
            found.append(node)
        for value in node.values():
            found += _unverified_refs(value)
    elif isinstance(node, list):
        for item in node:
            found += _unverified_refs(item)
    return found


def build_evidence(docs: list[CaseDocument]) -> dict:
    return {"timeline": build_timeline(docs), "flags": build_flags(docs)}

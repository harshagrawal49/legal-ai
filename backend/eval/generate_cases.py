"""Synthetic property-dispute cases with known ground truth, for the scorecard (eval/run_all.py).

Each case is one fictional dispute (a buyer paid an advance under an agreement to sell; the seller
allegedly agreed to sell to someone else), written as 2-3 documents in English or Hindi.
Because the generator picks every fact, every expected value is known exactly:
- amounts, dates and property identifiers present in each document (normalised);
- party names in each document;
- planted discrepancies: the receipt may show a different survey number and/or advance amount,
  so the evidence flags have a known right answer.

Formats vary on purpose (Rs. 5,00,000/- · Rs 5 lakh · INR 500000 · 15/03/2023 · 15th March, 2023 ·
Devanagari digits), and distractors that must NOT be extracted are included (cheque numbers, plot
area, phone numbers, "Section 54", "15 days").

Everything is fictional. The same seed always produces the same cases.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.services.evidence import _norm_id

EN_FIRST = ["Meera", "Ravi", "Sunil", "Anita", "Prakash", "Kavita", "Rahul", "Sneha", "Vikram", "Pooja", "Arjun", "Neha"]
EN_LAST = ["Kulkarni", "Patil", "Deshmukh", "Joshi", "Shinde", "Pawar", "Rao", "Nair", "Sharma", "Gupta", "Verma", "Kale"]
DEV_FIRST = ["मीरा", "रवि", "सुनील", "अनिता", "प्रकाश", "कविता", "राहुल", "स्नेहा", "विक्रम", "पूजा"]
DEV_LAST = ["कुलकर्णी", "पाटिल", "देशमुख", "जोशी", "शिंदे", "पवार", "शर्मा", "गुप्ता", "वर्मा", "सिंह"]
EN_VILLAGES = ["Wadgaon", "Hadapsar", "Wagholi", "Kharadi", "Baner", "Hinjewadi", "Manjari", "Undri"]
DEV_VILLAGES = ["वडगाँव", "हडपसर", "वाघोली", "खराडी", "बानेर", "मांजरी", "उंड्री"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
HI_MONTHS = ["जनवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
TO_DEV = str.maketrans("0123456789", "०१२३४५६७८९")
HEADERS = {
    "en": "SYNTHETIC SAMPLE DOCUMENT - FICTIONAL, FOR TESTING ONLY",
    "hi": "कृत्रिम नमूना दस्तावेज - काल्पनिक, केवल परीक्षण के लिए",
}


@dataclass
class GenDoc:
    filename: str
    kind: str  # agreement | receipt | notice
    language: str
    pages: list[str]
    amounts: set[str] = field(default_factory=set)  # rupees, as nlp.rupees() writes them
    dates: set[str] = field(default_factory=set)  # ISO
    ids: set[str] = field(default_factory=set)  # _norm_id form
    names: list[str] = field(default_factory=list)
    terms: set[str] = field(default_factory=set)  # glossary term ids the template contains
    doc_type: str = "other"
    # Facts as a perfect extractor would return them (DocumentFacts shape), for flag/provenance checks.
    facts: dict = field(default_factory=dict)


@dataclass
class GenCase:
    case_id: str
    language: str
    documents: list[GenDoc]
    planted: set[str]  # expected cross-document flags: property_identifier_difference, amount_difference
    buyer: str
    seller: str
    advance: int
    survey: str


def indian(n: int) -> str:
    """4500000 -> '45,00,000'."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head] + parts + [tail]) if head else ",".join(parts + [tail])


def fmt_amount(n: int, lang: str, rng: random.Random) -> str:
    lakh = n / 100_000
    lakh_text = f"{lakh:g}"
    if lang == "en":
        options = [f"Rs. {indian(n)}/-", f"Rs {indian(n)}", f"INR {n}"]
        if n % 50_000 == 0:
            options.append(f"Rs. {lakh_text} lakh")
    else:  # Hindi: ASCII or Devanagari numerals, or lakh
        options = [f"रुपये {indian(n)}", f"रुपये {indian(n).translate(TO_DEV)}"] + ([f"रुपये {lakh_text} लाख"] if n % 100_000 == 0 else [])
    return rng.choice(options)


def fmt_date(d: date, lang: str, rng: random.Random) -> str:
    numeric = f"{d.day:02d}/{d.month:02d}/{d.year}"
    if lang == "en":
        suffix = "th" if 11 <= d.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d.day % 10, "th")
        return rng.choice([
            f"{d.day} {EN_MONTHS[d.month - 1]} {d.year}", numeric,
            f"{d.day}{suffix} {EN_MONTHS[d.month - 1]}, {d.year}", f"{EN_MONTHS[d.month - 1]} {d.day}, {d.year}",
        ])
    return rng.choice([f"{d.day} {HI_MONTHS[d.month - 1]} {d.year}", numeric, numeric.translate(TO_DEV)])


def _src(page: int = 1) -> dict:
    return {"page": page, "excerpt": "x", "verified": True}


def _amount_fact(kind: str, text: str, page: int = 1) -> dict:
    return {"kind": kind, "description": kind.replace("_", " "), "value": text, "currency": "INR", "source": _src(page)}


def generate_case(index: int, rng: random.Random) -> GenCase:
    from app.services import nlp

    lang = rng.choices(["en", "hi"], weights=[6, 4])[0]
    dev = lang != "en"
    first, last = (DEV_FIRST, DEV_LAST) if dev else (EN_FIRST, EN_LAST)
    buyer, seller, other = (f"{f} {l}" for f, l in zip(rng.sample(first, 3), rng.sample(last, 3)))
    village = rng.choice(DEV_VILLAGES if dev else EN_VILLAGES)
    number = rng.randint(10, 999)
    survey = f"{number}/{rng.randint(1, 9)}"
    planted = set()
    survey_receipt = survey
    if rng.random() < 0.4:  # receipt shows a different survey number
        survey_receipt = f"{number}/{rng.choice('ABC')}" if lang == "en" else f"{number}/{int(survey[-1]) % 9 + 1}"
        planted.add("property_identifier_difference")
    total = rng.randint(20, 90) * 100_000
    advance = rng.randint(2, 10) * 50_000
    advance_receipt = advance
    if rng.random() < 0.4:  # receipt shows a different advance
        advance_receipt = advance + 50_000
        planted.add("amount_difference")
    balance = total - advance
    agreed = date(2019, 1, 1) + timedelta(days=rng.randint(0, 5 * 365))
    deadline = agreed + timedelta(days=180)
    notice_day = deadline + timedelta(days=rng.randint(30, 300))
    cheque = f"{rng.randint(0, 999999):06d}"
    area = rng.choice([1000, 1200, 1500, 2000, 2400, 3000])
    phone = f"9{rng.randint(100000000, 999999999)}"
    A = lambda n: fmt_amount(n, lang, rng)  # noqa: E731
    Dt = lambda d: fmt_date(d, lang, rng)  # noqa: E731
    header = HEADERS[lang]
    cid = f"case{index:03d}"
    docs: list[GenDoc] = []

    def finish(doc: GenDoc, amounts: list[int], dates: list[date], ids: list[str]) -> GenDoc:
        doc.amounts = {nlp.rupees(nlp.amount_value(f"Rs {a}")) for a in amounts}
        doc.dates = {d.isoformat() for d in dates}
        doc.ids = {_norm_id(i) for i in ids}
        return doc

    # ---- agreement ----
    a_total, a_adv, a_bal = A(total), A(advance), A(balance)
    if lang == "en":
        pages = [
            f"{header}\n\nAGREEMENT TO SELL\n\nThis Agreement to Sell is made at Pune on {Dt(agreed)} between {seller} "
            f"(the SELLER) and {buyer} (the PURCHASER).\n\n1. The Seller is the owner of the plot bearing Survey No. {survey}, "
            f"Village {village}, District Pune, admeasuring {area} sq. ft.\n\n2. The total sale consideration is {a_total}.\n\n"
            f"3. The Purchaser has paid an advance of {a_adv} by cheque no. {cheque} on the date of this agreement.",
            f"{header}\n\n4. The balance consideration of {a_bal} shall be paid on or before {Dt(deadline)}, within 15 days of "
            f"the Seller obtaining the required permissions.\n\n5. Contact for the Seller: {phone}.\n\n"
            f"Signed: {seller} (Seller)        Signed: {buyer} (Purchaser)",
        ]
    else:
        pages = [
            f"{header}\n\nविक्रय अनुबंध\n\nयह अनुबंध दिनांक {Dt(agreed)} को पुणे में {seller} (विक्रेता) और {buyer} (क्रेता) के बीच किया गया।\n\n"
            f"विक्रेता सर्वे नंबर {survey}, ग्राम {village} की {area} वर्ग फुट भूमि का स्वामी है।\n\n"
            f"कुल विक्रय मूल्य {a_total} है। क्रेता ने {a_adv} अग्रिम राशि के रूप में चेक संख्या {cheque} द्वारा दिए हैं।\n\n"
            f"शेष राशि {a_bal} दिनांक {Dt(deadline)} तक दी जाएगी। संपर्क: {phone}।"
        ]
    agreement = finish(GenDoc(f"{cid}_agreement.pdf", "agreement", lang, pages, names=[seller, buyer], doc_type="agreement_to_sell",
                              terms={"agreement_to_sell", "vendor_purchaser", "survey_number", "consideration", "earnest_money", "balance_consideration"}),
                       [total, advance, balance], [agreed, deadline], [survey])
    agreement.facts = {
        "document_type": "agreement_to_sell", "document_date": agreed.isoformat(), "document_date_source": _src(1),
        "parties": [{"name": seller, "stated_role": "seller", "source": _src(1)}, {"name": buyer, "stated_role": "purchaser", "source": _src(1)}],
        "property_identifiers": [{"kind": "survey number", "value": survey, "source": _src(1)}],
        "amounts": [_amount_fact("total_consideration", a_total), _amount_fact("advance_or_earnest_money", a_adv),
                    _amount_fact("installment", a_bal, len(pages))],
        "events": [{"kind": "agreement_signed", "date": agreed.isoformat(), "date_as_written": None, "description": "Agreement signed", "source": _src(1)},
                   {"kind": "deadline", "date": deadline.isoformat(), "date_as_written": None, "description": "Balance due", "source": _src(len(pages))}],
        "clauses": [], "referenced_documents": [], "uncertainties": [],
    }
    docs.append(agreement)

    # ---- receipt ----
    r_adv = A(advance_receipt)
    if lang == "en":
        pages = [f"{header}\n\nRECEIPT\n\nDate: {Dt(agreed)}\n\nReceived from {buyer} a sum of {r_adv} by cheque no. {cheque} towards "
                 f"advance for the sale of plot Survey No. {survey_receipt}, Village {village}, Pune.\n\nReceived by: {seller}"]
    else:
        pages = [f"{header}\n\nरसीद\n\nदिनांक: {Dt(agreed)}\n\n{buyer} से भूखंड सर्वे नंबर {survey_receipt}, ग्राम {village} की बिक्री हेतु "
                 f"अग्रिम राशि {r_adv} चेक संख्या {cheque} द्वारा प्राप्त हुई।\n\nप्राप्तकर्ता: {seller}"]
    receipt = finish(GenDoc(f"{cid}_receipt.pdf", "receipt", lang, pages, names=[buyer, seller], doc_type="receipt",
                            terms={"earnest_money", "survey_number"}),
                     [advance_receipt], [agreed], [survey_receipt])
    receipt.facts = {
        "document_type": "receipt", "document_date": agreed.isoformat(), "document_date_source": _src(1),
        "parties": [{"name": buyer, "stated_role": "payer", "source": _src(1)}, {"name": seller, "stated_role": "recipient", "source": _src(1)}],
        "property_identifiers": [{"kind": "survey number", "value": survey_receipt, "source": _src(1)}],
        "amounts": [_amount_fact("advance_or_earnest_money", r_adv)],
        "events": [{"kind": "payment", "date": agreed.isoformat(), "date_as_written": None, "description": "Advance paid", "source": _src(1)}],
        "clauses": [], "referenced_documents": [], "uncertainties": [],
    }
    docs.append(receipt)

    # ---- legal notice (English only) ----
    if lang == "en":
        n_adv = A(advance)
        pages = [f"{header}\n\nLEGAL NOTICE\n\nDate: {Dt(notice_day)}\n\nTo: {seller}\n\nUnder instructions from my client {buyer}, I state that "
                 f"you entered into an agreement to sell dated {Dt(agreed)} for the plot bearing Survey No. {survey}, Village {village}, "
                 f"and received an advance of {n_adv}.\n\nMy client has learnt that you have agreed to sell the same plot to {other}. "
                 f"My client calls upon you to execute the sale deed within 15 days of this notice, under Section 54 of the "
                 f"Transfer of Property Act read with the agreement.\n\nAdvocate for {buyer}"]
        notice = finish(GenDoc(f"{cid}_notice.pdf", "notice", lang, pages, names=[seller, buyer, other], doc_type="legal_notice",
                               terms={"legal_notice", "agreement_to_sell", "survey_number", "earnest_money", "specific_performance"}),
                        [advance], [notice_day, agreed], [survey])
        notice.facts = {
            "document_type": "legal_notice", "document_date": notice_day.isoformat(), "document_date_source": _src(1),
            "parties": [{"name": seller, "stated_role": "noticee", "source": _src(1)}, {"name": buyer, "stated_role": "client", "source": _src(1)}],
            "property_identifiers": [{"kind": "survey number", "value": survey, "source": _src(1)}],
            "amounts": [_amount_fact("advance_or_earnest_money", n_adv)],
            "events": [{"kind": "notice_sent", "date": notice_day.isoformat(), "date_as_written": None, "description": "Notice", "source": _src(1)},
                       {"kind": "agreement_signed", "date": agreed.isoformat(), "date_as_written": None, "description": "Agreement", "source": _src(1)}],
            "clauses": [], "referenced_documents": [], "uncertainties": [],
        }
        docs.append(notice)

    return GenCase(cid, lang, docs, planted, buyer, seller, advance, survey)


def generate(n: int = 200, seed: int = 7) -> list[GenCase]:
    rng = random.Random(seed)
    return [generate_case(i, rng) for i in range(n)]


if __name__ == "__main__":
    cases = generate(5)
    for c in cases:
        print(c.case_id, c.language, sorted(c.planted))
        for d in c.documents:
            print("  ", d.filename, sorted(d.amounts), sorted(d.dates), sorted(d.ids))
        print(c.documents[1].pages[0][:300], "\n")

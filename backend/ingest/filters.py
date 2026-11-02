"""Is this judgment a property / land dispute? Rule-based stages 1 (metadata) and 2 (full text).

Pure functions, no I/O, so every decision is reproducible and comes with its reasons. The taxonomy
(TAGS) follows ingest_plan.md §1. Known false positives from real data are excluded explicitly:
"possession" of drugs or arms (NDPS / Arms Act), and "Limitation Act s.5" condonation of delay alone.

Stage 1 decides which records are worth downloading (cheap: title, headnote, case type, acts).
Stage 2 scores the full text and returns accept / reject / borderline; borderline goes to the
semantic check (ingest/semantic.py) and, if enabled, the LLM check.
"""

import re
from dataclasses import dataclass, field

PIPELINE_VERSION = "1"

# Topic tags (ingest_plan.md §1): regexes matched case-insensitively.
TAGS: dict[str, list[str]] = {
    "sale_contract": [r"agreements? (to|for) sell", r"agreements? for sale", r"sale agreement", r"specific performance",
                      r"earnest money", r"refund of (the )?(advance|earnest|consideration)", r"ready and willing",
                      r"balance (sale )?consideration", r"double sale"],
    "title_ownership": [r"declaration of title", r"cancellation of (the )?(registered )?(sale )?deeds?", r"\bsale deeds?\b",
                        r"title (to|over|of) the (suit |said )?(property|land|plot|house|premises)", r"conveyance deed",
                        r"ownership of the (suit |said )?(property|land|plot)", r"\bgift deed", r"(oral|onerous) gift",
                        r"allotment of (the )?(land|plot|site|flat|shop)", r"lease (deed|of (the )?land)", r"leasing out (the )?land"],
    "possession_injunction": [r"recovery of possession", r"(permanent|perpetual|temporary|mandatory) injunction", r"encroach",
                              r"\btrespass", r"suit (property|land|premises|schedule)", r"dispossess", r"delivery of possession"],
    "partition_inheritance": [r"\bpartition\b", r"ancestral property", r"joint family property", r"coparcen",
                              r"hindu succession act", r"shares? (of the parties )?in the (suit |joint |ancestral |disputed )?(property|land)",
                              r"family settlement"],
    "land_records": [r"\bmutation\b", r"record of rights", r"revenue (records?|entr)", r"\bkhasra", r"khatauni",
                     r"jamabandi", r"\b7/12\b", r"land revenue code", r"\btehsildar", r"\bpatta\b", r"survey (no|number)",
                     r"\bconsolidation\b", r"(land )?ceiling (act|law|limit)", r"surplus land", r"disputed land", r"\bsuit land"],
    "land_acquisition": [r"land acquisition", r"acquisition of (the )?lands?", r"compensation for (the )?(acquired )?lands?",
                         r"\bacquisition\b.{0,80}\blands?\b|\blands?\b.{0,80}\bacquisition\b", r"acquired lands?",
                         r"right to fair compensation", r"\brfctlarr", r"acquiring body", r"award of (the )?collector"],
    "tenancy_rent": [r"\beviction\b", r"rent control", r"\blandlord", r"\btenan(t|ts|cy|ted)\b", r"\blessee\b", r"arrears of rent"],
    "builder_rera": [r"\brera\b", r"real estate \(regulation", r"flat buyers?", r"homebuyers?", r"\ballottees?\b",
                     r"possession of (the )?(flat|apartment|unit)"],
    "easement": [r"\beasement", r"right of way"],
    "adverse_possession": [r"adverse possession"],
    "property_fraud": [r"forged (sale |gift |power of attorney )?deeds?", r"fabricated (sale |gift )?deeds?",
                       r"impersonat\w* .{0,60}(owner|vendor|seller|land|property)",
                       r"(forg\w+|cheat\w*|fraud\w*).{0,80}(sale deed|property|land|plot|flat)"],
    "benami_mortgage": [r"\bbenami\b", r"\bmortgag", r"redemption of (the )?mortgage", r"equity of redemption"],
}
_TAG_RES = {t: [re.compile(p, re.I) for p in ps] for t, ps in TAGS.items()}

# Statutes that make a property dispute likely.
STATUTES = {
    "Transfer of Property Act": r"transfer of property act",
    "Specific Relief Act": r"specific relief act",
    "Registration Act": r"(?<!societies )(?<!society )(?<!companies )(?<!vehicle )\bregistration act\b",
    "Land Revenue Code / Act": r"land (and )?revenue (code|act|regulation)",
    "Rent Control Act": r"rent (control|act)|rent control",
    "Tenancy Act": r"tenancy (act|and agricultural lands)",
    "Land Acquisition Act": r"land acquisition act",
    "RFCTLARR Act 2013": r"right to fair compensation and transparency|rfctlarr",
    "RERA 2016": r"real estate \(regulation and development\)|\brera\b",
    "Easements Act": r"easements act",
    "Benami Act": r"benami (transactions )?(\(prohibition\) )?act",
    "Partition Act": r"\bpartition act\b",
    "Hindu Succession Act": r"hindu succession act",
    "Indian Stamp Act": r"stamp act",
    "Limitation Act Art. 65": r"article 65 of the limitation act|limitation act.{0,40}article 65",
}
_STATUTE_RES = {k: re.compile(v, re.I) for k, v in STATUTES.items()}

# Things that use property words but aren't property disputes.
EXCLUSIONS = {
    "NDPS / narcotics": r"\bndps\b|narcotic drugs|psychotropic|\bganja\b|\bheroin\b|\bcharas\b|contraband",
    "Arms Act": r"\barms act\b|possession of (a |an )?(fire)?arms?\b|unlicensed (fire)?arm",
    "Bail": r"\bbail application\b|anticipatory bail|application for bail|grant of bail",
    "Tax": r"\bincome[- ]tax act\b|\bgst\b|goods and services tax|customs act|central excise",
    "Service matter": r"\bseniority\b|disciplinary (proceedings|authority)|\bpension\b|regularisation of service|promotion to the post",
    "Matrimonial": r"\bdivorce\b|maintenance under section 125|\bdowry\b|domestic violence act",
    "Motor accident": r"motor (vehicles|accident) (act|claims)",
    "Arbitration only": r"arbitration and conciliation act",
    "Money laundering": r"prevention of money[- ]laundering|\bpmla\b|directorate of enforcement|enforcement directorate",
    "Securities": r"securities and exchange board|\bsebi\b|securities appellate tribunal",
    "Corruption": r"prevention of corruption act",
}
_EXCL_RES = {k: re.compile(v, re.I) for k, v in EXCLUSIONS.items()}

# High Court case-type codes (title prefix / case_details.case_type).
CIVIL_APPEAL_TYPES = {"SA", "RSA", "FA", "RFA", "AO", "FAO", "CS", "OS", "CRP", "RCRP", "XFA", "SAO", "RSAO", "CRA", "CR",
                      "LPA", "CMSA", "MSA", "RCR", "RP"}
NEGATIVE_TYPES = {"CRMA", "CRMAB", "CRMAM", "WPCR", "CRIA", "CRIR", "BA", "ABA", "TXA", "ITA", "COAP", "AAR", "ARP",
                  "CRLA", "CRLP", "CRLMC", "CRLRC", "BAIL", "MCRC", "CRA(S)", "CRMP"}
PROPERTY_PARTIES = re.compile(r"\b(developers?|builders?|housing (society|board)|land acquisition officer|"
                              r"special land acquisition|collector|tehsildar|nagar (nigam|palika)|development authority|"
                              r"improvement trust|cooperative housing)\b", re.I)


@dataclass
class Decision:
    verdict: str  # stage 1: candidate | reject. Stage 2: accept | reject | borderline
    stage: str  # metadata | fulltext
    score: float
    reasons: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    statutes: list[str] = field(default_factory=list)


def _tag_hits(text: str) -> dict[str, int]:
    """Tag -> number of distinct patterns matched."""
    return {t: n for t, rs in _TAG_RES.items() if (n := sum(1 for r in rs if r.search(text)))}


def _statutes(text: str) -> list[str]:
    return [k for k, r in _STATUTE_RES.items() if r.search(text)]


def _exclusions(text: str) -> list[str]:
    return [k for k, r in _EXCL_RES.items() if r.search(text)]


def acts_text(acts: list[dict]) -> str:
    return " ; ".join(f"{a.get('act') or ''} {a.get('section') or ''}" for a in acts)


def _only_procedural_acts(acts: list[dict]) -> bool:
    """Acts that say nothing about the subject: Limitation s.5 (condonation of delay), Constitution 226/227, CPC."""
    proc = re.compile(r"limitation act|constitution of india|code of civil procedure|civil procedure code|"
                      r"code of criminal procedure", re.I)
    return bool(acts) and all(proc.search(a.get("act") or "") for a in acts)


# ---------- Stage 1: metadata ----------

STAGE1_THRESHOLD = 2.0
# Weak signals: Stage 1 decides what's worth downloading, so it favours recall (stage 2 brings precision).
PROPERTY_NOUNS = re.compile(r"\b(land|lands|plot|plots|immovable|property|properties|premises|flat|house|lease|leased|tenant|"
                            r"allotment|allotted|acquisition|acquired|site|building|shop|godown|estate)\b", re.I)
SECOND_APPEAL = re.compile(r"second appeal|s\.\s?100 (of )?(the )?(cpc|code of civil procedure)|section 100 (of )?(the )?(cpc|code)", re.I)


def stage1(record) -> Decision:
    """Cheap pre-filter on title, headnote/description, parties, case type and acts. No download."""
    text = " ".join(filter(None, [record.title, record.description, record.petitioner, record.respondent, acts_text(record.acts)]))
    score, reasons = 0.0, []
    hits = _tag_hits(text)
    for tag, n in hits.items():
        score += 2 + min(n - 1, 2) * 0.5
        reasons.append(f"+ {tag} ({n} cue{'s' if n > 1 else ''})")
    statutes = _statutes(text)
    if statutes:
        score += 3
        reasons.append("+ statute: " + ", ".join(statutes))
    ct = (record.case_type or "").upper()
    if ct in CIVIL_APPEAL_TYPES:
        score += 2
        reasons.append(f"+ civil case type {ct}")
    elif ct in NEGATIVE_TYPES:
        score -= 3
        reasons.append(f"- criminal/other case type {ct}")
    if PROPERTY_PARTIES.search(text):
        score += 1
        reasons.append("+ property-related party")
    nouns = {m.lower() for m in PROPERTY_NOUNS.findall(text)}
    if nouns:
        score += 1 if len(nouns) == 1 else 2
        reasons.append("+ property words: " + ", ".join(sorted(nouns)[:5]))
    if SECOND_APPEAL.search(text):
        score += 1
        reasons.append("+ civil second appeal")
    if record.acts and _only_procedural_acts(record.acts) and not hits:
        score -= 1
        reasons.append("- only procedural acts (e.g. Limitation s.5, Art. 226/227)")
    excl = _exclusions(text)
    if excl and score < 5:
        score -= 4
        reasons.append("- excluded: " + ", ".join(excl))
    verdict = "candidate" if score >= STAGE1_THRESHOLD else "reject"
    # Most SC metadata has no headnote (only 2024+ has some), so the title alone can't decide: let the
    # full text judge, unless the metadata is clearly out of scope.
    if record.source == "sc" and len((record.description or "").strip()) < 80 and verdict == "reject" and score > -2:
        verdict = "candidate"
        reasons.append("no headnote in the dataset: judged on the full text")
    return Decision(verdict, "metadata", score, reasons or ["no property signals"], sorted(hits), statutes)


# ---------- Stage 2: full text ----------

ACCEPT_AT, REJECT_BELOW = 9.0, 4.0
GLOSSARY_PROPERTY_TERMS = {
    "agreement_to_sell", "sale_deed", "conveyance", "consideration", "earnest_money", "balance_consideration",
    "possession", "part_performance", "title", "encumbrance", "encumbrance_certificate", "seven_twelve", "mutation",
    "khata", "khasra_khatauni", "survey_number", "registration", "specific_performance", "lis_pendens", "injunction",
    "adverse_possession", "benami", "partition", "rera", "freehold_leasehold", "na_permission", "vendor_purchaser",
}


def stage2(record, text: str) -> Decision:
    """Score the judgment's text. Only the first ~60k characters count (the facts and issues come first)."""
    from app.services import glossary

    body = text[:60_000]
    head = " ".join(filter(None, [record.title, record.description, acts_text(record.acts)]))
    full = f"{head}\n{body}"
    hits = _tag_hits(full)
    statutes = _statutes(full)
    terms = {h.term_id for h in glossary.find_terms([body])} & GLOSSARY_PROPERTY_TERMS
    excl = _exclusions(body[:15_000] + " " + head)  # exclusions judged on the opening, where the subject is set out
    score = sum(2 + min(n - 1, 3) * 0.75 for n in hits.values()) + 2.5 * len(statutes) + 0.5 * len(terms)
    reasons = [f"+ {t} ({n})" for t, n in sorted(hits.items(), key=lambda x: -x[1])]
    if statutes:
        reasons.append("+ statutes: " + ", ".join(statutes))
    if terms:
        reasons.append(f"+ {len(terms)} property terms")
    ct = (record.case_type or "").upper()
    if excl:
        penalty = 6 if len(hits) <= 2 else 3
        if ct in CIVIL_APPEAL_TYPES:  # a civil appeal mentioning e.g. a divorce is still usually about property
            penalty /= 2
        score -= penalty * len(excl)
        reasons.append("- excluded: " + ", ".join(excl))
    if ct in NEGATIVE_TYPES:
        score -= 3
        reasons.append(f"- case type {ct}")
    verdict = "accept" if score >= ACCEPT_AT else "reject" if score < REJECT_BELOW else "borderline"
    # Main tags: matched at least twice, or the strongest two.
    tags = sorted([t for t, n in hits.items() if n >= 2] or sorted(hits, key=hits.get, reverse=True)[:2])
    return Decision(verdict, "fulltext", round(score, 2), reasons or ["no property signals"], tags, statutes)


def property_score(score: float) -> float:
    """Squash a stage-2 score to 0-1 (about 0.5 at the borderline midpoint)."""
    import math

    return round(1 / (1 + math.exp(-(score - (ACCEPT_AT + REJECT_BELOW) / 2) / 1.5)), 3)

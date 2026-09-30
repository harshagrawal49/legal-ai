"""Ingest Supreme Court of India judgments from the public AWS Open Data dataset.

Dataset: s3://indian-supreme-court-judgments (metadata as parquet per year, English PDFs per judgment).

Usage (from backend/):
    uv run python -m ingest.supreme_court --year 2023 --limit 50

Each judgment is: downloaded -> text extracted -> split into paragraphs -> summarised by the bulk model
-> embedded -> saved. Already-ingested judgments are skipped, so the script can be re-run safely.
For tens of thousands of judgments, move the summarisation step to the Message Batches API (50% cheaper).
"""

import argparse
import io
import json
import logging
from datetime import date, datetime
from pathlib import Path

import httpx
import openai
import pandas as pd

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.llm import prompts
from app.llm.client import LLMRefusal, structured
from app.llm.schemas import JudgmentSummary
from app.models import Judgment, JudgmentParagraph
from app.services.embeddings import embed_documents
from ingest.pdf_text import pdf_to_text, split_paragraphs

BUCKET = "https://indian-supreme-court-judgments.s3.amazonaws.com"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "sc"
MAX_SUMMARY_CHARS = 500_000  # ~125k tokens; longer judgments are summarised from their first part

log = logging.getLogger("ingest")


def _get(url: str) -> bytes:
    """Download with a local cache so re-runs don't re-download."""
    path = CACHE_DIR / url.removeprefix(BUCKET + "/")
    if not path.exists():
        resp = httpx.get(url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
    return path.read_bytes()


def load_metadata(year: int) -> pd.DataFrame:
    df = pd.read_parquet(io.BytesIO(_get(f"{BUCKET}/metadata/parquet/year={year}/metadata.parquet")))
    return df[df["available_languages"].fillna("").str.contains("ENG")]


def _parse_date(value: str | None) -> date | None:
    try:
        return datetime.strptime(value, "%d-%m-%Y").date() if value else None
    except ValueError:
        return None


def summarise(title: str, paragraphs: list[tuple[int, str]]) -> JudgmentSummary:
    body = "\n\n".join(f"[¶{n}] {t}" for n, t in paragraphs)
    if len(body) > MAX_SUMMARY_CHARS:
        log.warning("%s: text is %d chars, summarising the first %d", title, len(body), MAX_SUMMARY_CHARS)
        body = body[:MAX_SUMMARY_CHARS]
    return structured(
        JudgmentSummary,
        prompts.JUDGMENT_SUMMARY_SYSTEM,
        f"<judgment title=\"{title}\">\n{body}\n</judgment>",
        model=get_settings().model_bulk,
        max_tokens=8000,
    )


def ingest_row(row: dict, year: int) -> Judgment | None:
    pdf_url = f"{BUCKET}/data/pdf/year={year}/english/{row['path']}_EN.pdf"
    try:
        text = pdf_to_text(_get(pdf_url))
    except httpx.HTTPStatusError as e:
        log.warning("skip %s: PDF unavailable (%s)", row["path"], e.response.status_code)
        return None

    paragraphs = split_paragraphs(text)
    if sum(len(t) for _, t in paragraphs) < 500:
        log.warning("skip %s: too little text (scanned PDF? needs OCR)", row["path"])
        return None

    summary = summarise(row["title"], paragraphs)
    summary_text = f"{summary.case_type}. {summary.facts} {summary.holding}"
    vectors = embed_documents([summary_text] + [t for _, t in paragraphs])

    return Judgment(
        id=row["path"],
        title=row["title"] or row["path"],
        petitioner=row["petitioner"],
        respondent=row["respondent"],
        court=row["court"] or "Supreme Court of India",
        decision_date=_parse_date(row["decision_date"]),
        citation=row["citation"] or None,
        neutral_citation=row["case_id"] or row["nc_display"],
        judges=row["judge"],
        disposal=row["disposal_nature"],
        source_url=pdf_url,
        summary=summary.model_dump(),
        summary_embedding=vectors[0],
        paragraphs=[
            JudgmentParagraph(para_no=n, text=t, embedding=v)
            for (n, t), v in zip(paragraphs, vectors[1:], strict=True)
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--limit", type=int, default=20, help="max judgments to ingest this run")
    parser.add_argument(
        "--match", nargs="+", help="only titles/descriptions containing any of these texts (case-insensitive)"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    init_db()
    df = load_metadata(args.year)
    if args.match:
        haystack = (df["title"].fillna("") + " " + df["description"].fillna("")).str.lower()
        terms = [t.lower() for t in args.match]
        df = df[haystack.apply(lambda h: any(t in h for t in terms))]
    log.info("%d English judgments available for %d", len(df), args.year)

    done = 0
    with SessionLocal() as db:
        rows = df.astype(object).where(df.notna(), None).to_dict("records")  # NaN/NA -> None
        for row in rows:
            if done >= args.limit:
                break
            if db.get(Judgment, row["path"]):
                continue
            try:
                judgment = ingest_row(row, args.year)
            except LLMRefusal as e:
                log.warning("skip %s: summary declined (%s)", row["path"], e)
                continue
            except openai.APIError as e:  # provider overloaded or rate-limited even after retries
                log.warning("skip %s: LLM error (%s); re-run later to retry", row["path"], e)
                continue
            if judgment is None:
                continue
            db.add(judgment)
            db.commit()
            done += 1
            log.info("[%d/%d] %s — %s", done, args.limit, judgment.id, json.dumps(judgment.summary["outcome"]))

    log.info("ingested %d judgments", done)


if __name__ == "__main__":
    main()

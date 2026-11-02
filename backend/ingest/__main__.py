"""Ingest property and land dispute judgments into Postgres: one command.

    cd backend
    uv run python -m ingest                      # everything in scope; incremental (only what's new)
    uv run python -m ingest --dry-run --limit 50 # see what would be ingested; needs no database
    uv run python -m ingest --stats              # what's in the corpus

Default scope (ingest_plan.md §9):
  Supreme Court: all years (1950–now).
  High Courts:   Bombay (27_1) and the other courts whose dataset lists acts per case
                 (2_5, 9_13, 23_23), 2018–now.

Every record is filtered in four stages (metadata → full text → semantic → optional LLM); only property
and land disputes are stored, with paragraphs and local embeddings and no LLM call (summaries are
written when a judgment is first opened). Re-running is safe and incremental: unchanged dataset
partitions are skipped, decided records are never re-downloaded, and failures are retried (up to 3 times).
Ctrl-C stops cleanly; everything done so far is kept.

Requires Postgres with pgvector (`docker compose up -d` from the repo root) except with --dry-run.
"""

import argparse
import json
import logging
import sys
from datetime import date

from ingest.pipeline import Config, report, run


def years(spec: str | None) -> list[int] | None:
    """'2015-2026' | '2024' | '2019,2021' | 'all' -> list of years (None = default range)."""
    if not spec or spec == "all":
        return None
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b or date.today().year) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m ingest", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", nargs="+", choices=["sc", "hc"], default=["sc", "hc"], help="which datasets (default: both)")
    p.add_argument("--years", help="SC years, e.g. 2015-2026, 2024, 2019,2021 (default: all)")
    p.add_argument("--hc-years", help="HC years (default: 2018-now)")
    p.add_argument("--courts", nargs="+", default=["27_1", "2_5", "9_13", "23_23"], help="HC court codes (default: 27_1 2_5 9_13 23_23)")
    p.add_argument("--limit", type=int, help="max candidate judgments to download and judge this run (default: no limit)")
    p.add_argument("--dry-run", action="store_true", help="run the filters but store nothing (no database needed)")
    p.add_argument("--full", action="store_true", help="re-scan partitions even if unchanged since the last run")
    p.add_argument("--reprocess", action="store_true", help="re-judge records already decided (after changing the rules)")
    p.add_argument("--llm-budget", type=int, default=None, help="max LLM checks for borderline cases (default: 50 if an API key is set, else 0)")
    p.add_argument("--workers", type=int, default=4, help="parallel downloads (default: 4)")
    p.add_argument("--sample-csv", help="also write every decision to this CSV (for hand-labelling the filter)")
    p.add_argument("--stats", action="store_true", help="print corpus statistics and exit")
    p.add_argument("-q", "--quiet", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpcore", "fastembed"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if a.stats:
        from app.db import SessionLocal, init_db
        from ingest.store import corpus_stats

        init_db()
        with SessionLocal() as db:
            print(json.dumps(corpus_stats(db), indent=2, default=str))
        return 0

    from app.config import get_settings

    budget = a.llm_budget if a.llm_budget is not None else (50 if get_settings().llm_api_key else 0)
    cfg = Config(sources=a.source, sc_years=years(a.years), hc_years=years(a.hc_years), hc_courts=a.courts,
                 limit=a.limit, dry_run=a.dry_run, full=a.full, reprocess=a.reprocess, llm_budget=budget,
                 workers=a.workers, sample_csv=a.sample_csv)
    if a.dry_run:
        from ingest.store import MemoryStore

        store = MemoryStore()
    else:
        try:
            from ingest.store import PostgresStore

            store = PostgresStore()
        except Exception as e:
            print(f"Could not connect to Postgres ({type(e).__name__}). Start it with `docker compose up -d` from the repo "
                  "root and check DATABASE_URL in backend/.env, or use --dry-run.", file=sys.stderr)
            return 2
    stats = run(cfg, store)
    print(report(stats, a.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())

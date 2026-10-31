"""Where the ingester keeps its results: Postgres (normal runs) or memory (--dry-run, no database needed).

Both implement the same small interface, so a dry run exercises exactly the code path of a real run.
"""

import logging
from collections import Counter
from datetime import datetime, timezone

log = logging.getLogger("ingest")
DONE_STATUSES = {"accepted", "rejected", "unavailable"}
MAX_ATTEMPTS = 3


class MemoryStore:
    """Keeps everything in memory; nothing is written anywhere. Used by --dry-run and tests."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}
        self.judgments: dict[str, dict] = {}
        self.watermarks: dict[str, str] = {}
        self.runs: list[dict] = []

    def known(self, source: str, keys: list[str]) -> dict[str, dict]:
        return {k: self.items[(source, k)] for k in keys if (source, k) in self.items}

    def record_item(self, rec, status, stage=None, score=None, reasons=None, error=None, version=None):
        prev = self.items.get((rec.source, rec.key), {})
        self.items[(rec.source, rec.key)] = {
            "status": status, "stage": stage, "score": score, "reasons": reasons or [], "last_error": error,
            "attempts": prev.get("attempts", 0) + (1 if status == "failed" else 0), "title": rec.title,
            "partition": rec.partition,
        }

    def save_judgment(self, judgment: dict, paragraphs: list[tuple[int, str, list[float]]]):
        self.judgments[judgment["id"]] = {**judgment, "paragraphs": paragraphs}

    def watermark(self, partition_id: str) -> str | None:
        return self.watermarks.get(partition_id)

    def set_watermark(self, partition_id: str, etag: str | None, last_modified: str | None, rows: int):
        self.watermarks[partition_id] = etag

    def start_run(self, args: dict) -> int:
        self.runs.append({"args": args, "status": "running"})
        return len(self.runs)

    def finish_run(self, run_id: int, stats: dict, status: str):
        self.runs[run_id - 1].update(stats=stats, status=status)

    def commit(self):
        pass


class PostgresStore:
    def __init__(self):
        from app.db import SessionLocal, init_db

        init_db()  # creates tables / adds the ingestion columns if needed
        self.db = SessionLocal()

    def known(self, source: str, keys: list[str]) -> dict[str, dict]:
        from sqlalchemy import select

        from app.models import IngestionItem

        out = {}
        for i in range(0, len(keys), 1000):
            for item in self.db.scalars(select(IngestionItem).where(IngestionItem.source == source, IngestionItem.key.in_(keys[i:i + 1000]))):
                out[item.key] = {"status": item.status, "attempts": item.attempts}
        return out

    def record_item(self, rec, status, stage=None, score=None, reasons=None, error=None, version=None):
        from sqlalchemy import select

        from app.models import IngestionItem

        item = self.db.scalar(select(IngestionItem).where(IngestionItem.source == rec.source, IngestionItem.key == rec.key))
        if item is None:
            item = IngestionItem(source=rec.source, key=rec.key, partition=rec.partition, attempts=0)
            self.db.add(item)
        item.status, item.stage, item.score, item.reasons = status, stage, score, (reasons or [])[:20]
        item.last_error = (error or "")[:2000] or None
        item.pipeline_version = version
        if status == "failed":
            item.attempts = (item.attempts or 0) + 1

    def save_judgment(self, judgment: dict, paragraphs: list[tuple[int, str, list[float]]]):
        from app.models import Judgment, JudgmentParagraph

        existing = self.db.get(Judgment, judgment["id"])
        if existing is not None:  # re-processing: replace
            self.db.delete(existing)
            self.db.flush()
        j = Judgment(**judgment)
        j.paragraphs = [JudgmentParagraph(para_no=n, text=t, embedding=v) for n, t, v in paragraphs]
        self.db.add(j)

    def watermark(self, partition_id: str) -> str | None:
        from app.models import SourcePartition

        p = self.db.get(SourcePartition, partition_id)
        return p.etag if p and p.completed_at else None

    def set_watermark(self, partition_id: str, etag: str | None, last_modified: str | None, rows: int):
        from app.models import SourcePartition

        p = self.db.get(SourcePartition, partition_id) or SourcePartition(id=partition_id)
        p.etag, p.last_modified, p.rows, p.completed_at = etag, last_modified, rows, datetime.now(timezone.utc)
        self.db.merge(p)
        self.db.commit()

    def start_run(self, args: dict) -> int:
        from app.models import IngestionRun

        run = IngestionRun(args=args, stats={}, status="running")
        self.db.add(run)
        self.db.commit()
        return run.id

    def finish_run(self, run_id: int, stats: dict, status: str):
        from app.models import IngestionRun

        run = self.db.get(IngestionRun, run_id)
        run.stats, run.status, run.finished_at = stats, status, datetime.now(timezone.utc)
        self.db.commit()

    def commit(self):
        self.db.commit()


def corpus_stats(db) -> dict:
    """Counts for `python -m ingest --stats` and GET /corpus/stats."""
    from sqlalchemy import func, select

    from app.models import IngestionItem, IngestionRun, Judgment

    by_source = dict(db.execute(select(Judgment.source, func.count()).group_by(Judgment.source)).all())
    by_court = dict(db.execute(select(Judgment.court, func.count()).group_by(Judgment.court)).all())
    tags = Counter()
    for (t,) in db.execute(select(Judgment.topic_tags)):
        tags.update(t or [])
    items = dict(db.execute(select(IngestionItem.status, func.count()).group_by(IngestionItem.status)).all())
    last = db.scalar(select(IngestionRun).where(IngestionRun.status.in_(["done", "interrupted"])).order_by(IngestionRun.id.desc()))
    latest = db.scalar(select(func.max(Judgment.decision_date)))
    return {
        "judgments": sum(by_source.values()),
        "by_source": {k or "legacy": v for k, v in by_source.items()},
        "by_court": by_court,
        "by_tag": dict(tags.most_common()),
        "ingestion_items": items,
        "last_run_at": last.finished_at.isoformat() if last and last.finished_at else None,
        "last_run_stats": last.stats if last else None,
        "latest_decision_date": latest.isoformat() if latest else None,
    }

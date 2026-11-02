"""Readers for the two public court-judgment datasets on AWS Open Data (plain HTTPS, no AWS account).

  Supreme Court   https://indian-supreme-court-judgments.s3.amazonaws.com
                  metadata/parquet/year=Y/metadata.parquet  ·  data/pdf/year=Y/english/<path>_EN.pdf
  High Courts     https://indian-high-court-judgments.s3.amazonaws.com
                  metadata/parquet/year=Y/court=C/bench=B/metadata.parquet
                  metadata/parquet_case_details/court=C/bench=B/case_details-mobile.parquet (some courts: acts!)
                  data/pdf/year=Y/court=C/bench=B/<basename of pdf_link>

Both datasets' availability flags are unreliable (`available_languages` is empty for most 2026 SC rows,
`pdf_exists` is False for HC rows whose PDFs exist), so we never filter on them: a missing PDF is
discovered by its 404 when it's fetched. Everything downloaded is cached under data/ingest-cache/.
"""

import ast
import io
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import httpx
import pandas as pd

log = logging.getLogger("ingest")

SC_BUCKET = "https://indian-supreme-court-judgments.s3.amazonaws.com"
HC_BUCKET = "https://indian-high-court-judgments.s3.amazonaws.com"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "ingest-cache"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


@dataclass
class Record:
    """One judgment/order from either dataset, normalised."""

    source: str  # sc | hc
    key: str  # becomes Judgment.id
    partition: str  # "2024" or "2025/27_1/hcbgoa"
    title: str
    court: str
    pdf_key: str  # object key in the bucket
    description: str = ""  # SC headnote; HC opening lines
    petitioner: str | None = None
    respondent: str | None = None
    decision_date: date | None = None
    citation: str | None = None
    neutral_citation: str | None = None
    judges: str | None = None
    disposal: str | None = None
    cnr: str | None = None
    court_code: str | None = None
    bench: str | None = None
    case_type: str | None = None
    acts: list[dict] = field(default_factory=list)
    lower_court: str | None = None

    @property
    def bucket(self) -> str:
        return SC_BUCKET if self.source == "sc" else HC_BUCKET

    @property
    def pdf_url(self) -> str:
        return f"{self.bucket}/{self.pdf_key}"


# ---------- HTTP with retries and a disk cache ----------

_client = httpx.Client(timeout=120, follow_redirects=True)


def _request(method: str, url: str, attempts: int = 4) -> httpx.Response:
    for i in range(attempts):
        try:
            r = _client.request(method, url)
            if r.status_code in (429, 500, 502, 503, 504) and i < attempts - 1:
                raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
            return r
        except (httpx.TransportError, httpx.HTTPStatusError):
            if i == attempts - 1:
                raise
            time.sleep(2 ** i)
    raise RuntimeError("unreachable")


def fetch(url: str, cache: bool = True) -> bytes | None:
    """Bytes at `url`, or None for 404. Cached on disk unless cache=False (e.g. files that change)."""
    path = CACHE_DIR / re.sub(r"^https://", "", url)
    if cache and path.exists():
        return path.read_bytes()
    r = _request("GET", url)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    return r.content


def head(url: str) -> tuple[str | None, str | None]:
    """(ETag, Last-Modified) of an object, or (None, None) if it doesn't exist."""
    r = _request("HEAD", url)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    return r.headers.get("etag", "").strip('"') or None, r.headers.get("last-modified")


def fetch_versioned(url: str, etag: str | None) -> bytes:
    """A file that changes over time (metadata parquet): re-download only when its ETag changed."""
    path = CACHE_DIR / re.sub(r"^https://", "", url)
    tag = path.with_suffix(path.suffix + ".etag")
    if etag and path.exists() and tag.exists() and tag.read_text() == etag:
        return path.read_bytes()
    data = fetch(url, cache=False)
    if data is None:
        raise FileNotFoundError(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if etag:
        tag.write_text(etag)
    return data


def list_prefixes(bucket: str, prefix: str) -> list[str]:
    """Immediate sub-prefixes ("folders") under `prefix`, following S3 pagination."""
    out, token = [], None
    while True:
        url = f"{bucket}/?list-type=2&delimiter=/&prefix={prefix}" + (f"&continuation-token={token}" if token else "")
        r = _request("GET", url)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        out += [p.findtext(f"{S3_NS}Prefix") for p in root.iter(f"{S3_NS}CommonPrefixes")]
        token = root.findtext(f"{S3_NS}NextContinuationToken")
        if not token:
            return out


def _value(prefix: str, name: str) -> str:
    """'metadata/parquet/year=2025/court=27_1/' -> value of `name=` ('27_1')."""
    m = re.search(rf"{name}=([^/]+)", prefix)
    return m.group(1) if m else ""


# ---------- Parsing helpers ----------


def _clean(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return None if s in ("", "nan", "None", "NaT") else s


def parse_date(v) -> date | None:
    s = _clean(v)
    if not s:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


CASE_TYPE_RE = re.compile(r"^\s*([A-Z][A-Z.()]*?)\s*/")


def case_type_from_title(title: str) -> str | None:
    m = CASE_TYPE_RE.match(title or "")
    return m.group(1).replace(".", "").replace("(", "").replace(")", "") if m else None


def parse_acts(v) -> list[dict]:
    """The case-details `acts` column: a list/array of {act, section}, or its string form."""
    if v is None:
        return []
    if isinstance(v, str):
        try:
            v = ast.literal_eval(v.replace("\n", ","))
        except (ValueError, SyntaxError):
            return []
    try:
        items = list(v)
    except TypeError:
        return []
    out = []
    for a in items:
        if isinstance(a, dict) and _clean(a.get("act")):
            out.append({"act": _clean(a.get("act")), "section": _clean(a.get("section"))})
    return out


# ---------- Supreme Court ----------


def sc_years() -> list[int]:
    return sorted(int(_value(p, "year")) for p in list_prefixes(SC_BUCKET, "metadata/parquet/") if _value(p, "year").isdigit())


def sc_partition_url(year: int) -> str:
    return f"{SC_BUCKET}/metadata/parquet/year={year}/metadata.parquet"


def sc_records(year: int, etag: str | None = None) -> list[Record]:
    df = pd.read_parquet(io.BytesIO(fetch_versioned(sc_partition_url(year), etag)))
    out = []
    for row in df.to_dict("records"):
        path = _clean(row.get("path"))
        if not path:
            continue
        out.append(Record(
            source="sc", key=path, partition=str(year), title=_clean(row.get("title")) or path,
            court=_clean(row.get("court")) or "Supreme Court of India",
            # English PDF for every row: the language flag is unreliable, so a 404 decides instead.
            pdf_key=f"data/pdf/year={year}/english/{path}_EN.pdf",
            description=_clean(row.get("description")) or "",
            petitioner=_clean(row.get("petitioner")), respondent=_clean(row.get("respondent")),
            decision_date=parse_date(row.get("decision_date")), citation=_clean(row.get("citation")),
            neutral_citation=_clean(row.get("case_id")) or _clean(row.get("nc_display")),
            judges=_clean(row.get("judge")), disposal=_clean(row.get("disposal_nature")), cnr=_clean(row.get("cnr")),
        ))
    return out


# ---------- High Courts ----------


def hc_courts(year: int) -> list[str]:
    return [_value(p, "court") for p in list_prefixes(HC_BUCKET, f"metadata/parquet/year={year}/")]


def hc_benches(year: int, court: str) -> list[str]:
    return [_value(p, "bench") for p in list_prefixes(HC_BUCKET, f"metadata/parquet/year={year}/court={court}/")]


def hc_partition_url(year: int, court: str, bench: str) -> str:
    return f"{HC_BUCKET}/metadata/parquet/year={year}/court={court}/bench={bench}/metadata.parquet"


def hc_case_details(court: str, bench: str) -> dict[str, dict]:
    """cnr -> case details (case type, parties, acts), where the dataset has them (some courts only)."""
    url = f"{HC_BUCKET}/metadata/parquet_case_details/court={court}/bench={bench}/case_details-mobile.parquet"
    etag, _ = head(url)
    if etag is None:
        return {}
    df = pd.read_parquet(io.BytesIO(fetch_versioned(url, etag)))
    return {str(r["cnr"]): r for r in df.to_dict("records") if _clean(r.get("cnr"))}


def hc_records(year: int, court: str, bench: str, etag: str | None = None) -> list[Record]:
    df = pd.read_parquet(io.BytesIO(fetch_versioned(hc_partition_url(year, court, bench), etag)))
    details = hc_case_details(court, bench)
    out = []
    for row in df.to_dict("records"):
        link = _clean(row.get("pdf_link"))
        if not link:
            continue
        filename = link.rsplit("/", 1)[-1]
        cnr = _clean(row.get("cnr"))
        d = details.get(cnr or "", {})
        title = _clean(row.get("title")) or filename
        out.append(Record(
            source="hc", key=f"hc_{court}_{bench}_{filename.removesuffix('.pdf')}",
            partition=f"{year}/{court}/{bench}", title=title, court=_clean(row.get("court")) or f"High Court {court}",
            pdf_key=f"data/pdf/year={year}/court={court}/bench={bench}/{filename}",
            description=_clean(row.get("description")) or "",
            petitioner=_clean(d.get("petitioner")), respondent=_clean(d.get("respondent")),
            decision_date=parse_date(row.get("decision_date")), judges=_clean(row.get("judge")),
            disposal=_clean(row.get("disposal_nature")), cnr=cnr, court_code=court, bench=bench,
            case_type=_clean(d.get("case_type")) or case_type_from_title(title),
            acts=parse_acts(d.get("acts")), lower_court=_clean(d.get("lower_court")),
        ))
    return out

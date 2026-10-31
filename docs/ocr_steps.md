# OCR: step-by-step reference

How OCR works in NyayaSathi, and every step to install, configure, test, benchmark, choose an engine
and troubleshoot it. The design is in [`ocr_plan.md`](../ocr_plan.md); the engine comparison and the
decision (Tesseract) are in [`ocr_report.md`](ocr_report.md).

---

## 0. What OCR does in this app

- **What it reads:** scanned PDF pages and phone photos (JPG/PNG). A photo is converted to a one-page PDF first.
- **Which pages:** only pages with almost no selectable text and an image on them. Typed pages keep
  their text, so a typed agreement with a scanned annexure works.
- **Where:** fully on the server (local engines), in the background after upload. The app shows
  "Reading and extracting facts…" until it's done.
- **What is stored:** the OCR text exactly as the engine read it (never "fixed" by an LLM), plus per
  page the source, engine and confidence (`case_documents.page_info`). The uploaded file itself is
  never stored; the PDF bytes are held in memory only until OCR finishes.
- **What the user sees:** pages and source links marked **"read by OCR"**, with flags for
  low-confidence pages (`ocr_low_confidence`) and pages that couldn't be read (`ocr_page_not_read`).

Code map:

| File | Role |
|---|---|
| `backend/app/services/ocr.py` | Engine interface, `TesseractEngine`, `PaddleEngine`, engine selection, page detection, rendering |
| `backend/app/services/documents.py` | `prepare_upload` (photo → PDF), `read_pdf` (which pages need OCR), `run_ocr`, background processing |
| `backend/app/services/evidence.py` | `ocr_flags`, `from_ocr` on every source reference |
| `backend/app/services/brief.py` | OCR page count and average confidence per document |
| `backend/eval/scans.py` | Synthetic scans at 3 quality levels (clean / photo / degraded) |
| `backend/eval/run_ocr_eval.py` | Engine comparison benchmark |
| `backend/tests/test_ocr.py` | OCR unit tests (+ real-engine tests when installed) |
| `android/.../ui/documents/*` | "Read by OCR" labels, per-page confidence, photo upload |

---

## 1. Install the engines

### 1a. Tesseract (default engine, required for OCR)

macOS:
```bash
brew install tesseract tesseract-lang     # tesseract-lang adds hin, mar and ~100 other languages
tesseract --version                       # expect 5.x
tesseract --list-langs | grep -E "eng|hin|mar"
```
Ubuntu / Debian / Docker:
```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-mar
```
The Python wrapper (`pytesseract`) is already a project dependency: `cd backend && uv sync`.

### 1b. PaddleOCR (optional second engine)

```bash
cd backend
uv sync --extra paddle        # installs paddleocr + paddlepaddle (large: several hundred MB)
```
The first OCR call downloads the recognition models (internet needed once; they're cached
afterwards). To pre-download them and check the install:
```bash
RUN_PADDLE_TESTS=1 uv run python -m pytest tests/test_ocr.py -k paddle -rs
```
Installed versions on the dev machine (2026-10-31): `paddleocr 3.7.0`, `paddlepaddle 3.3.1` (Apple Silicon, CPU).

### 1c. Check what the backend sees

Start the backend; the log prints either `OCR enabled with tesseract` (or `paddle`), or a warning
that no engine is installed. Or check directly:
```bash
cd backend
uv run python -c "from app.services import ocr; e = ocr.get_engine(); print(e.name if e else 'no OCR engine')"
```

---

## 2. Configure (`backend/.env`)

| Setting | Default | Notes |
|---|---|---|
| `OCR_ENABLED` | `true` | `false` turns OCR off; scans then fail with "OCR isn't available on this server" |
| `OCR_ENGINE` | `tesseract` | Chosen by benchmark ([`ocr_report.md`](ocr_report.md)). `paddle` to use PaddleOCR; `auto` = Tesseract if installed, else PaddleOCR |
| `OCR_PADDLE_MODEL` | `default` | PaddleOCR models: `default` (PP-OCRv6 medium), `mobile` (PP-OCRv5 mobile, faster), `devanagari` |
| `OCR_RETRY_BELOW_CONFIDENCE` | `85` | Tesseract re-reads pages below this confidence with a denoise filter and keeps the better result |
| `OCR_LANGUAGES` | `eng+hin+mar` | Tesseract languages. Each extra language slows OCR; all must be installed |
| `OCR_PADDLE_LANG` | `en` | PaddleOCR uses **one** recognition language: `en`, or `hi` / `mr` for Devanagari documents |
| `OCR_DPI` | `300` | Render resolution. 300 is the usual balance; higher is slower and rarely better |
| `OCR_MAX_PAGES` | `30` | Pages beyond this are skipped and flagged |
| `OCR_MIN_CONFIDENCE` | `60` | Pages below this get an `ocr_low_confidence` flag |
| `OCR_PAGE_TIMEOUT_SECONDS` | `60` | Per-page limit (Tesseract) |

Restart the backend after changing `.env`.

---

## 3. Use it

1. In the app, use **Attach documents** (new case), **Upload PDF or photo** (My documents), or 📎 in chat.
2. Choose a scanned PDF or a photo. The upload returns immediately with status "Reading and extracting facts…".
3. The document list refreshes by itself. When it's done, the card shows "N read by OCR".
4. Open the document: each page header says "read by OCR (NN% confidence)". Low-confidence pages
   are shown in red with "check against the original".
5. **Timeline & flags** lists `ocr_used`, `ocr_low_confidence` and `ocr_page_not_read` items,
   and every source link from an OCR page says "read by OCR, check digits and names".

Via the API:
```bash
curl -F "file=@receipt.jpg;type=image/jpeg" -H "X-User-Id: dev-user" http://localhost:8000/cases/<case_id>/documents
curl -H "X-User-Id: dev-user" http://localhost:8000/cases/<case_id>/documents/<document_id>   # poll until status != processing
```

Tips for users: a flat page, good light, no shadows, the whole page in frame, and 300 dpi when scanning.

---

## 4. Test

```bash
cd backend
uv run python -m pytest tests/test_ocr.py -rs        # unit tests (fake engine) + real Tesseract if installed
RUN_PADDLE_TESTS=1 uv run python -m pytest tests/test_ocr.py -rs   # also real PaddleOCR
uv run python -m pytest                              # everything
```
What the unit tests cover: Tesseract/PaddleOCR output parsing (both PaddleOCR 2.x and 3.x formats),
engine selection, render-size cap for large photos, scanned-page detection (including mixed PDFs),
photo → PDF conversion, OCR filling scanned pages, low-confidence / failed / unreadable / skipped
pages and their flags, and "unreadable scan fails without inventing text". The API tests cover
JPEG/PNG and scanned-PDF uploads end to end.

---

## 5. Benchmark and choose the engine

```bash
cd backend
uv run python -m eval.run_ocr_eval                       # all installed engines, all 3 quality levels
uv run python -m eval.run_ocr_eval --engines tesseract --qualities photo degraded
uv run python -m eval.run_ocr_eval --sets devanagari --engines tesseract paddle-devanagari
```
It prints a table and saves `eval/results/ocr-<timestamp>.json`:

| Column | Meaning | Better |
|---|---|---|
| CER / WER | Character / word error rate against the original text | Lower |
| key values | Share of names, survey numbers and amounts read exactly. **The most important column**: these feed the conflict flags | Higher |
| s/page | Seconds per page on this machine | Lower |
| conf | Mean engine confidence | Context only (engines score differently) |

The script ends with a recommendation: the engine with the lowest CER on the realistic `photo` and
`degraded` levels, unless it is more than 3× slower (then it reports the trade-off).

**Decision procedure:**
1. Install both engines (§1) and run the benchmark.
2. Prefer the engine with the higher **key-value** score on `photo`/`degraded`; use CER as a tie-breaker.
3. Check that s/page is acceptable (a 10-page scan should finish in about 1–2 minutes).
4. Set `OCR_ENGINE` in `.env.example` to the winner and record the table and the reason in
   `docs/evaluation.md` (OCR section). Keep the JSON file in `eval/results/`.
5. Re-run the benchmark after changing engines, versions, `OCR_DPI` or languages.

Engines available to the benchmark: `tesseract`, `paddle-default`, `paddle-mobile`,
`paddle-devanagari`. Datasets: `english` (3 documents) and `devanagari` (a Marathi receipt + a Hindi
agreement extract, rendered with a Devanagari system font; skipped if no such font is installed).

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "OCR isn't available on this server" | No engine installed or `OCR_ENABLED=false`. Install Tesseract (§1a) and restart |
| Log: "Tesseract is missing language packs: hin, mar" | `brew install tesseract-lang` (macOS) or `apt-get install tesseract-ocr-hin tesseract-ocr-mar` |
| `pytesseract.TesseractNotFoundError` | The `tesseract` binary isn't on `PATH` for the backend process; check with `which tesseract` |
| PaddleOCR is slow on the first document | It's downloading and loading models; later documents are faster (the model stays loaded) |
| PaddleOCR import error after an upgrade | The 2.x → 3.x API changed; `ocr.py` handles both result formats. Reinstall with `uv sync --extra paddle` |
| "The scan is too unclear to read" | Every page OCR'd to (almost) nothing. Rescan at 300 dpi or take a sharper photo |
| Many `ocr_low_confidence` flags | Blur, skew or low light; or the wrong language (a Marathi page with `OCR_PADDLE_LANG=en`) |
| Document stuck on "Reading…" after a server restart | Restarted mid-OCR. On startup it's marked failed with "Please upload the document again" (the file isn't stored, so OCR can't resume) |
| Very slow on photos | Phone photos are capped at 3500 px on the long side before OCR; lower `OCR_DPI` for scans if needed |

---

## 7. Limitations (state these honestly)

- Handwriting is not supported; it will usually be flagged as low-confidence or unreadable.
- OCR can misread digits (5↔6, 0↔8) and similar letters; that's why OCR'd items are labelled and
  the cross-document conflict flags matter.
- Stamps, seals and signatures over text cause errors.
- PaddleOCR reads one language per run; mixed English + Devanagari pages favour Tesseract with `eng+hin+mar`.
- The benchmark is small and synthetic (3 documents, 4 pages, English). It compares engines; it
  is not an accuracy claim for real-world documents.

---

## 8. Checklist for a new machine

- [ ] `brew install tesseract tesseract-lang` (or the apt packages)
- [ ] `cd backend && uv sync` (add `--extra paddle` for PaddleOCR)
- [ ] `.env`: OCR settings from `.env.example`
- [ ] Start the backend; the log says "OCR enabled with …"
- [ ] `uv run python -m pytest tests/test_ocr.py -rs`: no failures
- [ ] `uv run python -m eval.run_ocr_eval`: record the results
- [ ] Upload a photo of a receipt in the app; the pages say "read by OCR"

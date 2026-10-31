# OCR for scanned documents: plan

> Status: **implemented**. Engine decision: **Tesseract** (see [`docs/ocr_report.md`](docs/ocr_report.md)). Step-by-step reference: [`docs/ocr_steps.md`](docs/ocr_steps.md).
> Goal: scanned PDFs and phone photos of property documents become page-linked text. Low-quality
> pages are flagged instead of silently trusted, and nothing is ever made up.

## 1. The problem today

`app/services/documents.py` rejects any PDF with fewer than 20 characters of selectable text
(`no_text`: "This looks like a scanned document; OCR is not supported yet"). In practice many of the
documents people actually hold are scans or photos:

- old sale deeds and agreements to sell, usually scanned at a registrar or a photocopy shop;
- receipts and stamp paper photographed on a phone;
- 7/12 extracts and other property records, often in **Marathi or Hindi (Devanagari)**;
- mixed PDFs: a typed agreement with scanned annexures.

So OCR is the biggest coverage gap in the document workflow.

## 2. Library choice

### Options compared

| Option | Indian scripts | Runs on a 16 GB Mac (CPU) | Install size | Privacy | Confidence scores | Verdict |
|---|---|---|---|---|---|---|
| **Tesseract 5** (via `pytesseract` + PyMuPDF rendering) | Yes: `hin`, `mar`, plus others (`ben`, `tam`, `tel`, `guj`, `kan`, …) | Fast, about 1–3 s per page | ~50 MB binary + ~15 MB per language | Fully local | Per-word (`image_to_data`) | ✅ **Chosen** |
| PyMuPDF's built-in OCR (`page.get_textpage_ocr`) | Same as Tesseract (it calls Tesseract) | Same | No new Python package | Local | ❌ No per-word confidence | Partial fallback |
| OCRmyPDF | Tesseract underneath | OK | Needs Ghostscript, unpaper, qpdf | Local | Indirect | Overkill: it produces PDF/A files, but we only need text |
| EasyOCR | Hindi, Marathi | Slow on CPU; PyTorch ~1–2 GB | Large | Local | Yes | Too heavy for a laptop backend |
| PaddleOCR | Devanagari models | Moderate; Paddle framework | Large | Local | Yes | Heavier install, Apple-Silicon support is uneven |
| Surya OCR | Strong multilingual | Slow without a GPU | Large (transformer models) | Local | Yes | Licence restrictions on model weights; needs a GPU to be practical |
| docTR | Mainly Latin scripts | Moderate | PyTorch/TF | Local | Yes | Weak on Devanagari |
| Apple Vision (`ocrmac`) | Limited Devanagari support | Very fast | Small | Local | Yes | macOS only; wouldn't run on a Linux server |
| Google Cloud Vision / Document AI | Excellent | n/a (cloud) | n/a | ❌ Documents leave the machine | Yes | Paid; private documents sent to a third party |
| Gemini multimodal (page image → text) | Very good | n/a (cloud) | n/a | ❌ Free tier may use data | No | **Can "correct" or invent text**, which breaks the never-fabricate rule; also slow on the free tier |

### Decision: support **both Tesseract 5 and PaddleOCR**, and let a benchmark choose the default

Neither engine has been measured on our documents, so instead of guessing we put OCR behind one
small interface and compare the two on the same scans.

```python
class OcrEngine(Protocol):
    name: str
    def available(self) -> bool: ...
    def read(self, image: PIL.Image.Image) -> OcrResult: ...   # text + mean confidence (0-100)
```

| | Tesseract 5 (`pytesseract`) | PaddleOCR (`paddleocr` + `paddlepaddle`) |
|---|---|---|
| Role | **Default to start with**; always installed | **Optional extra** (`uv sync --extra paddle`) |
| Strengths | Light, fast on CPU, mature Hindi/Marathi language packs, word-level confidence, simple install | Usually more accurate on photos, skew, low light, stamps and complex layouts; line-level confidence |
| Weaknesses | Weaker on poor photos and complex layouts | Heavy framework and model downloads; fiddlier on Apple Silicon; API changed between 2.x and 3.x; one recognition language per instance; Devanagari quality unproven |
| Setting | `OCR_ENGINE=tesseract` | `OCR_ENGINE=paddle` (`OCR_PADDLE_LANG=en`, or `hi`/`mr` for Devanagari) |

`OCR_ENGINE=auto` (the default) uses Tesseract when it's installed, otherwise PaddleOCR.

**How the default is chosen (milestone M6):** `eval/run_ocr_eval.py` runs every installed engine on
the same synthetic scans at three quality levels. It measures character error rate (CER), word
error rate (WER), how many key values (survey numbers, amounts, names) survive OCR, seconds per
page, and mean confidence. The engine with the best results on the realistic levels (photo-like and
degraded), within an acceptable time per page, becomes the default, and `docs/evaluation.md` records why.

Both engines run fully locally, so documents never leave the machine.

Install:
```bash
brew install tesseract tesseract-lang        # macOS (tesseract-lang includes hin, mar)
sudo apt-get install tesseract-ocr tesseract-ocr-hin tesseract-ocr-mar   # Debian/Ubuntu or Docker
uv sync                                       # pytesseract is a normal dependency
uv sync --extra paddle                        # optional: PaddleOCR + PaddlePaddle (large download)
```

## 3. Design

### 3.1 Flow

```
upload (PDF, or JPG/PNG photo → converted to a 1-page PDF)
  │
  ├─ per page: selectable text ≥ MIN_PAGE_CHARS ? ──yes──► use it (as today, instant)
  │                                    │no, and the page has images
  │                                    ▼
  │                          mark page "needs OCR"
  ▼
if no page needs OCR → status "processing" → fact extraction (as today)
else                 → status "processing" (stage "ocr") → BACKGROUND:
                          render each page at 300 dpi (PyMuPDF)
                          → preprocess (grayscale, auto-contrast, deskew)
                          → Tesseract eng+hin+mar → text + mean word confidence
                          → page confidence < OCR_MIN_CONFIDENCE → page kept but flagged
                          → all pages unreadable → status "failed" ("image too unclear")
                        → fact extraction on the combined text (as today)
                        → excerpt verification against the OCR text (as today)
```

Key points:
- **OCR is per page, not per document**, so mixed PDFs work (typed agreement + scanned annexure).
- **It always runs in the background**, using the existing `extract_in_background` and the app's
  polling. OCR can take a minute or two for a long scan, so the upload must stay instant.
- **OCR text is never "improved" by an LLM.** What Tesseract read is what gets stored. The fact
  extractor only quotes from it, and excerpt verification checks quotes against it.

### 3.2 Data model

`case_documents` gets one new JSONB column:

```python
page_info: list[dict]  # one per page: {"source": "text" | "ocr", "confidence": float | None}
```

`Base.metadata.create_all` doesn't add columns to an existing table, so `init_db()` will also run
`ALTER TABLE case_documents ADD COLUMN IF NOT EXISTS page_info JSONB DEFAULT '[]'`. This is a
small, safe step; a proper move to Alembic migrations stays on the backlog.

### 3.3 Honesty in the evidence pack and brief

- New flag kind **`ocr_low_confidence`**: "Page 2 of receipt.pdf was read by OCR with low confidence
  (54%). Check amounts, dates and survey numbers against the original."
- New flag kind **`ocr_used`** (informational): which documents/pages were read by OCR.
- Supported facts from OCR pages keep `verified: true` only if the excerpt matches, and are tagged
  **"from OCR"** in the brief, because a matching excerpt proves *where* the text came from, not that
  OCR read the digits correctly.
- The brief's "Documents processed" section shows "scanned (OCR, avg confidence 82%)".

### 3.4 Configuration (`app/config.py`, `.env`)

| Setting | Default | Meaning |
|---|---|---|
| `OCR_ENABLED` | `true` | Turn OCR off entirely; scanned PDFs then fail with a clear message |
| `OCR_ENGINE` | `auto` | `tesseract`, `paddle`, or `auto` (Tesseract if installed, else PaddleOCR) |
| `OCR_LANGUAGES` | `eng+hin+mar` | Tesseract language packs |
| `OCR_PADDLE_LANG` | `en` | PaddleOCR recognition language (`hi` / `mr` for Devanagari documents) |
| `OCR_DPI` | `300` | Render resolution (300 is the usual sweet spot for accuracy vs. speed) |
| `OCR_MAX_PAGES` | `30` | Bigger scans: OCR the first 30 pages and flag the rest |
| `OCR_MIN_CONFIDENCE` | `60` | Pages below this mean word confidence get `ocr_low_confidence` |
| `OCR_PAGE_TIMEOUT_SECONDS` | `60` | Per-page safety limit |

If Tesseract isn't installed, startup logs a clear warning and uploads keep working for text PDFs.

### 3.5 Error messages (shown in the app)

| Situation | Status | Message |
|---|---|---|
| OCR disabled or not installed | `failed` | "This looks like a scanned document. OCR isn't available on this server." |
| Every page unreadable | `failed` | "The scan is too unclear to read. Try a sharper photo or scan (300 dpi, good light)." |
| Some pages unreadable | `processed` + flag | Page-level `ocr_low_confidence` flags |
| Too many pages | `processed` + flag | "Only the first 30 pages were read." |

## 4. Implementation milestones

### M1: OCR service with two engines (backend only)
- **New** `app/services/ocr.py`:
  - the `OcrEngine` interface and `OcrResult` (text, confidence 0–100, engine name);
  - `TesseractEngine` (rebuilds lines from `image_to_data`, word-level confidence);
  - `PaddleEngine` (handles both the PaddleOCR 2.x `ocr()` and 3.x `predict()` result formats);
  - `get_engine()` (from `OCR_ENGINE`), `render_page()` (PyMuPDF → PIL at `OCR_DPI`), `page_needs_ocr()`.
- `pyproject.toml`: `pytesseract` as a dependency; `paddleocr` + `paddlepaddle` as the optional `paddle` extra.
- **Acceptance**: a scanned (image-only) copy of `advance_receipt.pdf` returns text containing
  "123/A" and "5,50,000", with confidence > 60.

### M2: Pipeline integration
- `documents.py`: `extract_pages` returns per-page info; scanned pages are queued for OCR in
  `extract_in_background` (OCR first, then facts); `no_text` is raised only when OCR is disabled,
  not installed, or fails on every page.
- `models.py` + `db.py`: the `page_info` column and the `ADD COLUMN IF NOT EXISTS` step.
- `schemas.py` / `api/documents.py`: expose `page_info` and an `ocr_pages` count.
- **Acceptance**: uploading a scanned PDF → `processing` → `processed` with facts; mixed PDFs OCR only their scanned pages.

### M3: Evidence and brief honesty
- `evidence.py`: the `ocr_low_confidence` and `ocr_used` flags.
- `brief.py`: OCR status per document; facts from OCR pages tagged.
- **Acceptance**: a deliberately blurred scan produces an `ocr_low_confidence` flag naming the page.

### M4: Photo uploads (JPG/PNG)
- `check_upload`: accept JPEG/PNG magic bytes; convert to a 1-page PDF with PyMuPDF; same limits.
- Android: the picker accepts `application/pdf` and `image/*`; add a "Take photo" option later.
- **Acceptance**: a phone photo of a receipt is processed like a scanned PDF.

### M5: Android
- Status text "Reading scanned pages (OCR)…" while processing; an "OCR" badge on the document card
  and on each page in the document view; low-confidence pages highlighted.
- **Acceptance**: you can see which pages were read by OCR and which need checking.

### M6: Tests and evaluation
- **Unit tests** (they run without Tesseract by faking `ocr_page`): page detection, mixed-PDF routing,
  low-confidence flags, the "all pages unreadable" failure, the OCR-disabled path, image-to-PDF conversion.
- **Integration tests** marked `@pytest.mark.skipif(shutil.which("tesseract") is None)`: real OCR
  on the synthetic scans.
- **OCR benchmark** (`eval/run_ocr_eval.py`): render the 3 synthetic sample PDFs to images in
  three quality levels (clean 300 dpi; 150 dpi + slight rotation; blur + noise + JPEG compression)
  and rebuild them as image-only PDFs. Measure:
  - **character error rate (CER)** and **word error rate (WER)** against the original text;
  - field recall through the whole pipeline (do "123/A" and "5,50,000" survive OCR?);
  - excerpt-verified rate;
  - seconds per page;
  - whether low-quality pages are correctly flagged.
- Optional: a synthetic **Marathi/Hindi** sample (needs a Devanagari font such as Noto Sans
  Devanagari, OFL-licensed, to render the test images).
- Record the results in `docs/evaluation.md` (new "OCR" section). This also gives the presentation
  a concrete chart: CER by scan quality.

### M7: Docs
- README: install steps (brew/apt), settings, limitations.
- `ppt_plan.md`: add an OCR slide (pipeline + CER chart) to Act 4 and mention OCR in the demo
  (upload a scanned receipt).
- `plan_claude.md`: progress log.

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| OCR misreads digits (5 ↔ 6, 0 ↔ 8) in amounts or survey numbers | Low-confidence flags; "from OCR" tag; the existing cross-document conflict flags will often catch it; the user is told to check originals |
| Slow on long scans | Background processing, `OCR_MAX_PAGES`, per-page timeout, 300 dpi (not higher) |
| Tesseract missing on a teammate's machine | `OCR_ENABLED` + startup check; clear message; install steps in the README |
| Wrong language pack (e.g. Gujarati record) | `OCR_LANGUAGES` setting; listed as a limitation |
| Handwritten documents | Out of scope; low confidence → flagged or failed, never invented |
| Prompt injection through scanned text | Same as today: document text is wrapped as untrusted data |

## 6. Effort estimate

| Milestone | Effort |
|---|---|
| M1–M3 (backend OCR, honest flags) | ~1 day |
| M4 (photos) | ~0.5 day |
| M5 (Android) | ~0.5 day (needs a machine with the Android SDK to verify) |
| M6 (tests + OCR benchmark) | ~0.5–1 day |
| M7 (docs) | ~1–2 hours |

## 7. Decisions (taken)

1. **Languages**: `eng+hin+mar` for Tesseract; `en` for PaddleOCR (switch to `hi`/`mr` for Devanagari documents).
2. **Photo uploads (M4)**: included.
3. **Engines**: both Tesseract and PaddleOCR, compared by `eval/run_ocr_eval.py`. The benchmark
   chose **Tesseract** as the default ([`docs/ocr_report.md`](docs/ocr_report.md)); PaddleOCR stays optional.

Step-by-step instructions (install, run, test, benchmark, choose, troubleshoot) are in
[`docs/ocr_steps.md`](docs/ocr_steps.md).

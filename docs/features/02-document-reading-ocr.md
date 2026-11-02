# 02 · Document upload and reading (OCR)

## What it does
Users attach agreements, receipts, notices and land records as **PDFs or phone photos (JPG/PNG)**, from
the new-case screen, My documents, or 📎 in chat. Each becomes page-numbered text, typed or OCR'd, that
everything else is built on.

## How it is implemented
1. **Validation:** file type by magic bytes (PDF, JPEG, PNG), 10 MB, 60 pages, and encrypted or damaged
   files rejected with a clear reason. Photos are converted to a one-page PDF.
2. **Per-page text:** PyMuPDF extracts selectable text page by page. A page with almost no text but an
   image on it is treated as a scan. This works per page, so a typed agreement with a scanned annexure
   works.
3. **OCR in the background:** the upload returns immediately ("Reading…"). A background task renders
   each scanned page at 300 dpi (photos capped at 3,500 px), and Tesseract reads it with `eng+hin`.
4. **Adaptive denoising:** if a page's confidence is below 85, it's read again after a 3×3 median filter,
   and the higher-confidence result is kept.
5. **Honesty:**
   - OCR text is stored exactly as read and never "corrected" by an LLM;
   - each page records its source (`text` / `ocr`), engine and confidence;
   - low-confidence pages, unreadable pages and pages over the limit are flagged;
   - every value from an OCR'd page is labelled "read by OCR, check digits and names".
6. **Privacy:** the original file is never stored; the PDF bytes stay in memory only until OCR finishes.

## Why Tesseract, not the alternatives
We put both engines behind one interface and **benchmarked them on the same scans** (details:
[`../ocr_report.md`](../ocr_report.md)).

| Criterion | Tesseract | PaddleOCR (default model) | PaddleOCR (Devanagari model) |
|---|---|---|---|
| Hindi key values, clean / photo scans | **100% / 100%** | can't read Devanagari | 70% (clean) |
| English key values, clean / photo | 79% / 79% | 79% / 79% | n/a |
| English, degraded scans | 50% (with denoise retry) | **57%** | n/a |
| Speed | **0.5–2 s/page** | ~26 s/page | ~78 s/page |
| Peak memory | **~0.1 GB** | ~15 GB | not measured |
| English + Hindi on one page | ✅ one pass | ❌ one language per model | ❌ |

Other options ruled out: EasyOCR, Surya and docTR (heavy or weak on Devanagari); cloud OCR (private
documents would leave the machine); Gemini vision (it can "correct" or invent text, which breaks the
never-fabricate rule).

## Results (200-case scorecard, Tesseract on 40 cases)
| Scan quality | Key values precision / recall / F1 | Party names recall |
|---|---|---|
| clean | 99.1% / 97.6% / **98.3%** | 98.7% |
| phone photo | 97.3% / 95.0% / **96.1%** | 95.3% |
| degraded | 74.2% / 30.9% / 43.7% | 44.4% |

- The denoise retry raised degraded-scan key values from 36% to 50% (English) and from 20% to 50%
  (Hindi), with no change on clean or photo scans.
- Black-and-white thresholding was tested and rejected: it gave a lower character error rate but
  destroyed commas and digits (0% key values).
- The "Iyer" → "lyer" error seen with every engine turned out to be a font effect: in sans-serif fonts,
  capital I and lowercase l look alike.

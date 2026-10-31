# OCR engine comparison: Tesseract vs PaddleOCR

**Decision: Tesseract 5 is the default OCR engine** (`OCR_ENGINE=tesseract`). PaddleOCR stays as an
optional extra for experiments. This report shows the measurements behind that decision.

Date: 2026-10-31 · Machine: Apple Silicon MacBook, 16 GB RAM, CPU only · Benchmark: `backend/eval/run_ocr_eval.py` (v1)

---

## 1. Why we needed to choose

Many property documents people hold are scans or phone photos (old sale deeds, receipts, 7/12
extracts), often in **Marathi or Hindi**. The OCR engine has to:

1. read **names, survey numbers, amounts and dates exactly**, because these feed the conflict flags
   (for example "survey no. 123/4 vs 123/A" or "₹5,00,000 vs ₹5,50,000");
2. read **English and Devanagari** (Hindi, Marathi), including Devanagari numerals (१२३/४);
3. run **locally** on a 16 GB laptop, because property documents are private;
4. be **fast enough** that a multi-page scan finishes while the user waits (target: a 10-page scan in about a minute).

## 2. What we compared

| Setup | Version / models | Languages |
|---|---|---|
| **Tesseract** | Tesseract 5.5.4 via `pytesseract` | `eng+hin+mar` in one pass |
| **PaddleOCR default** | PaddleOCR 3.7.0, PaddlePaddle 3.3.1, PP-OCRv6 *medium* det + rec | `en` |
| **PaddleOCR mobile** | PP-OCRv5 *mobile* det + rec (lighter) | Chinese/English model |
| **PaddleOCR Devanagari** | PP-OCRv5 server det + `devanagari_PP-OCRv5_mobile_rec` | `mr` (Devanagari) |

All four run locally on CPU. Other options (EasyOCR, Surya, docTR, cloud APIs, Gemini vision) were
ruled out earlier for size, privacy or the risk of an LLM "correcting" text. See `ocr_plan.md` §2.

## 3. Method

- **Documents** (all synthetic, with fictional people and places):
  - *English set*: the 3 benchmark documents from `eval/samples.py` (agreement to sell, receipt,
    legal notice), 4 pages in total.
  - *Devanagari set*: a Marathi receipt with Devanagari numerals and a Hindi agreement extract with
    ASCII numerals, 2 pages. They're rendered with correct conjunct shaping (PyMuPDF `Story` + a
    Devanagari system font).
- **Scan quality levels** (`eval/scans.py`): each text PDF is turned into an image-only PDF:
  - **clean**: 300 dpi flatbed scan;
  - **photo**: 150 dpi, 1.5° rotation, slight blur, JPEG quality 70 (a careful phone photo);
  - **degraded**: 120 dpi, 3° rotation, more blur, speckle noise, JPEG quality 40 (a poor photocopy).
- **Metrics:**
  - **Key values**: share of the names, survey numbers, amounts and dates read *exactly*. This is
    **the primary metric**, because these values drive the app's conflict flags.
  - **CER / WER**: character / word error rate against the original text (lower is better).
  - **s/page**: seconds per page, with the model already loaded.
  - **conf**: the engine's own mean confidence (engines score differently, so for context only).
  - **Peak memory**: peak resident memory of the process for one page.

Raw results: `backend/eval/results/ocr-20261031-144556.json` (first PaddleOCR run),
`ocr-20261031-english-console.txt` and `ocr-20261031-devanagari-console.txt` (four-engine runs; the
run was interrupted before its JSON was written, so the console output is the record),
`ocr-20261031-162305.json` (final Tesseract run with the denoise retry, §5).

## 4. Results

### 4.1 English documents (4 pages)

| Engine | Quality | Key values | CER | WER | s/page | conf |
|---|---|---|---|---|---|---|
| **Tesseract** | clean | **79%** | **0.2%** | **1.5%** | **0.5** | 95 |
| PaddleOCR default | clean | 79% | 0.3% | 2.3% | 27.3 | 100 |
| PaddleOCR mobile | clean | 86% | 0.3% | 2.4% | 7.1 | 97 |
| **Tesseract** | photo | **79%** | **0.3%** | **2.0%** | **0.6** | 95 |
| PaddleOCR default | photo | 79% | 2.3% | 4.4% | 26.5 | 99 |
| PaddleOCR mobile | photo | 79% | 3.0% | 12.1% | 6.5 | 96 |
| Tesseract (before denoise retry) | degraded | 36% | 41.9% | 60.8% | 0.8 | 65 |
| **Tesseract (with denoise retry, §5)** | degraded | **50%** | 30.9% | 49.4% | 2.0 | 70 |
| PaddleOCR default | degraded | **57%** | **5.2%** | **11.8%** | 25.9 | 84 |
| PaddleOCR mobile | degraded | 36% | 7.4% | 32.0% | 6.1 | 91 |

### 4.2 Devanagari documents: Marathi + Hindi (2 pages)

| Engine | Quality | Key values | CER | WER | s/page | conf |
|---|---|---|---|---|---|---|
| **Tesseract** (`eng+hin+mar`) | clean | **100%** | **1.2%** | **6.1%** | **0.7** | 93 |
| PaddleOCR Devanagari | clean | 70% | 2.6% | 12.4% | 78.5 | 97 |
| PaddleOCR default (`en`) | clean | 30% | 85.7% | 97.3% | 24.7 | 66 |
| PaddleOCR mobile | clean | 0% | 93.8% | 100% | 5.4 | 52 |
| **Tesseract** | photo | **100%** | **1.4%** | **3.8%** | **0.7** | 93 |
| PaddleOCR default (`en`) | photo | 30% | 91.2% | 100% | 22.6 | 69 |
| PaddleOCR mobile | photo | 30% | 91.8% | 100% | 5.1 | 54 |
| Tesseract (before denoise retry) | degraded | 20% | 44.8% | 68.1% | 0.5 | 65 |
| **Tesseract (with denoise retry)** | degraded | **50%** | **23.8%** | **41.9%** | 1.3 | 76 |
| PaddleOCR default (`en`) | degraded | 30% | 90.2% | 100% | 22.8 | 64 |
| PaddleOCR mobile | degraded | 0% | 96.3% | 100% | 5.0 | 58 |
| PaddleOCR Devanagari | photo, degraded | *not measured: the run was stopped after the clean level (78.5 s/page)* | | | | |

PaddleOCR's `en` and mobile models can't read Devanagari at all. Their 30% comes only from the
ASCII-numeral values (`123/4`, `45,00,000`) in the Hindi document.

### 4.3 Resources

| Engine | Peak memory (one page) | Install size | First-run download |
|---|---|---|---|
| **Tesseract** | **~92 MB** (tesseract process) + ~260 MB Python host | ~50 MB + language packs (`brew install tesseract tesseract-lang`) | none |
| PaddleOCR mobile | ~4.3 GB | PaddlePaddle + PaddleOCR (the project `.venv` grew to ~1.2 GB) | models, ~1 min |
| PaddleOCR default | **~15 GB** (on a 16 GB machine) | same | models, ~1 min |

Peak memory is the process's maximum resident set size (`ru_maxrss`), measured once per engine in a
fresh process. It may include allocator caches, but it is what the laptop actually has to provide.

### 4.4 Errors seen (representative)

| Error | Engines | Cause | What we did |
|---|---|---|---|
| "Meera **Iyer**" → "Meera **lyer**" | **all engines**, every quality level | In sans-serif fonts (Helvetica, Arial) capital I and lowercase l are nearly identical. The same text in a serif font (Times) was read correctly by Tesseract | Documented. Party names aren't used for conflict flags; OCR'd items carry a "check names" label |
| "Rs. 5,**50**,000" → "Rs. 5**.**50,000" | PaddleOCR (degraded) | Comma read as a dot | `parse_amount` treats a dot followed by digits and a comma as a grouping comma (tested), avoiding a false ₹5.5 amount conflict |
| "Kulka**rn**i" → "Kulka**m**i" | PaddleOCR, Tesseract (degraded) | `rn` merges into `m` | Documented; OCR'd items are labelled for checking |
| Speckle noise → junk characters, broken digits | Tesseract (degraded) | No denoising | Adaptive median-filter retry (§5) |
| Confidence 77% while the amount was wrong | PaddleOCR (degraded) | Confidence measures recognition certainty, not correctness | The "read by OCR, check digits" label on **every** OCR'd item, not just low-confidence pages |

## 5. Improvement made because of the benchmark: adaptive denoising for Tesseract

Tesseract's weak spot was degraded scans. We tested four preprocessing options on the photo and
degraded levels (scratch experiment; results below):

| Preprocessing | English degraded: key values / CER | Devanagari degraded: key values / CER | Effect on photo-quality scans |
|---|---|---|---|
| none (grayscale + autocontrast) | 36% / 41.9% | 20% / 44.8% | — |
| **3×3 median filter** | **57%** / 28.4% | **50%** / 23.8% | key values unchanged, CER +0.1–0.8 pts |
| 3×3 median + black/white threshold | **0%** / 18.7% | 20% / 20.6% | — |
| 5×5 median filter | 21% / 23.4% | 50% / 19.6% | — |

**Lesson:** thresholding gives the lowest CER but destroys commas and thin digit strokes, so
key-value accuracy collapses. CER alone would have picked the wrong option. This is why key values
are the primary metric.

**Implemented** (`TesseractEngine.read`): run normally; if the page's confidence is below
`OCR_RETRY_BELOW_CONFIDENCE` (85), run again with a 3×3 median filter and keep the higher-confidence
result. Clean and photo pages (confidence ~93–95) pay nothing extra; degraded pages take one extra
pass (~1 s). Final measured effect: degraded key values went from 36% to 50% (English) and from
20% to 50% (Devanagari), with clean/photo unchanged.

## 6. Comparison summary

| Criterion | Tesseract | PaddleOCR default | PaddleOCR mobile | PaddleOCR Devanagari |
|---|---|---|---|---|
| English, clean/photo | ✅ best or equal | ✅ equal | ✅ equal or better on clean | n/a |
| English, degraded | ⚠️ 50% key values | ✅ **57%**, best | ❌ 36% | n/a |
| Marathi/Hindi | ✅ **100%** clean/photo | ❌ can't read Devanagari | ❌ can't read Devanagari | ⚠️ 70% on clean |
| Mixed English + Devanagari on one page | ✅ one pass (`eng+hin+mar`) | ❌ one language per model | ❌ | ❌ Devanagari only |
| Speed (s/page) | ✅ **0.5–2** | ❌ ~26 | ⚠️ ~6 | ❌ ~78 |
| Peak memory | ✅ **~0.1 GB** | ❌ **~15 GB** | ❌ ~4.3 GB | not measured |
| Install | ✅ `brew install`, small | ❌ large framework + model downloads | ❌ same | ❌ same |
| Confidence scores | ✅ per word | per line | per line | per line |

## 7. Conclusion

**Tesseract is the right default for NyayaSathi.**

1. **It reads the documents our users actually have.** It got 100% of key values on clean and
   photo-quality Marathi and Hindi scans, including Devanagari numerals, in a single pass that also
   reads English. PaddleOCR needs a different model per language, and its Devanagari model was
   both less accurate (70%) and about 100× slower.
2. **It is about 40× faster** (0.5–2 s per page against ~26 s). A 10-page scan takes seconds, not minutes.
3. **It fits a 16 GB laptop comfortably** (~0.1 GB against up to ~15 GB for PaddleOCR's default model,
   which would make the backend unusable on the target machine).
4. **On clean and photo-quality scans it is as accurate as PaddleOCR or better** (CER 0.2–0.3% on English).
5. **Its one weakness, degraded scans, is reduced** by the adaptive denoise retry (key values 36% → 50%
   English, 20% → 50% Devanagari). PaddleOCR default is still better on degraded English (57%), but
   not by enough to justify the speed and memory cost or the loss of Devanagari support.

**Where PaddleOCR would be worth revisiting:** a GPU server processing mostly English, poor-quality
scans in bulk. It stays available (`uv sync --extra paddle`, `OCR_ENGINE=paddle`) and the same
benchmark can re-check that case.

**Honest limits of this study:**
- The benchmark is small (6 pages, 2 scripts) and synthetic: computer-generated scans with simulated
  degradation, not real photographed documents. It compares engines; it is not an accuracy claim for
  real-world documents.
- PaddleOCR's Devanagari model was measured only on clean scans (the run was stopped).
- Handwriting, stamps over text and real camera artefacts (shadows, curved pages) were not tested.
- All engines struggle with I/l in sans-serif fonts and with digits on poor scans. That is why every
  OCR'd item in the app is labelled "read by OCR, check digits and names", and why the
  cross-document conflict flags matter.

## 8. Recommended next steps

1. **Real-document check:** run the pipeline on 5–10 real (permissioned) photographed documents and
   compare key values by hand.
2. **Detect garbled text layers:** some Indian PDFs have a Devanagari text layer that extracts as
   garbled characters. We saw this when generating the Marathi samples. Pages whose text is mostly
   unexpected Latin-extended characters should be sent to OCR instead of being trusted as typed text.
3. **Deskew** before OCR for rotated photos (Tesseract's orientation detection or a Hough-line deskew),
   then re-run this benchmark.
4. Finish the PaddleOCR Devanagari photo/degraded levels if PaddleOCR is ever reconsidered.

## 9. How to reproduce

```bash
brew install tesseract tesseract-lang
cd backend && uv sync --extra paddle
uv run python -m eval.run_ocr_eval                                   # all engines, both sets (slow: PaddleOCR)
uv run python -m eval.run_ocr_eval --engines tesseract               # Tesseract only (under a minute)
uv run python -m eval.run_ocr_eval --sets devanagari --engines tesseract paddle-devanagari
```
Full setup and troubleshooting: [`docs/ocr_steps.md`](ocr_steps.md).

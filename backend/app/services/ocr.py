"""OCR for scanned pages and photos, with two interchangeable engines: Tesseract and PaddleOCR.

Both run locally, so documents never leave the machine. OCR text is stored exactly as the engine read
it: never "improved" by an LLM. A confidence score (0-100) is kept per page, so low-quality pages are
flagged in the evidence pack instead of being silently trusted.

    OCR_ENGINE=tesseract  brew install tesseract tesseract-lang   (OCR_LANGUAGES=eng+hin)  (default)
    OCR_ENGINE=auto       Tesseract if installed, else PaddleOCR
    OCR_ENGINE=paddle     uv sync --extra paddle                  (OCR_PADDLE_LANG=en | hi)

eval/run_ocr_eval.py compares the installed engines on the same synthetic scans; docs/ocr_report.md
explains why Tesseract is the default.
"""

import logging
import statistics
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import pymupdf
from PIL import Image, ImageFilter, ImageOps

from app.config import get_settings

log = logging.getLogger("uvicorn.error")

MIN_PAGE_CHARS = 25  # a page with less selectable text than this is treated as a scan if it has an image


@dataclass
class OcrResult:
    text: str
    confidence: float | None  # mean recognition confidence, 0-100
    engine: str


class OcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def read(self, image: Image.Image) -> OcrResult: ...


# ---------- Tesseract ----------


def tesseract_text(data: dict) -> tuple[str, float | None]:
    """Rebuild lines and paragraphs from pytesseract.image_to_data output, with mean word confidence."""
    lines: dict[tuple, list[str]] = {}
    confidences = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        conf = float(data["conf"][i])
        if not word or conf < 0:  # -1 marks layout boxes, not words
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        confidences.append(conf)
    out, previous = [], None
    for key in sorted(lines):
        if previous is not None and key[:2] != previous[:2]:
            out.append("")  # blank line between paragraphs
        out.append(" ".join(lines[key]))
        previous = key
    return "\n".join(out), (statistics.fmean(confidences) if confidences else None)


class TesseractEngine:
    name = "tesseract"

    def available(self) -> bool:
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            missing = set(get_settings().ocr_languages.split("+")) - set(pytesseract.get_languages())
        except Exception:
            return False
        if missing:
            log.warning("Tesseract is missing language packs: %s (brew install tesseract-lang)", ", ".join(sorted(missing)))
            return False
        return True

    def read(self, image: Image.Image) -> OcrResult:
        import pytesseract

        s = get_settings()

        def run(img: Image.Image) -> tuple[str, float | None]:
            data = pytesseract.image_to_data(
                img, lang=s.ocr_languages, output_type=pytesseract.Output.DICT, timeout=s.ocr_page_timeout_seconds
            )
            return tesseract_text(data)

        gray = ImageOps.grayscale(image)
        text, confidence = run(ImageOps.autocontrast(gray))
        # Noisy scans: a 3x3 median filter removes speckle. In the OCR benchmark it roughly doubled
        # key values read exactly on degraded scans (English 36% -> 57%, Devanagari 20% -> 50%) but
        # slightly hurt clean ones, so it is only tried on low-confidence pages, keeping the better
        # result. (Black/white thresholding was tested too: lower CER but it broke digits and commas.)
        if confidence is not None and confidence < s.ocr_retry_below_confidence:
            text2, confidence2 = run(ImageOps.autocontrast(gray.filter(ImageFilter.MedianFilter(3))))
            if confidence2 is not None and confidence2 > confidence:
                text, confidence = text2, confidence2
        return OcrResult(text, confidence, self.name)


# ---------- PaddleOCR ----------


def paddle_lines(result) -> list[tuple[str, float]]:
    """(text, score 0-1) pairs from PaddleOCR output, for both the 3.x `predict()` and 2.x `ocr()` formats."""
    lines = []
    for page in result or []:
        if page is None:
            continue
        if hasattr(page, "get") and "rec_texts" in page:  # 3.x: one result object per image
            lines += list(zip(page["rec_texts"], page["rec_scores"]))
            continue
        for item in page:  # 2.x: [[box, (text, score)], ...]
            if item and len(item) == 2 and isinstance(item[1], (list, tuple)):
                lines.append((item[1][0], float(item[1][1])))
    return [(t, float(c)) for t, c in lines if t and t.strip()]


# OCR_PADDLE_MODEL=mobile: PaddleOCR's lighter models (there is no PP-OCRv6 mobile model in 3.7).
PADDLE_MOBILE_MODELS = {"text_detection_model_name": "PP-OCRv5_mobile_det", "text_recognition_model_name": "PP-OCRv5_mobile_rec"}


@lru_cache
def _paddle_model(lang: str, variant: str):
    from paddleocr import PaddleOCR

    models = PADDLE_MOBILE_MODELS if variant == "mobile" else {}
    if variant == "devanagari":  # PaddleOCR maps hi to its Devanagari recognition model
        lang = "hi"
    try:  # 3.x: skip the document-unwarping models we don't need (much faster)
        return PaddleOCR(
            lang=None if models else lang, **models,
            use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
        )
    except (TypeError, ValueError):  # 2.x
        return PaddleOCR(lang=lang, use_angle_cls=True, show_log=False)


class PaddleEngine:
    """`variant` None follows OCR_PADDLE_MODEL; "default" or "mobile" fixes it (used by the benchmark)."""

    def __init__(self, variant: str | None = None):
        self.variant = variant
        self.name = "paddle" if variant is None else f"paddle-{variant}"

    def _variant(self) -> str:
        return self.variant or get_settings().ocr_paddle_model

    def available(self) -> bool:
        try:
            import paddleocr  # noqa: F401
        except Exception:
            return False
        return True

    def read(self, image: Image.Image) -> OcrResult:
        import numpy as np

        model = _paddle_model(get_settings().ocr_paddle_lang, self._variant())
        array = np.array(image.convert("RGB"))
        result = model.predict(array) if hasattr(model, "predict") else model.ocr(array, cls=True)
        lines = paddle_lines(result)
        text = "\n".join(t for t, _ in lines)
        confidence = statistics.fmean(c for _, c in lines) * 100 if lines else None
        return OcrResult(text, confidence, self.name)


# ---------- Selection and helpers ----------

ENGINES: dict[str, OcrEngine] = {"tesseract": TesseractEngine(), "paddle": PaddleEngine()}
# Fixed variants for the benchmark, so it can compare them side by side.
BENCHMARK_ENGINES: dict[str, OcrEngine] = {
    "tesseract": ENGINES["tesseract"],
    "paddle-default": PaddleEngine("default"),
    "paddle-mobile": PaddleEngine("mobile"),
    "paddle-devanagari": PaddleEngine("devanagari"),
}


@lru_cache
def _available(name: str) -> bool:
    return ENGINES[name].available()


def get_engine() -> OcrEngine | None:
    """The configured engine if OCR is enabled and the engine is installed, else None."""
    s = get_settings()
    if not s.ocr_enabled:
        return None
    names = ["tesseract", "paddle"] if s.ocr_engine == "auto" else [s.ocr_engine]
    for name in names:
        if name in ENGINES and _available(name):
            return ENGINES[name]
    return None


def log_status() -> None:
    engine = get_engine()
    if engine:
        log.info("OCR enabled with %s", engine.name)
    elif get_settings().ocr_enabled:
        log.warning("OCR is enabled but no engine is installed; scanned documents will be rejected. See docs/ocr_steps.md")


def page_needs_ocr(page: pymupdf.Page, text: str) -> bool:
    """Almost no selectable text, but an image on the page: a scan or a photo."""
    return len(text.strip()) < MIN_PAGE_CHARS and bool(page.get_images())


MAX_RENDER_PX = 3500  # longest side; a phone photo becomes a huge "page", so cap the render size


def render_page(page: pymupdf.Page, dpi: int | None = None) -> Image.Image:
    scale = (dpi or get_settings().ocr_dpi) / 72
    longest = max(page.rect.width, page.rect.height) * scale
    if longest > MAX_RENDER_PX:
        scale *= MAX_RENDER_PX / longest
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

"""Synthetic scans of the sample documents (eval/samples.py), for OCR tests and the OCR benchmark.

Each text PDF is rendered to images and rebuilt as an image-only PDF, so it behaves exactly like a
scan: no selectable text. Three quality levels approximate what users actually upload:
- clean:    300 dpi flatbed scan
- photo:    150 dpi, rotated 1.5 degrees, slight blur, JPEG compression (a careful phone photo)
- degraded: 120 dpi, rotated 3 degrees, more blur, noise, strong JPEG compression (a poor photocopy)
"""

import io
import random

import pymupdf
from PIL import Image, ImageFilter

from eval.samples import make_pdf

QUALITIES = {
    "clean": {"dpi": 300, "rotate": 0.0, "blur": 0.0, "noise": 0, "jpeg": 95},
    "photo": {"dpi": 150, "rotate": 1.5, "blur": 0.6, "noise": 8, "jpeg": 70},
    "degraded": {"dpi": 120, "rotate": 3.0, "blur": 1.1, "noise": 20, "jpeg": 40},
}


def degrade(image: Image.Image, quality: str, seed: int = 0) -> Image.Image:
    q = QUALITIES[quality]
    img = image.convert("L")
    if q["rotate"]:
        img = img.rotate(q["rotate"], expand=True, fillcolor=255)
    if q["blur"]:
        img = img.filter(ImageFilter.GaussianBlur(q["blur"]))
    if q["noise"]:
        rng = random.Random(seed)
        pixels = img.load()
        for _ in range(img.width * img.height // 25):  # speckle on ~4% of pixels
            x, y = rng.randrange(img.width), rng.randrange(img.height)
            pixels[x, y] = max(0, min(255, pixels[x, y] + rng.randint(-q["noise"] * 4, q["noise"] * 4)))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=q["jpeg"])
    return Image.open(io.BytesIO(buffer.getvalue()))


def image_only_pdf(images: list[Image.Image]) -> bytes:
    out = pymupdf.open()
    for img in images:
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=95)
        page = out.new_page(width=595, height=842)  # A4 in points
        page.insert_image(page.rect, stream=buffer.getvalue())
    data = out.tobytes()
    out.close()
    return data


def make_scanned_pdf(pages: list[str], quality: str = "clean", seed: int = 0) -> bytes:
    """An image-only PDF of the given page texts at one of the QUALITIES levels."""
    source = pymupdf.open(stream=make_pdf(pages), filetype="pdf")
    images = []
    for n, page in enumerate(source):
        pix = page.get_pixmap(dpi=QUALITIES[quality]["dpi"], alpha=False)
        clean = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        images.append(degrade(clean, quality, seed + n))
    source.close()
    return image_only_pdf(images)


def make_photo(text: str, fmt: str = "JPEG") -> bytes:
    """A single photo-like image (JPEG or PNG bytes) of one page of text."""
    source = pymupdf.open(stream=make_pdf([text]), filetype="pdf")
    pix = source[0].get_pixmap(dpi=150, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    source.close()
    buffer = io.BytesIO()
    img.save(buffer, format=fmt)
    return buffer.getvalue()


# ---------- Devanagari (Marathi / Hindi) samples ----------
# PyMuPDF's Story layout engine shapes Devanagari correctly (conjuncts such as श्र, क्ष), unlike
# Pillow without libraqm. It needs a Devanagari font on the machine; macOS ships these.

DEVANAGARI_FONTS = [
    "/System/Library/Fonts/Supplemental/ITFDevanagari.ttc",
    "/System/Library/Fonts/Kohinoor.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansDevanagari-Regular.ttf",
]

DEVANAGARI_SAMPLES = {
    # Marathi receipt with Devanagari numerals, as on many Maharashtra documents.
    "pavati_marathi.pdf": [
        "कृत्रिम नमुना दस्तऐवज - काल्पनिक, केवळ चाचणीसाठी\n\n"
        "पावती\n\n"
        "दिनांक: १५/०३/२०२३\n\n"
        "श्रीमती मीरा अय्यर यांच्याकडून मौजे वडगाव, तालुका हवेली, जिल्हा पुणे येथील सर्वे क्रमांक "
        "१२३/४ या भूखंडाच्या विक्रीपोटी अग्रिम रक्कम रुपये ५,००,००० (अक्षरी रुपये पाच लाख फक्त) "
        "धनादेश क्रमांक ००४५१२ द्वारे मिळाली.\n\n"
        "रक्कम स्वीकारणार: रवी कुलकर्णी"
    ],
    # Hindi agreement extract with ASCII numerals.
    "anubandh_hindi.pdf": [
        "कृत्रिम नमूना दस्तावेज - काल्पनिक, केवल परीक्षण के लिए\n\n"
        "विक्रय अनुबंध\n\n"
        "यह अनुबंध दिनांक 15 मार्च 2023 को पुणे में रवि कुलकर्णी (विक्रेता) और मीरा अय्यर (क्रेता) के बीच किया गया।\n\n"
        "विक्रेता सर्वे नंबर 123/4, ग्राम वडगाँव की 2000 वर्ग फुट भूमि का स्वामी है।\n\n"
        "कुल विक्रय मूल्य रुपये 45,00,000 है। क्रेता ने रुपये 5,00,000 अग्रिम राशि के रूप में दिए हैं।"
    ],
}

DEVANAGARI_KEY_VALUES = {
    "pavati_marathi.pdf": ["मीरा अय्यर", "रवी कुलकर्णी", "१२३/४", "५,००,०००", "१५/०३/२०२३"],
    "anubandh_hindi.pdf": ["रवि कुलकर्णी", "मीरा अय्यर", "123/4", "45,00,000", "5,00,000"],
}


def devanagari_font() -> str | None:
    import os

    return next((f for f in DEVANAGARI_FONTS if os.path.exists(f)), None)


def make_devanagari_pdf(pages: list[str]) -> bytes:
    """A text PDF of Devanagari pages (correctly shaped). Raises RuntimeError if no font is installed."""
    import html
    import os

    font = devanagari_font()
    if font is None:
        raise RuntimeError("No Devanagari font found; install Noto Sans Devanagari")
    css = f"@font-face {{font-family: dev; src: url({os.path.basename(font)});}} p {{font-family: dev; font-size: 12pt;}}"
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    for text in pages:
        body = "".join(f"<p>{html.escape(p)}</p>" for p in text.split("\n\n"))
        story = pymupdf.Story(html=body, user_css=css, archive=pymupdf.Archive(os.path.dirname(font)))
        more = True
        while more:
            device = writer.begin_page(pymupdf.paper_rect("a4"))
            more, _ = story.place(pymupdf.Rect(50, 50, 545, 800))
            story.draw(device)
            writer.end_page()
    writer.close()
    return buffer.getvalue()


def scan_pdf(source_pdf: bytes, quality: str = "clean", seed: int = 0) -> bytes:
    """Image-only copy of any text PDF at one of the QUALITIES levels."""
    source = pymupdf.open(stream=source_pdf, filetype="pdf")
    images = []
    for n, page in enumerate(source):
        pix = page.get_pixmap(dpi=QUALITIES[quality]["dpi"], alpha=False)
        images.append(degrade(Image.frombytes("RGB", (pix.width, pix.height), pix.samples), quality, seed + n))
    source.close()
    return image_only_pdf(images)

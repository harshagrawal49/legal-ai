"""PDF -> numbered paragraphs."""

import re

import pymupdf

PARA_START = re.compile(r"^\s*(\d{1,3})\.\s+\S")
FALLBACK_CHUNK_CHARS = 1500


def pdf_to_text(pdf_bytes: bytes) -> str:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_paragraphs(text: str) -> list[tuple[int, str]]:
    """Split judgment text into (para_no, text).

    Indian judgments usually number their paragraphs "1.", "2.", ... at the start of a line; we follow
    that numbering (so ¶N matches the judgment) and put any header text before ¶1 into ¶0. If the
    numbering can't be found, fall back to fixed-size chunks numbered 1..n.
    """
    paras: list[tuple[int, list[str]]] = [(0, [])]
    expected = 1
    for line in text.splitlines():
        m = PARA_START.match(line)
        if m and int(m.group(1)) == expected:
            paras.append((expected, [line]))
            expected += 1
        else:
            paras[-1][1].append(line)

    result = [(n, _clean(" ".join(lines))) for n, lines in paras]
    result = [(n, t) for n, t in result if t]
    if expected > 5:  # found a real numbering sequence
        return result
    return _chunk(text)


def _chunk(text: str) -> list[tuple[int, str]]:
    chunks, current = [], ""
    for block in re.split(r"\n\s*\n", text):
        block = _clean(block)
        if current and len(current) + len(block) > FALLBACK_CHUNK_CHARS:
            chunks.append(current)
            current = ""
        current = f"{current} {block}".strip()
    if current:
        chunks.append(current)
    return list(enumerate(chunks, start=1))

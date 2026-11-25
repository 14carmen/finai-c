"""PDF / image -> PNG pages, and OCR (Tesseract)."""
import base64
import io
import json
import shutil
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from .db import DATA_DIR

DOCS_DIR = DATA_DIR / "documents"
DOCS_DIR.mkdir(exist_ok=True)


def doc_dir(doc_id: int) -> Path:
    return DOCS_DIR / str(doc_id)


def page_path(doc_id: int, page: int, dpi: int, max_side: int) -> Path:
    return doc_dir(doc_id) / f"page_{page}_{dpi}dpi_{max_side}px.png"


def store_upload(doc_id: int, filename: str, data: bytes) -> dict:
    """Stores the original file. Returns the page count and whether the PDF has a text layer."""
    d = doc_dir(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    (d / f"original{ext}").write_bytes(data)
    if ext == ".pdf":
        with fitz.open(stream=data, filetype="pdf") as pdf:
            text = "".join(p.get_text() for p in pdf)
            return {"pages": pdf.page_count, "has_text": int(len(text.strip()) > 50), "kind": "pdf"}
    Image.open(io.BytesIO(data)).verify()
    return {"pages": 1, "has_text": 0, "kind": "image"}


def original(doc_id: int) -> Path:
    return next(doc_dir(doc_id).glob("original.*"))


def render_pages(doc_id: int, dpi: int = 150, max_side: int = 1024) -> list[Path]:
    """PDF -> one PNG per page (cached on disk). The longest side is capped so that small models
    do not receive an excessive number of visual tokens."""
    src = original(doc_id)
    out = []
    if src.suffix.lower() == ".pdf":
        with fitz.open(src) as pdf:
            for i, page in enumerate(pdf, start=1):
                p = page_path(doc_id, i, dpi, max_side)
                if not p.exists():
                    pix = page.get_pixmap(dpi=dpi)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    img.thumbnail((max_side, max_side))
                    img.save(p)
                out.append(p)
    else:
        p = page_path(doc_id, 1, dpi, max_side)
        if not p.exists():
            img = Image.open(src).convert("RGB")
            img.thumbnail((max_side, max_side))
            img.save(p)
        out.append(p)
    return out


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def _lang():
    import pytesseract
    return "ron+eng" if "ron" in pytesseract.get_languages(config="") else "eng"


def ocr_pages(doc_id: int, dpi: int = 300) -> list[str]:
    """Plain-text OCR with Tesseract (local), one string per page. Uses Romanian if installed,
    otherwise English. Cached on disk."""
    import pytesseract

    if not tesseract_available():
        raise RuntimeError("Tesseract is not installed (see README).")
    cache = doc_dir(doc_id) / f"ocr_{dpi}dpi.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8").split("\f")
    lang = _lang()
    pages = [pytesseract.image_to_string(preprocess_for_ocr(Image.open(p)), lang=lang, config="--psm 6")
             for p in render_pages(doc_id, dpi=dpi, max_side=4000)]
    cache.write_text("\f".join(pages), encoding="utf-8")
    return pages


def ocr_words(doc_id: int, dpi: int = 300) -> list[dict]:
    """OCR WITH POSITIONS: for each page, a list of text lines, each line = words with x/y.
    Positions tell us which column (start / end of period) every amount belongs to."""
    import pytesseract

    if not tesseract_available():
        raise RuntimeError("Tesseract is not installed (see README).")
    cache = doc_dir(doc_id) / f"ocr_words_{dpi}dpi.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    lang = _lang()
    pages = []
    for p in render_pages(doc_id, dpi=dpi, max_side=4000):
        img = preprocess_for_ocr(Image.open(p))
        d = pytesseract.image_to_data(img, lang=lang, config="--psm 6", output_type=pytesseract.Output.DICT)
        lines = {}
        for i, t in enumerate(d["text"]):
            if not t.strip():
                continue
            key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
            lines.setdefault(key, []).append({"t": t, "x0": d["left"][i], "x1": d["left"][i] + d["width"][i],
                                              "y": d["top"][i], "h": d["height"][i]})
        ordered = sorted(lines.values(), key=lambda ws: min(w["y"] for w in ws))
        pages.append({"width": img.width, "lines": [sorted(ws, key=lambda w: w["x0"]) for ws in ordered]})
    cache.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return pages


def preprocess_for_ocr(img: Image.Image, threshold: int = 180) -> Image.Image:
    """Binarisation + removal of table grid lines (OpenCV morphology). On scanned statements the
    grid lines confuse Tesseract badly. Only line pixels are removed, not digits touching them."""
    import cv2
    import numpy as np

    g = np.array(img.convert("L"))
    _, inv = cv2.threshold(g, threshold, 255, cv2.THRESH_BINARY_INV)
    h, w = inv.shape
    horiz = cv2.morphologyEx(inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 25, 20), 1)))
    vert = cv2.morphologyEx(inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 40, 20))))
    lines = cv2.dilate(cv2.bitwise_or(horiz, vert), np.ones((2, 2), np.uint8))
    clean = cv2.bitwise_and(inv, cv2.bitwise_not(lines))
    return Image.fromarray(cv2.bitwise_not(clean))


_WIN_TESSERACT = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe",
]


def find_tesseract() -> str | None:
    """Looks for Tesseract in PATH, then in the usual Windows install folders
    (so the PATH does not have to be edited by hand)."""
    found = shutil.which("tesseract")
    if found:
        return found
    for p in _WIN_TESSERACT:
        if p.exists():
            return str(p)
    return None


def tesseract_available() -> bool:
    exe = find_tesseract()
    if exe:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = exe
    return exe is not None


def delete(doc_id: int):
    shutil.rmtree(doc_dir(doc_id), ignore_errors=True)

"""Extraction pipelines compared in the benchmark.

  vlm_page         image of each page -> VLM, results merged                         (pure VLM)
  vlm_document     all pages in one call -> VLM                                      (VLM, long context)
  hybrid           page image + OCR text -> VLM                                      (VLM helped by OCR)
  ocr_llm          Tesseract -> reconstructed table -> text LLM copies the amounts   (OCR + LLM)
  ocr_llm_rowpick  Tesseract -> numbered table -> text LLM only picks ROW NUMBERS;  (OCR + LLM as selector)
                   the app takes the exact amount from the chosen row
  ocr_rules        Tesseract -> fuzzy label matching, no language model              (deterministic baseline)
  ocr_embeddings   Tesseract -> embedding model matches rows by meaning              (OCR + semantic matching)
  vlm_ocr_rules    a vision model used only as OCR (e.g. GLM-OCR) -> same rules     (AI OCR vs Tesseract)
"""
import json
import math
import re
import time
import unicodedata
from difflib import SequenceMatcher

from . import documents, runtimes
from .numbers import fmt_ro, parse_number
from .schema import ALL_FIELDS, NUMERIC_FIELDS, TEXT_FIELDS, json_schema, row_pick_schema

PIPELINES = {
    "vlm_page": "VLM – page by page",
    "vlm_document": "VLM – whole document in one call",
    "hybrid": "Hybrid – page image + OCR text → VLM",
    "ocr_llm": "OCR → table → text LLM copies the amounts",
    "ocr_llm_rowpick": "OCR → numbered table → text LLM picks the rows",
    "ocr_rules": "OCR + rules (no language model, baseline)",
    "ocr_embeddings": "OCR + embeddings (semantic matching, e.g. EmbeddingGemma)",
    "vlm_ocr_rules": "AI OCR (e.g. GLM-OCR) + rules – alternative to Tesseract",
}
NEEDS_EMBEDDING = {"ocr_embeddings"}
NEEDS_VISION = {"vlm_page", "vlm_document", "hybrid", "vlm_ocr_rules"}
NO_MODEL = {"ocr_rules"}
LLM_JSON = {"vlm_page", "vlm_document", "hybrid", "ocr_llm"}       # pipelines where the model writes amounts


# ------------------------------------------------------------------ prompts
EXAMPLE = ('{"entity": "EXAMPLE COMPANY SRL", "tax_id": "12345678", "period": "31.12.2020", '
           '"fixed_assets": "1.250.000,00", "current_assets": "830.415,27", "inventories": "120.000,00", '
           '"receivables": "310.200,15", "cash": "400.215,12", "total_assets": "2.080.415,27", '
           '"current_liabilities": "512.300,00", "non_current_liabilities": "0,00", '
           '"total_liabilities": "512.300,00", "equity": "1.568.115,27", "revenue": null, '
           '"total_income": null, "total_expenses": null, "net_result": "-35.120,40"}')

ROWPICK_EXAMPLE = ('{"fixed_assets": 4, "current_assets": 11, "inventories": 6, "receivables": 7, "cash": 9, '
                   '"total_assets": 12, "current_liabilities": 17, "non_current_liabilities": 14, '
                   '"total_liabilities": 18, "equity": 23, "revenue": null, "total_income": null, '
                   '"total_expenses": null, "net_result": 21}')


def _field_lines(numeric_only=False):
    lines = [] if numeric_only else [f"- {k}: {label}" for k, label in TEXT_FIELDS.items()]
    for k, (label, syn) in NUMERIC_FIELDS.items():
        ro = [s for s in syn if not re.search(r"\b(assets|liabilities|equity|income|expenses|revenue|turnover|"
                                              r"cash|inventories|receivables|fixed|result)\b", s)] or syn
        lines.append(f"- {k}: {label} (Romanian labels: {', '.join(ro[:3])})")
    return lines


def build_prompt(scope: str, ocr_text: str | None = None, example: bool = False) -> str:
    lines = [
        "You extract data from Romanian financial statements (balance sheet, profit and loss account, "
        "ANAF / Ministry of Finance forms).",
        f"Analyse {scope} and return ONLY a JSON object with the keys below, with no other text.",
        "",
        "Rules:",
        "1. Copy every amount EXACTLY as written in the document, as text (e.g. \"1.689.799,07\"). "
        "Do not compute, round, convert or change the separators (Romanian format: '.' = thousands, "
        "',' = decimals).",
        "2. If the table has two value columns (start and end of the period, or previous and current year), "
        "use the END of period / current year column (usually the last column).",
        "3. If an item does not appear, use null. Do not guess and do not derive values from other rows.",
        "4. Prefer TOTAL rows (e.g. \"Total active curente\") over their components.",
        "5. \"total_expenses\" is the total of expenses from the profit and loss account, NOT "
        "\"cheltuieli în avans\" (prepaid expenses). Negative values are written with a minus sign; a result "
        "on \"sold debitor\" (debit balance) is a loss, i.e. negative.",
        "",
        "Keys:",
        *_field_lines(),
    ]
    if example:
        lines += ["", "The value of each key is the AMOUNT on that row, NOT the name of the row.",
                  "Example of a correct answer (for a different document, invented amounts):", EXAMPLE]
    if ocr_text is not None:
        lines += ["", "Document text obtained by OCR (may contain recognition errors):",
                  "<<<", ocr_text.strip()[:12000], ">>>"]
    return "\n".join(lines)


def build_rowpick_prompt(rows: list[dict], example: bool = False) -> str:
    lines = [
        "Below is a table from a Romanian financial statement, reconstructed by OCR. Every row starts with "
        "its number in square brackets, e.g. [7].",
        "For each key, answer with the NUMBER of the row that contains that item (an integer). Do NOT write the "
        "amount and do NOT write the row name. If the item is not in the table, use null.",
        "Return ONLY a JSON object with the keys below, with no other text.",
        "",
        "Rules:",
        "1. Prefer TOTAL rows (e.g. \"total active curente\") over their components.",
        "2. \"total_expenses\" is the total of expenses from the profit and loss account, NOT "
        "\"cheltuieli in avans\" (prepaid expenses).",
        "3. For net_result choose the row with the result of the period (\"rezultatul exercitiului\", profit or "
        "loss) that has a value in the END of period column.",
        "4. Each row number may be used for at most one key.",
        "",
        "Keys:",
        *_field_lines(numeric_only=True),
    ]
    if example:
        lines += ["", "Example of a correct answer (for a different table):", ROWPICK_EXAMPLE]
    lines += ["", "Table:", numbered_table(rows)]
    return "\n".join(lines)


# ------------------------------------------------------------------ parsing the answer
def parse_json(text: str):
    """Extracts the JSON object from an answer (strips <think>, ```json, ...). Returns (dict|None, strict_valid)."""
    if not text:
        return None, False
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    try:
        d = json.loads(t)
        return (d, True) if isinstance(d, dict) else (None, False)
    except ValueError:
        pass
    t = re.sub(r"```(?:json)?", "", t)
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b <= a:
        return None, False
    try:
        d = json.loads(t[a:b + 1])
        return (d, False) if isinstance(d, dict) else (None, False)   # recovered, but not clean JSON
    except ValueError:
        return None, False


def _unwrap(v):
    """Some models return {"end": .., "start": ..} or lists instead of a single value."""
    if isinstance(v, dict):
        for k in ("end", "current", "value", "sfarsit"):
            if k in v:
                return v[k]
        return list(v.values())[-1] if v else None
    if isinstance(v, list):
        return v[-1] if v else None
    return v


def normalize(raw: dict) -> dict:
    """Raw answer -> {field: float|str|None} for the known fields only."""
    out = {}
    raw = {str(k).strip().lower(): _unwrap(v) for k, v in (raw or {}).items()}
    for k in TEXT_FIELDS:
        v = raw.get(k)
        out[k] = None if v in (None, "", "null") else str(v).strip()
    for k in NUMERIC_FIELDS:
        out[k] = parse_number(raw.get(k))
    return out


def merge(parts: list[dict]) -> dict:
    """Merges per-page extractions: the first non-null value wins."""
    out = {k: None for k in ALL_FIELDS}
    for p in parts:
        for k, v in p.items():
            if out.get(k) is None and v is not None:
                out[k] = v
    return out


def rowpick_to_values(raw: dict | None, rows: list[dict]) -> tuple[dict, list[str]]:
    """Row numbers chosen by the model -> exact amounts from the end-of-period column."""
    out = {k: None for k in ALL_FIELDS}
    log = []
    for k in NUMERIC_FIELDS:
        v = _unwrap((raw or {}).get(k))
        m = re.search(r"\d+", str(v)) if v is not None else None
        if not m:
            continue
        i = int(m.group())
        if 1 <= i <= len(rows):
            out[k] = rows[i - 1]["end"]
            log.append(f"{k:24} ← row [{i}] {rows[i - 1]['label']}: {fmt_ro(rows[i - 1]['end'])}")
        else:
            log.append(f"{k:24} ✗ row [{i}] does not exist")
    return out, log


# ------------------------------------------------------------------ reconstructing the table from OCR
def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s)


_AMOUNT = re.compile(r"^\(?-?(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d{1,3}[.,]\d{2}|0)\)?$")
_CODE = re.compile(r"^(?:\d{2,3}|\d{5,6})$")        # row code: "07", "290" (OCR) or "01046", "010331"


def _clean_tok(t):
    return t.strip("|!/\\:;_~‘’“”'\"»«*.,")


def _clean_label(raw: str) -> tuple[str, bool]:
    """Row text -> (clean label, is_loss). Removes account formulas "(ct.401+403…)", "(rd.07+15)",
    enumerations and OCR noise."""
    text = _plain(raw)
    neg = "sold debitor" in text
    text = re.sub(r"\((?:ct|rd|1d|td|r)\b[^)]*\)?", " ", text)
    label = re.sub(r"[^a-z]+", " ", text)
    label = re.sub(r"^(?:[a-z]{1,2} )+", "", label.strip() + " ").strip()
    label = re.sub(r"\b(?:din care|ct|rd|sold creditor|sold debitor)\b", " ", label)
    label = re.sub(r"\s+", " ", label).strip()
    label = re.sub(r"(?: [a-z]{1,2})+$", "", label)            # trailing OCR noise ("stocuri so")
    return label, neg


def ocr_rows(word_pages: list[dict]) -> list[dict]:
    """Rebuilds the table rows from OCR with positions.

    - a new row starts when a line begins with a row code (2–3 or 5–6 digits) or the previous row ended
      with amounts;
    - labels spread over several lines are joined; account formulas are removed;
    - each amount gets its column from its horizontal position: on each page the amounts form two
      groups (start / end of period), separated by the largest gap between their right edges;
    - rows on "sold debitor" (loss) get a minus sign.
    Returns [{"label", "compact", "start", "end", "raw"}]."""
    rows = []
    for page in word_pages:
        recs, cur = [], None
        for line in page["lines"]:
            toks = [_clean_tok(w["t"]) for w in line]
            first = next((t for t in toks if t), "")
            if cur is None or _CODE.match(first) or cur["amounts"]:
                cur = {"words": [], "amounts": []}
                recs.append(cur)
            merged = []                                    # join fragments split by a small gap ("9.55 1.600.247")
            for w in line:
                t = _clean_tok(w["t"])
                if merged and re.fullmatch(r"[\d.,]+", t) and re.search(r"\d[.,]?$", merged[-1]["t"]) \
                        and w["x0"] - merged[-1]["x1"] < 0.6 * max(w["h"], 1) and "+" not in merged[-1]["t"]:
                    merged[-1] = {**merged[-1], "t": merged[-1]["t"] + t, "x1": w["x1"]}
                else:
                    merged.append({**w, "t": t})
            for w in merged:
                t = re.sub(r"(?<=\d)[.,]{2,}(?=\d)", ".", w["t"])     # "4.718.454,.292"
                t = re.sub(r"^[—–_=]+-?", "", t)            # "—-2.761.945,00": the dash is OCR noise
                if not t:
                    continue
                if _CODE.match(t) and cur["words"] == [] and not cur["amounts"]:
                    continue                                          # the row code
                if _AMOUNT.match(t) and parse_number(t) is not None:
                    cur["amounts"].append({"v": parse_number(t), "x1": w["x1"]})
                    continue
                glued = list(re.finditer(r"-?\d{1,3}(?:[.,]\d{3})*,\d{2}", t))   # "14.327.980,27,14.181.785,71"
                if len(glued) >= 2 and sum(len(g.group()) for g in glued) >= len(t) - len(glued) - 1:
                    for g in glued:
                        cur["amounts"].append({"v": parse_number(g.group()),
                                               "x1": w["x0"] + (w["x1"] - w["x0"]) * g.end() / len(t)})
                    continue
                cur["words"].append(t)
        edges = sorted(a["x1"] for r in recs for a in r["amounts"])
        if not edges:
            continue
        if len(edges) > 1 and (edges[-1] - edges[0]) > 0.08 * page["width"]:
            _, i = max((edges[i + 1] - edges[i], i) for i in range(len(edges) - 1))
            split = (edges[i] + edges[i + 1]) / 2
        else:
            split = edges[0] - 1                                      # a single column -> end of period
        for r in recs:
            raw = " ".join(r["words"])
            if not r["amounts"] or not re.search(r"[a-z]{3}", _plain(raw)):
                continue
            label, neg = _clean_label(raw)
            if len(label) < 4:
                continue
            col = {"start": None, "end": None}
            for am in r["amounts"]:
                col["end" if am["x1"] > split else "start"] = -abs(am["v"]) if neg else am["v"]
            rows.append({"label": label, "compact": label.replace(" ", ""), **col, "raw": raw[:160]})
    return rows


def rows_as_text(rows: list[dict]) -> str:
    """The OCR-reconstructed table, cleaned, for text-only LLMs."""
    lines = ["Item | Balance at start of period | Balance at end of period"]
    for r in rows:
        lines.append(f"{r['label']} | {fmt_ro(r['start'])} | {fmt_ro(r['end'])}")
    return "\n".join(lines)


def numbered_table(rows: list[dict]) -> str:
    lines = ["[No.] Item | Balance at start of period | Balance at end of period"]
    for i, r in enumerate(rows, start=1):
        lines.append(f"[{i}] {r['label']} | {fmt_ro(r['start'])} | {fmt_ro(r['end'])}")
    return "\n".join(lines)


# ------------------------------------------------------------------ AI OCR (GLM-OCR & co.)
def is_ocr_specialist(model_id: str) -> bool:
    m = model_id.lower()
    return any(x in m for x in ("glm-ocr", "glmocr", "deepseek-ocr", "paddleocr", "olmocr", "lightonocr"))


def table_prompt(model_id: str) -> str:
    """GLM-OCR only accepts its documented task prompts ("Table Recognition:"); other VLMs get an
    explicit transcription request."""
    if "glm-ocr" in model_id.lower() or "glmocr" in model_id.lower():
        return "Table Recognition:"
    return ("Transcribe ALL tables in the image as Markdown (| cell | cell |). Keep every column, including empty "
            "cells, and copy the numbers exactly as written. Do not add anything else.")


def _table_rows(text: str) -> list[list[str]]:
    """Rows of an HTML (<tr><td>) or Markdown (| a | b |) table in a model's answer."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    rows = []
    if "<tr" in text.lower():
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S | re.I):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)
            rows.append([re.sub(r"<[^>]+>", " ", c).strip() for c in cells])
    else:
        for line in text.splitlines():
            line = line.strip()
            if line.count("|") >= 2 and not re.fullmatch(r"[|:\-\s]+", line):
                rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def rows_from_tables(page_texts: list[str]) -> list[dict]:
    """Tables transcribed by a model -> same format as ocr_rows(): last column = end of period,
    second to last = start of period; multi-line labels are joined; "sold debitor" -> negative."""
    out = []
    for text in page_texts:
        rows = _table_rows(text)
        if not rows:
            continue
        ncol = max(len(r) for r in rows)
        pending = []
        for r in rows:
            cells = r + [""] * (ncol - len(r))
            nums = {}
            for i, c in enumerate(cells):
                t = re.sub(r"(?<=\d)[.,]{2,}(?=\d)", ".", _clean_tok(c.replace(" ", "")))
                if i >= ncol - 2 and t and _AMOUNT.match(t) and parse_number(t) is not None:
                    nums[i] = parse_number(t)
            words = [c for i, c in enumerate(cells) if i < ncol - 2 and c]
            if not nums:
                if re.search(r"denumire|sold la|inceputul|sfarsitul|perioadei", _plain(" ".join(cells))):
                    pending = []                                       # table header
                elif any(re.search(r"[A-Za-z]{3}", w) for w in words):
                    pending += words
                continue
            raw = " ".join(pending + words)
            pending = []
            label, neg = _clean_label(raw)
            if len(label) < 4:
                continue
            sgn = (lambda v: -abs(v)) if neg else (lambda v: v)
            out.append({"label": label, "compact": label.replace(" ", ""),
                        "start": sgn(nums[ncol - 2]) if ncol - 2 in nums and ncol >= 3 else None,
                        "end": sgn(nums[ncol - 1]) if ncol - 1 in nums else None,
                        "raw": raw[:160]})
    return out


# ------------------------------------------------------------------ methods without a generative model
def find_tax_id(texts):
    m = re.search(r"(?:cui|cod fiscal|cod de identificare fiscala)[^0-9]{0,30}(\d{6,10})", _plain("\n".join(texts)))
    return m.group(1) if m else None


def rules_extract(texts: list[str], rows: list[dict]) -> dict:
    """Deterministic baseline: fuzzy matching of the row label against the known labels (by LETTERS,
    tolerant to OCR errors); takes the end-of-period amount."""
    syn = [(_plain(s).replace(" ", ""), k) for k, (_, ss) in NUMERIC_FIELDS.items() for s in ss]
    out = {k: None for k in ALL_FIELDS}
    out["tax_id"] = find_tax_id(texts)
    for ln in rows:
        if ln["end"] is None:
            continue
        best, field = max(((SequenceMatcher(None, ln["compact"], s).ratio(), k) for s, k in syn), key=lambda x: x[0])
        if best >= 0.9 and out[field] is None:
            out[field] = ln["end"]
    return out


def embeddings_extract(settings: dict, model_id: str, texts: list[str], rows: list[dict]) -> tuple[dict, str]:
    """SEMANTIC matching: every field (with its labels) and every OCR row are turned into vectors by an
    embedding model (e.g. EmbeddingGemma). Each field gets the closest row by meaning (cosine similarity)
    if it passes the threshold; a row can be used for one field only. No text is generated, so the model
    cannot invent amounts, but it can pick the wrong row."""
    threshold = float(settings.get("embedding_threshold", 0.85))
    lines = [r for r in rows if r["end"] is not None]
    out = {k: None for k in ALL_FIELDS}
    out["tax_id"] = find_tax_id(texts)
    if not lines:
        return out, "OCR found no rows with amounts."
    queries = [(k, s) for k, (label, ss) in NUMERIC_FIELDS.items() for s in [label] + ss]
    prefix = "task: sentence similarity | query: "            # prompt format recommended for EmbeddingGemma
    vecs = runtimes.embed(settings, model_id, [prefix + s for _, s in queries] + [prefix + ln["label"] for ln in lines])
    qv, lv = vecs[:len(queries)], vecs[len(queries):]

    def cos(a, b):
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
        return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0

    best = {}                                                   # (field, row) -> best score over the labels
    for (k, _), q in zip(queries, qv):
        for j, l in enumerate(lv):
            sc = cos(q, l)
            if sc > best.get((k, j), -1):
                best[(k, j)] = sc
    used, log = set(), []
    for (k, j), sc in sorted(best.items(), key=lambda x: -x[1]):
        if out[k] is None and j not in used and sc >= threshold:
            out[k] = lines[j]["end"]
            used.add(j)
            log.append(f"{k:24} ← {sc:.3f}  {lines[j]['raw']}")
    for k in NUMERIC_FIELDS:
        if out[k] is None:
            free = [(j, best[(k, j)]) for j in range(len(lines)) if j not in used]
            if not free:
                log.append(f"{k:24} ✗ all rows were already used")
                continue
            j, sc = max(free, key=lambda x: x[1])
            log.append(f"{k:24} ✗ closest free row scores {sc:.3f} < threshold {threshold}: {lines[j]['raw']}")
    return out, f"Similarity threshold: {threshold}\n" + "\n".join(log)


# ------------------------------------------------------------------ running a pipeline
def run(settings: dict, doc_id: int, model_id: str | None, pipeline: str) -> dict:
    """Runs one pipeline on one document. Returns a dict ready to be stored in `runs`."""
    dpi, max_side = int(settings["dpi"]), int(settings["max_side_px"])
    example = settings.get("prompt_example", "no") == "yes"
    constrained = settings.get("constrained_output", "no") == "yes"
    schema = json_schema(constrained)
    agg = {"total_time": 0.0, "load_time": 0.0, "tokens_generated": 0, "memory_mb": None}
    tps, raws, parts, notes = [], [], [], []
    valid_all = True

    def generate(prompt, images, sch):
        r = runtimes.chat(settings, model_id, prompt, images, sch)
        for k in ("total_time", "load_time", "tokens_generated"):
            agg[k] += r.get(k) or 0
        agg["memory_mb"] = max(filter(None, [agg["memory_mb"], r.get("memory_mb")]), default=None)
        if r.get("tokens_per_sec"):
            tps.append(r["tokens_per_sec"])
        if sch and not r.get("schema_used"):
            notes.append("[the server rejected the JSON schema; this call ran WITHOUT constrained decoding]")
        raws.append(r["text"])
        return r["text"]

    def call(prompt, images):
        nonlocal valid_all
        d, valid = parse_json(generate(prompt, images, schema))
        valid_all = valid_all and valid
        parts.append(normalize(d) if d else {})

    def result(extracted, raw, json_valid):
        return {"extracted": extracted, "raw_output": "\n".join(notes + [raw]), "json_valid": json_valid,
                "total_time": agg["total_time"], "load_time": agg["load_time"] or None,
                "tokens_generated": agg["tokens_generated"] or None,
                "tokens_per_sec": round(sum(tps) / len(tps), 2) if tps else None, "memory_mb": agg["memory_mb"]}

    if pipeline == "ocr_rules":
        t0 = time.perf_counter()
        pages = documents.ocr_pages(doc_id)
        extracted = rules_extract(pages, ocr_rows(documents.ocr_words(doc_id)))
        return {"extracted": extracted, "raw_output": "\n\f\n".join(pages), "json_valid": None,
                "total_time": time.perf_counter() - t0}

    if pipeline == "ocr_embeddings":
        t0 = time.perf_counter()
        pages = documents.ocr_pages(doc_id)
        extracted, log = embeddings_extract(settings, model_id, pages, ocr_rows(documents.ocr_words(doc_id)))
        return {"extracted": extracted, "raw_output": log, "json_valid": None,
                "total_time": time.perf_counter() - t0,
                "memory_mb": runtimes.ollama_memory(settings, model_id.split("/", 1)[1])}

    if pipeline == "vlm_ocr_rules":
        texts = [generate(table_prompt(model_id), [documents.b64(p)], None)
                 for p in documents.render_pages(doc_id, dpi, max_side)]
        rows = rows_from_tables(texts)
        extracted = rules_extract(texts, rows)
        return result(extracted, f"[{len(rows)} table rows recognised]\n\n" +
                      "\n\n----- next page -----\n\n".join(texts), None)

    if pipeline == "ocr_llm_rowpick":
        rows = ocr_rows(documents.ocr_words(doc_id))
        text = generate(build_rowpick_prompt(rows, example), [], row_pick_schema())
        d, valid = parse_json(text)
        extracted, log = rowpick_to_values(d, rows)
        extracted["tax_id"] = find_tax_id(documents.ocr_pages(doc_id))
        return result(extracted, text + "\n\n----- rows chosen -----\n" + "\n".join(log), int(valid))

    if pipeline == "vlm_page":
        for p in documents.render_pages(doc_id, dpi, max_side):
            call(build_prompt("this page of a financial statement", None, example), [documents.b64(p)])
    elif pipeline == "vlm_document":
        imgs = [documents.b64(p) for p in documents.render_pages(doc_id, dpi, max_side)]
        call(build_prompt(f"the document ({len(imgs)} pages, in order)", None, example), imgs)
    elif pipeline == "ocr_llm":
        text = rows_as_text(ocr_rows(documents.ocr_words(doc_id)))
        call(build_prompt("the table below (reconstructed by OCR from a balance sheet; the last column is the "
                          "end of the period)", text, example), [])
    elif pipeline == "hybrid":
        pages = documents.render_pages(doc_id, dpi, max_side)
        for p, t in zip(pages, documents.ocr_pages(doc_id)):
            call(build_prompt("the image of this page (the OCR text is given only as help; the image has "
                              "priority)", t, example), [documents.b64(p)])
    else:
        raise ValueError(f"Unknown pipeline: {pipeline}")

    return result(merge(parts), "\n\n----- next page -----\n\n".join(raws), int(valid_all))


def phone_prompt(doc_id: int, pipeline: str, example: bool) -> str:
    """The exact prompt to paste into a model on the phone (text variants include the OCR table)."""
    if pipeline == "ocr_llm_rowpick":
        return build_rowpick_prompt(ocr_rows(documents.ocr_words(doc_id)), example)
    if pipeline == "ocr_llm":
        return build_prompt("the table below (reconstructed by OCR from a balance sheet; the last column is the "
                            "end of the period)", rows_as_text(ocr_rows(documents.ocr_words(doc_id))), example)
    return build_prompt("this page of a financial statement", None, example)


def external_result(doc_id: int, pipeline: str, answer: str) -> tuple[dict, int, str]:
    """Scores an answer obtained outside the app (e.g. on the phone). Returns (extracted, json_valid, log)."""
    if pipeline == "ocr_llm_rowpick":
        d, valid = parse_json(answer)
        extracted, log = rowpick_to_values(d, ocr_rows(documents.ocr_words(doc_id)))
        return extracted, int(valid), "\n".join(log)
    parts = [p for p in answer.split("-----") if p.strip()]     # several pages separated by -----
    parsed = [parse_json(p) for p in parts]
    extracted = merge([normalize(d) for d, _ in parsed if d])
    return extracted, (int(all(v for _, v in parsed)) if parsed else 0), ""

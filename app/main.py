"""FinAI C — a local finance app + benchmark of local models for extracting figures from
financial statements. Start:  uvicorn app.main:app --port 8006   then open http://localhost:8006
"""
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, documents, extract, indicators, jobs, metrics, report, runtimes
from .numbers import parse_number
from .schema import NUMERIC_FIELDS, TEXT_FIELDS

app = FastAPI(title="FinAI C")
STATIC = Path(__file__).resolve().parent.parent / "static"
db.init()

CATEGORIES = {
    "income": ["Sales of goods", "Services", "Interest", "Grants and subsidies", "Other income"],
    "expense": ["Salaries and contributions", "Rent", "Utilities", "Raw materials and supplies", "Goods for resale",
                "Transport", "Marketing", "IT and software", "Taxes and duties", "External services",
                "Other expenses"],
}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# ------------------------------------------------------------------ meta
@app.get("/api/meta")
def meta():
    return {"numeric_fields": {k: v[0] for k, v in NUMERIC_FIELDS.items()}, "text_fields": TEXT_FIELDS,
            "pipelines": extract.PIPELINES, "vision_pipelines": sorted(extract.NEEDS_VISION),
            "indicators": indicators.INDICATORS, "statuses": metrics.STATUS, "categories": CATEGORIES}


@app.get("/api/status")
def status():
    m = runtimes.list_models(db.get_settings())
    return {"tesseract": documents.tesseract_available(), "ollama": "ollama" not in m["errors"],
            "openai": "openai" not in m["errors"], "n_models": len(m["models"])}


@app.get("/api/settings")
def get_settings():
    return db.get_settings()


@app.post("/api/settings")
def post_settings(d: dict):
    db.save_settings(d)
    return db.get_settings()


@app.get("/api/models")
def models():
    return runtimes.list_models(db.get_settings())


# ------------------------------------------------------------------ companies
class CompanyIn(BaseModel):
    name: str = Field(min_length=1)
    tax_id: str | None = None


@app.get("/api/companies")
def companies():
    return db.q("SELECT * FROM companies ORDER BY name")


@app.post("/api/companies")
def add_company(c: CompanyIn):
    return {"id": db.ex("INSERT INTO companies(name, tax_id) VALUES(?,?)", (c.name.strip(), c.tax_id))}


@app.delete("/api/companies/{cid}")
def delete_company(cid: int):
    for d in db.q("SELECT id FROM documents WHERE company_id=?", (cid,)):
        documents.delete(d["id"])
    db.ex("DELETE FROM companies WHERE id=?", (cid,))
    return {"ok": True}


# ------------------------------------------------------------------ documents
@app.get("/api/documents")
def list_documents():
    return db.q("""SELECT d.id, d.company_id, c.name AS company, d.filename, d.kind, d.pages, d.has_text,
                   d.ground_truth IS NOT NULL AS has_gt, d.accepted_run, d.created,
                   (SELECT COUNT(*) FROM runs r WHERE r.document_id=d.id) AS n_runs
                   FROM documents d LEFT JOIN companies c ON c.id=d.company_id ORDER BY d.id""")


@app.get("/api/documents/{did}")
def document(did: int):
    d = db.q1("SELECT d.*, c.name AS company FROM documents d LEFT JOIN companies c ON c.id=d.company_id WHERE d.id=?",
              (did,))
    if not d:
        raise HTTPException(404, "Document not found")
    return d


@app.post("/api/documents")
async def upload(file: UploadFile = File(...), company_id: int | None = Form(None),
                 new_company: str | None = Form(None), tax_id: str | None = Form(None)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
        raise HTTPException(400, "Only PDF files or images (png, jpg, webp, tif) are accepted.")
    if not company_id:
        if not new_company:
            raise HTTPException(400, "Choose a company or type the name of a new one.")
        company_id = db.ex("INSERT INTO companies(name, tax_id) VALUES(?,?)", (new_company.strip(), tax_id))
    data = await file.read()
    did = db.ex("INSERT INTO documents(company_id, filename) VALUES(?,?)", (company_id, file.filename))
    try:
        info = documents.store_upload(did, file.filename, data)
    except Exception as e:
        db.ex("DELETE FROM documents WHERE id=?", (did,))
        documents.delete(did)
        raise HTTPException(400, f"The file cannot be read: {e}")
    db.ex("UPDATE documents SET kind=?, pages=?, has_text=? WHERE id=?", (info["kind"], info["pages"], info["has_text"], did))
    return {"id": did, "company_id": company_id, **info}


@app.delete("/api/documents/{did}")
def delete_document(did: int):
    db.ex("DELETE FROM documents WHERE id=?", (did,))
    documents.delete(did)
    return {"ok": True}


@app.get("/api/documents/{did}/page/{n}")
def page(did: int, n: int):
    s = db.get_settings()
    pages = documents.render_pages(did, int(s["dpi"]), int(s["max_side_px"]))
    if not 1 <= n <= len(pages):
        raise HTTPException(404)
    return FileResponse(pages[n - 1], media_type="image/png")


@app.get("/api/documents/{did}/ocr-table")
def ocr_table(did: int):
    """The table rebuilt from OCR (what text-only models receive)."""
    if not documents.tesseract_available():
        raise HTTPException(400, "Tesseract is not installed.")
    return PlainTextResponse(extract.numbered_table(extract.ocr_rows(documents.ocr_words(did))))


class GroundTruth(BaseModel):
    values: dict   # {text_field: str, numeric_field: {"end": "1.234,56", "start": ".."}}


@app.put("/api/documents/{did}/ground-truth")
def save_gt(did: int, body: GroundTruth):
    out = metrics.normalize_ground_truth(body.values)
    db.ex("UPDATE documents SET ground_truth=? WHERE id=?", (out, did))
    jobs.rescore_document(did)
    return out


@app.post("/api/documents/{did}/accept/{rid}")
def accept(did: int, rid: int):
    """The values extracted by a run become the official values of the document (used by the dashboard)."""
    r = db.q1("SELECT extracted FROM runs WHERE id=? AND document_id=?", (rid, did))
    if not r:
        raise HTTPException(404)
    db.ex("UPDATE documents SET accepted_values=?, accepted_run=? WHERE id=?", (r["extracted"], rid, did))
    return {"ok": True}


# ------------------------------------------------------------------ runs
class RunIn(BaseModel):
    documents: list[int]
    models: list[str] = []
    pipelines: list[str]
    repetitions: int = Field(1, ge=1, le=10)


@app.post("/api/runs")
def start(r: RunIn):
    bad = [p for p in r.pipelines if p not in extract.PIPELINES]
    if bad or not r.pipelines or not r.documents:
        raise HTTPException(400, "Choose at least one document and one valid pipeline.")
    if any(p not in extract.NO_MODEL for p in r.pipelines) and not r.models and "ocr_rules" not in r.pipelines:
        raise HTTPException(400, "AI pipelines need at least one model.")
    if any(p in ("ocr_rules", "ocr_llm", "ocr_llm_rowpick", "hybrid", "ocr_embeddings") for p in r.pipelines):
        if not documents.tesseract_available():
            raise HTTPException(400, "OCR pipelines need Tesseract installed (see README).")
    known = runtimes.list_models(db.get_settings())["models"]
    no_vision = {m["id"] for m in known if m["vision"] is False}
    embedding = {m["id"] for m in known if m.get("embedding")}
    jid = jobs.submit(r.documents, r.models, r.pipelines, r.repetitions, no_vision, embedding)
    if jobs.JOBS[jid]["total"] == 0:
        jobs.JOBS.pop(jid, None)
        raise HTTPException(400, "No valid combination. Models without vision cannot run image pipelines, embedding "
                                 "models (e.g. EmbeddingGemma) only run 'OCR + embeddings', and OCR models "
                                 "(e.g. GLM-OCR) only run 'AI OCR + rules'.")
    return jobs.JOBS[jid]


@app.get("/api/jobs")
def list_jobs():
    return sorted(jobs.JOBS.values(), key=lambda j: j["start"], reverse=True)


@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str):
    if jid in jobs.JOBS:
        jobs.JOBS[jid]["cancelled"] = True
    return {"ok": True}


@app.get("/api/runs")
def list_runs(document_id: int | None = None):
    rs = report.runs(document_id)
    for r in rs:
        r.pop("raw_output", None)
        r["config"] = report.config(r)
    return rs


@app.get("/api/runs/{rid}")
def get_run(rid: int):
    r = db.q1("SELECT * FROM runs WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404)
    return r


@app.delete("/api/runs/{rid}")
def delete_run(rid: int):
    db.ex("DELETE FROM runs WHERE id=?", (rid,))
    return {"ok": True}


class External(BaseModel):
    """A result obtained outside the app (e.g. on the phone, with Gemma 3n / Bonsai)."""
    document_id: int
    model: str
    device: str = "phone"
    pipeline: str = "ocr_llm"
    answer: str                       # the model's answer, copied from the phone
    total_time: float | None = None
    tokens_per_sec: float | None = None
    memory_mb: float | None = None


@app.post("/api/runs/external")
def import_external(e: External):
    doc = db.q1("SELECT ground_truth FROM documents WHERE id=?", (e.document_id,))
    if not doc:
        raise HTTPException(404, "Document not found")
    if e.pipeline not in extract.PIPELINES:
        raise HTTPException(400, "Unknown pipeline")
    extracted, valid, log = extract.external_result(e.document_id, e.pipeline, e.answer)
    m = metrics.evaluate(extracted, doc["ground_truth"])
    s = db.get_settings()
    params = {"source": "manual import", "prompt_example": s.get("prompt_example")}
    rid = db.ex("""INSERT INTO runs(document_id, model, runtime, pipeline, device, params, raw_output, extracted,
                   metrics, total_time, tokens_per_sec, memory_mb, json_valid) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (e.document_id, e.model, "external", e.pipeline, e.device, params,
                 e.answer + ("\n\n----- rows chosen -----\n" + log if log else ""), extracted, m,
                 e.total_time, e.tokens_per_sec, e.memory_mb, valid))
    return {"id": rid, "metrics": m}


@app.get("/api/prompt")
def prompt(pipeline: str = "ocr_llm", document_id: int | None = None):
    """The exact prompt the app uses — to copy it to the phone for external tests.
    ocr_llm / ocr_llm_rowpick: text only (prompt + OCR table), works with any model (e.g. Bonsai 8B);
    vlm_page: the prompt to send together with a photo of each page (vision models only)."""
    example = db.get_settings().get("prompt_example", "no") == "yes"
    if pipeline in ("ocr_llm", "ocr_llm_rowpick"):
        if not document_id:
            raise HTTPException(400, "Choose a document.")
        if not documents.tesseract_available():
            raise HTTPException(400, "Tesseract is not installed.")
    return PlainTextResponse(extract.phone_prompt(document_id, pipeline, example))


# ------------------------------------------------------------------ comparison and export
@app.get("/api/compare")
def compare(document_id: int | None = None):
    return report.comparison(document_id)


@app.get("/api/export/runs.csv")
def export_runs(document_id: int | None = None):
    return Response(report.runs_csv(document_id), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=runs.csv"})


@app.get("/api/export/summary.csv")
def export_summary(document_id: int | None = None):
    return Response(report.summary_csv(document_id), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=model_summary.csv"})


# ------------------------------------------------------------------ transactions
class TransactionIn(BaseModel):
    company_id: int
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    type: str = Field(pattern=r"^(income|expense)$")
    category: str
    amount: float = Field(gt=0)
    description: str | None = None


@app.get("/api/transactions")
def transactions(company_id: int | None = None, month: str | None = None):
    sql, args = "SELECT t.*, c.name AS company FROM transactions t JOIN companies c ON c.id=t.company_id WHERE 1=1", []
    if company_id:
        sql += " AND t.company_id=?"
        args.append(company_id)
    if month:
        sql += " AND substr(t.date,1,7)=?"
        args.append(month)
    return db.q(sql + " ORDER BY t.date DESC, t.id DESC", tuple(args))


@app.post("/api/transactions")
def add_transaction(t: TransactionIn):
    if t.category not in CATEGORIES[t.type]:
        raise HTTPException(400, "Invalid category for the selected type.")
    return {"id": db.ex("INSERT INTO transactions(company_id, date, type, category, amount, description) "
                        "VALUES(?,?,?,?,?,?)", (t.company_id, t.date, t.type, t.category, round(t.amount, 2),
                                                t.description))}


@app.delete("/api/transactions/{tid}")
def delete_transaction(tid: int):
    db.ex("DELETE FROM transactions WHERE id=?", (tid,))
    return {"ok": True}


# ------------------------------------------------------------------ dashboard
@app.get("/api/dashboard")
def dashboard():
    out = []
    for c in db.q("SELECT * FROM companies ORDER BY name"):
        doc = db.q1("""SELECT id, filename, accepted_values FROM documents
                       WHERE company_id=? AND accepted_values IS NOT NULL ORDER BY id DESC""", (c["id"],))
        by_cat = db.q("SELECT type, category, SUM(amount) AS total FROM transactions WHERE company_id=? "
                      "GROUP BY type, category", (c["id"],))
        monthly = db.q("""SELECT substr(date,1,7) AS month,
                          SUM(CASE WHEN type='income' THEN amount ELSE 0 END) AS income,
                          SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS expenses
                          FROM transactions WHERE company_id=? GROUP BY month ORDER BY month DESC LIMIT 12""",
                       (c["id"],))
        inc = sum(r["total"] for r in by_cat if r["type"] == "income")
        exp = sum(r["total"] for r in by_cat if r["type"] == "expense")
        out.append({**c,
                    "document": doc and {"id": doc["id"], "filename": doc["filename"]},
                    "values": doc["accepted_values"] if doc else None,
                    "indicators": indicators.compute(doc["accepted_values"]) if doc else None,
                    "income": inc, "expenses": exp, "result": inc - exp,
                    "by_category": by_cat, "monthly": list(reversed(monthly)),
                    "n_documents": db.q1("SELECT COUNT(*) AS n FROM documents WHERE company_id=?", (c["id"],))["n"]})
    return out


app.mount("/static", StaticFiles(directory=STATIC), name="static")

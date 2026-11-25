"""Run queue. Models run SEQUENTIALLY (one at a time) so that measured times and memory are not
affected by other models running in parallel."""
import threading
import uuid
from datetime import datetime

from . import db, extract, metrics, runtimes

JOBS: dict[str, dict] = {}
_queue_lock = threading.Lock()


def compatible(model: str | None, pipeline: str, no_vision=(), embedding=()) -> bool:
    """Which (model, pipeline) combinations make sense."""
    if (pipeline in extract.NO_MODEL) != (model is None):
        return False
    if model is None:
        return True
    if model in no_vision and pipeline in extract.NEEDS_VISION:
        return False
    if (pipeline in extract.NEEDS_EMBEDDING) != (model in embedding):
        return False                     # embedding models cannot generate text; generators cannot embed
    if extract.is_ocr_specialist(model) and pipeline != "vlm_ocr_rules":
        return False                     # GLM-OCR & co. only transcribe; they do not answer with JSON
    return True


def submit(doc_ids, model_ids, pipelines, repetitions=1, no_vision=(), embedding=()) -> str:
    tasks = []
    for model in model_ids:
        for pipe in pipelines:
            if compatible(model, pipe, no_vision, embedding):
                tasks += [{"doc": d, "model": model, "pipeline": pipe, "rep": r}
                          for d in doc_ids for r in range(1, repetitions + 1)]
    if "ocr_rules" in pipelines:         # the baseline has no model and runs once per document
        tasks += [{"doc": d, "model": None, "pipeline": "ocr_rules", "rep": 1} for d in doc_ids]
    jid = uuid.uuid4().hex[:8]
    JOBS[jid] = {"id": jid, "total": len(tasks), "done": 0, "errors": 0, "current": None,
                 "state": "queued", "cancelled": False, "start": datetime.now().isoformat(timespec="seconds"),
                 "log": []}
    if tasks:
        threading.Thread(target=_worker, args=(jid, tasks), daemon=True).start()
    return jid


def _worker(jid, tasks):
    job = JOBS[jid]
    with _queue_lock:                       # one active job at a time
        job["state"] = "running"
        settings = db.get_settings()
        prev_model = None
        for t in tasks:
            if job["cancelled"]:
                job["state"] = "cancelled"
                break
            if prev_model and prev_model != t["model"]:
                runtimes.unload(settings, prev_model)
            prev_model = t["model"] or prev_model
            label = f"{t['model'] or '—'} · {extract.PIPELINES[t['pipeline']]} · doc {t['doc']} · rep {t['rep']}"
            job["current"] = label
            try:
                run_one(settings, t["doc"], t["model"], t["pipeline"], t["rep"], jid)
                job["log"].append("✓ " + label)
            except Exception as e:
                job["errors"] += 1
                job["log"].append(f"✗ {label}: {e}")
            job["done"] += 1
        if prev_model:
            runtimes.unload(settings, prev_model)
        if job["state"] == "running":
            job["state"] = "finished"
        job["current"] = None


def run_params(settings) -> dict:
    keys = ("dpi", "max_side_px", "num_ctx", "thinking", "embedding_threshold", "prompt_example", "constrained_output")
    return {k: settings.get(k) for k in keys}


def run_one(settings, doc_id, model_id, pipeline, rep=1, jid=None):
    doc = db.q1("SELECT * FROM documents WHERE id=?", (doc_id,))
    if not doc:
        raise ValueError(f"Document {doc_id} does not exist")
    runtime = model_id.split("/")[0] if model_id else "local"
    try:
        res = extract.run(settings, doc_id, model_id, pipeline)
        err = None
    except Exception as e:
        res, err = {"extracted": {}, "raw_output": "", "json_valid": 0, "total_time": None}, str(e)
    m = metrics.evaluate(res["extracted"], doc.get("ground_truth"))
    rid = db.ex(
        """INSERT INTO runs(document_id, model, runtime, pipeline, device, params, raw_output, extracted, metrics,
           total_time, load_time, tokens_generated, tokens_per_sec, memory_mb, json_valid, error, repetition, job_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (doc_id, model_id or "ocr+rules", runtime, pipeline, settings.get("device", "laptop"), run_params(settings),
         res.get("raw_output"), res["extracted"], m, res.get("total_time"), res.get("load_time"),
         res.get("tokens_generated"), res.get("tokens_per_sec"), res.get("memory_mb"), res.get("json_valid"),
         err, rep, jid))
    if err:
        raise RuntimeError(err)
    return rid


def rescore_document(doc_id):
    """After the ground truth changes, recompute the metrics of all runs on the document."""
    doc = db.q1("SELECT ground_truth FROM documents WHERE id=?", (doc_id,))
    for r in db.q("SELECT id, extracted FROM runs WHERE document_id=?", (doc_id,)):
        db.ex("UPDATE runs SET metrics=? WHERE id=?", (metrics.evaluate(r["extracted"] or {}, doc["ground_truth"]), r["id"]))

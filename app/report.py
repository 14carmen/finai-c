"""Aggregating runs into the comparison table (and the CSV files for the paper)."""
import csv
import io
import statistics as st

from . import db, extract
from .metrics import STATUS
from .schema import NUMERIC_FIELDS

METRICS = ["accuracy", "accuracy_tolerant", "precision", "f1", "hallucination_rate", "indicator_error", "consistency"]
PERF = ["total_time", "load_time", "tokens_per_sec", "memory_mb"]


def _ms(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, None
    return round(st.mean(vals), 4), (round(st.stdev(vals), 4) if len(vals) > 1 else 0.0)


def runs(document_id=None):
    sql = """SELECT r.*, d.filename, d.ground_truth IS NOT NULL AS has_gt FROM runs r
             JOIN documents d ON d.id = r.document_id"""
    args = ()
    if document_id:
        sql += " WHERE r.document_id = ?"
        args = (document_id,)
    return db.q(sql + " ORDER BY r.id DESC", args)


def config(r) -> str:
    """Settings that change the result (runs with different settings are not averaged together)."""
    p = r.get("params") or {}
    pipe = r["pipeline"]
    if pipe == "ocr_rules" or not p:
        return ""
    if pipe == "ocr_embeddings":
        return f"threshold {p.get('embedding_threshold', '0.85')}"
    parts = []
    if pipe in extract.NEEDS_VISION:
        parts.append(f"{p.get('dpi')} dpi, max {p.get('max_side_px')} px")
    if p.get("thinking") == "yes":
        parts.append("thinking")
    if pipe in extract.LLM_JSON or pipe == "ocr_llm_rowpick":
        parts.append("one-shot" if p.get("prompt_example") == "yes" else "zero-shot")
    if pipe in extract.LLM_JSON and p.get("constrained_output") == "yes":
        parts.append("constrained")
    if p.get("source") == "manual import":
        parts.append("imported")
    return ", ".join(parts)


def comparison(document_id=None):
    groups = {}
    for r in runs(document_id):
        groups.setdefault((r["model"], r["pipeline"], r["device"], config(r)), []).append(r)
    out = []
    for (model, pipe, dev, cfg), rs in groups.items():
        ok = [r for r in rs if not r["error"]]
        g = {"model": model, "pipeline": pipe, "pipeline_name": extract.PIPELINES.get(pipe, pipe),
             "device": dev, "config": cfg, "n_runs": len(rs), "n_errors": len(rs) - len(ok),
             "n_documents": len({r["document_id"] for r in rs})}
        for k in METRICS:
            g[k], g[k + "_std"] = _ms([(r["metrics"] or {}).get(k) for r in ok])
        for k in PERF:
            g[k], g[k + "_std"] = _ms([r[k] for r in ok])
        jv = [r["json_valid"] for r in rs if r["json_valid"] is not None]
        g["json_valid"] = round(sum(jv) / len(jv), 3) if jv else None
        cnt = {s: 0 for s in STATUS}
        field_ok = {k: [0, 0] for k in NUMERIC_FIELDS}
        for r in ok:
            m = r["metrics"] or {}
            for s, c in (m.get("counts") or {}).items():
                cnt[s] = cnt.get(s, 0) + c
            for k, s in (m.get("per_field") or {}).items():
                if s not in ("correct_null", "hallucinated") and k in field_ok:
                    field_ok[k][1] += 1
                    field_ok[k][0] += s == "correct"
        g["error_types"] = cnt
        g["per_field"] = {k: (round(a / b, 3) if b else None) for k, (a, b) in field_ok.items()}
        out.append(g)
    out.sort(key=lambda g: (-(g["f1"] if g["f1"] is not None else -1), g["total_time"] or 1e9))
    return out


def runs_csv(document_id=None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "document", "model", "pipeline", "device", "config", "repetition", "total_time_s", "load_time_s",
                "tokens_per_sec", "memory_mb", "json_valid", "error"] + METRICS + [f"field_{k}" for k in NUMERIC_FIELDS])
    for r in runs(document_id):
        m = r["metrics"] or {}
        w.writerow([r["id"], r["filename"], r["model"], r["pipeline"], r["device"], config(r), r["repetition"],
                    r["total_time"], r["load_time"], r["tokens_per_sec"], r["memory_mb"], r["json_valid"],
                    r["error"]] + [m.get(k) for k in METRICS] +
                   [(m.get("per_field") or {}).get(k) for k in NUMERIC_FIELDS])
    return buf.getvalue()


def summary_csv(document_id=None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    base = ["model", "pipeline", "device", "config", "n_runs", "n_errors", "n_documents", "json_valid"]
    for k in METRICS + PERF:
        base += [k, k + "_std"]
    w.writerow(base + [f"err_{s}" for s in STATUS] + [f"acc_{k}" for k in NUMERIC_FIELDS])
    for g in comparison(document_id):
        w.writerow([g.get(c) for c in base] + [g["error_types"].get(s) for s in STATUS] +
                   [g["per_field"].get(k) for k in NUMERIC_FIELDS])
    return buf.getvalue()

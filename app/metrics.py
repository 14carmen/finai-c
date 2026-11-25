"""Comparison of an extraction with the ground truth, plus an error typology."""
import math
import re

from . import indicators
from .schema import LEGACY_KEYS, NUMERIC_FIELDS, TEXT_FIELDS
from .numbers import parse_number

STATUS = {
    "correct": "Correct (±1 unit)",
    "close": "Close (error ≤ 1%)",
    "wrong_column": "Wrong column (start-of-period value)",
    "scale_error": "Scale error (×10ⁿ, separator misread)",
    "wrong_sign": "Wrong sign",
    "wrong": "Wrong value",
    "missing": "Missing (null although present in the document)",
    "hallucinated": "Hallucinated (value for an item that does not exist)",
    "correct_null": "Correctly absent",
}


def _close(a, b, abs_tol=1.0, rel=0.0):
    return abs(a - b) <= max(abs_tol, rel * abs(b))


def field_status(pred, gt_end, gt_start=None):
    if gt_end is None:
        return "correct_null" if pred is None else "hallucinated"
    if pred is None:
        return "missing"
    if _close(pred, gt_end):
        return "correct"
    if gt_start is not None and _close(pred, gt_start):
        return "wrong_column"
    if _close(pred, -gt_end):
        return "wrong_sign"
    if gt_end != 0 and pred != 0:
        ratio = abs(pred / gt_end)
        k = round(math.log10(ratio))
        if k != 0 and abs(ratio / 10 ** k - 1) < 0.001:
            return "scale_error"
    if _close(pred, gt_end, rel=0.01):
        return "close"
    return "wrong"


def normalize_ground_truth(values: dict) -> dict:
    """Accepts the English format {field: {"end", "start"}}, a plain value per field, or the legacy
    Romanian format of the first app version ({camp: {"sfarsit", "inceput"}})."""
    v = {LEGACY_KEYS.get(k, k): val for k, val in (values or {}).items() if not str(k).startswith("_")}
    out = {}
    for k in TEXT_FIELDS:
        x = v.get(k)
        out[k] = (str(x).strip() or None) if x is not None else None
    for k in NUMERIC_FIELDS:
        if k not in v:
            continue
        x = v[k]
        if isinstance(x, dict):
            x = {LEGACY_KEYS.get(a, a): b for a, b in x.items()}
            out[k] = {"end": parse_number(x.get("end")), "start": parse_number(x.get("start"))}
        else:
            out[k] = {"end": parse_number(x), "start": None}
    return out


def gt_values(gt: dict, col="end") -> dict:
    return {k: (gt.get(k) or {}).get(col) if isinstance(gt.get(k), dict) else None for k in NUMERIC_FIELDS}


def evaluate(extracted: dict, gt: dict | None) -> dict:
    checks = indicators.consistency_checks(extracted)
    applicable = [ok for _, ok in checks if ok is not None]
    m = {
        "indicators": indicators.compute(extracted),
        "checks": [{"name": n, "ok": ok} for n, ok in checks],
        "consistency": round(sum(applicable) / len(applicable), 3) if applicable else None,
        "fields_extracted": sum(1 for k in NUMERIC_FIELDS if extracted.get(k) is not None),
    }
    if not gt:
        return m

    end, start = gt_values(gt, "end"), gt_values(gt, "start")
    per = {k: field_status(extracted.get(k), end[k], start[k]) for k in NUMERIC_FIELDS if k in gt}
    cnt = {s: 0 for s in STATUS}
    for s in per.values():
        cnt[s] += 1
    n_pos = sum(1 for k in per if end[k] is not None)            # items present in the document
    n_neg = len(per) - n_pos
    n_pred = sum(1 for k in per if extracted.get(k) is not None)
    tp = cnt["correct"]
    precision = tp / n_pred if n_pred else None
    recall = tp / n_pos if n_pos else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else 0.0

    gt_ind = indicators.compute(end)
    errs = []
    for k, g in gt_ind.items():
        p = m["indicators"].get(k)
        if g not in (None, 0):
            errs.append(1.0 if p is None else min(abs(p - g) / abs(g), 1.0))

    tid_gt = re.sub(r"\D", "", str(gt.get("tax_id") or ""))
    tid_p = re.sub(r"\D", "", str(extracted.get("tax_id") or ""))
    m.update({
        "per_field": per,
        "counts": cnt,
        "accuracy": round(tp / n_pos, 4) if n_pos else None,                      # = strict recall
        "accuracy_tolerant": round((tp + cnt["close"]) / n_pos, 4) if n_pos else None,
        "precision": round(precision, 4) if precision is not None else None,
        "f1": round(f1, 4),
        "hallucination_rate": round(cnt["hallucinated"] / n_neg, 4) if n_neg else None,
        "indicator_error": round(sum(errs) / len(errs), 4) if errs else None,     # MAPE capped at 100%
        "true_indicators": gt_ind,
        "tax_id_correct": (tid_gt == tid_p) if tid_gt else None,
    })
    return m

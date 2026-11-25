"""Command-line benchmark (no user interface) + export for the paper.

Examples (from the project folder, with Ollama running):
  python -m scripts.benchmark --list
  python -m scripts.benchmark --models ollama/qwen2.5vl:3b ollama/gemma3n:e2b --pipelines vlm_page hybrid --rep 3
  python -m scripts.benchmark --all-models --pipelines ocr_rules ocr_embeddings ocr_llm ocr_llm_rowpick
  python -m scripts.benchmark --export-only

The current Settings (prompt example, constrained output, image size, ...) are used.
Results go into the same database as the interface, and these files are written to results/:
  runs.csv      — every run (for your own statistical analysis)
  summary.csv   — mean ± std per model × pipeline × device × configuration
  summary.md    — Markdown table ready to paste into the paper
"""
import argparse
import time
from pathlib import Path

from app import db, extract, jobs, report, runtimes

OUT = Path(__file__).resolve().parent.parent / "results"


def fmt(x, kind):
    if x is None:
        return "—"
    return {"pct": f"{x * 100:.1f}%", "s": f"{x:.1f}", "f": f"{x:.3f}"}[kind]


def write_outputs():
    OUT.mkdir(exist_ok=True)
    (OUT / "runs.csv").write_text(report.runs_csv(), encoding="utf-8")
    (OUT / "summary.csv").write_text(report.summary_csv(), encoding="utf-8")
    lines = ["| Model | Pipeline | Config | Device | n | Accuracy | F1 | Hallucinations | Indicator error | Valid JSON | "
             "Time/doc (s) | Tok/s | Memory (GB) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in report.comparison():
        acc = fmt(r["accuracy"], "pct") + (f" ± {r['accuracy_std'] * 100:.1f}" if r["accuracy_std"] else "")
        t = fmt(r["total_time"], "s") + (f" ± {r['total_time_std']:.1f}" if r["total_time_std"] else "")
        mem = f"{r['memory_mb'] / 1024:.1f}" if r["memory_mb"] else "—"
        lines.append(f"| {r['model']} | {r['pipeline']} | {r['config'] or '—'} | {r['device']} | {r['n_runs']} | {acc} | "
                     f"{fmt(r['f1'], 'f')} | {fmt(r['hallucination_rate'], 'pct')} | {fmt(r['indicator_error'], 'pct')} | "
                     f"{fmt(r['json_valid'], 'pct')} | {t} | {fmt(r['tokens_per_sec'], 's')} | {mem} |")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWritten to {OUT}/ : runs.csv, summary.csv, summary.md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list the local models found")
    ap.add_argument("--models", nargs="*", default=[])
    ap.add_argument("--all-models", action="store_true", help="every local model found")
    ap.add_argument("--pipelines", nargs="*", default=["vlm_page"], choices=list(extract.PIPELINES))
    ap.add_argument("--docs", nargs="*", type=int, help="document ids (default: all with ground truth)")
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--export-only", action="store_true")
    a = ap.parse_args()

    db.init()
    settings = db.get_settings()
    known = runtimes.list_models(settings)
    if a.list:
        for x in known["models"]:
            print(f"{x['id']:45} vision={x['vision']} embedding={x.get('embedding')}  "
                  f"{x['parameters'] or ''} {x['quantization'] or ''} {x['size_gb'] or ''} GB")
        for k, v in known["errors"].items():
            print(f"[{k} unavailable] {v}")
        return
    if a.export_only:
        write_outputs()
        return

    models = list(a.models) + ([x["id"] for x in known["models"]] if a.all_models else [])
    emb = {x["id"] for x in known["models"] if x.get("embedding")}
    novis = {x["id"] for x in known["models"] if x["vision"] is False}
    docs = a.docs or [d["id"] for d in db.q("SELECT id FROM documents WHERE ground_truth IS NOT NULL")]
    if not docs:
        raise SystemExit("No documents with ground truth. Run first: python -m scripts.seed_examples")

    plan = []
    for p in a.pipelines:
        if p in extract.NO_MODEL:
            plan += [(None, p, d, 1) for d in docs]
            continue
        for m in models:
            if jobs.compatible(m, p, novis, emb):
                plan += [(m, p, d, r) for d in docs for r in range(1, a.rep + 1)]
    plan.sort(key=lambda t: (t[0] or "", t[1]))
    print(f"{len(plan)} runs planned on '{settings['device']}'\n")

    prev = None
    for i, (m, p, d, r) in enumerate(plan, 1):
        if prev and prev != m:
            runtimes.unload(settings, prev)
        prev = m or prev
        t0 = time.time()
        try:
            rid = jobs.run_one(settings, d, m, p, r)
            met = db.q1("SELECT metrics FROM runs WHERE id=?", (rid,))["metrics"]
            print(f"[{i}/{len(plan)}] {m or 'ocr+rules'} · {p} · doc {d} · rep {r}: "
                  f"accuracy {fmt(met.get('accuracy'), 'pct')}, F1 {fmt(met.get('f1'), 'f')} ({time.time() - t0:.1f} s)")
        except Exception as e:
            print(f"[{i}/{len(plan)}] {m} · {p} · doc {d}: ERROR {e}")
    if prev:
        runtimes.unload(settings, prev)
    print()
    write_outputs()


if __name__ == "__main__":
    main()

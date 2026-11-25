"""Loads the example statements in examples/ together with their ground truth.
Run from the project folder:  python -m scripts.seed_examples
"""
import json
from pathlib import Path

from app import db, documents, jobs, metrics

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
COMPANY = ("Agentia Nationala de Administrare Fiscala (ANAF)", "16031712")


def company_id(name, tax_id):
    company = db.q1("SELECT id FROM companies WHERE name=?", (name,))
    return company["id"] if company else db.ex("INSERT INTO companies(name, tax_id) VALUES(?,?)", (name, tax_id))


def main():
    db.init()
    for pdf in sorted(EXAMPLES.glob("*.pdf")):
        if db.q1("SELECT id FROM documents WHERE filename=?", (pdf.name,)):
            print(f"Already loaded: {pdf.name}")
            continue
        gt_file = pdf.with_suffix(".ground_truth.json")
        raw = json.loads(gt_file.read_text(encoding="utf-8")) if gt_file.exists() else {}
        # each ground-truth file may name its own company; the ANAF examples use the default
        cid = company_id(raw["_company"], raw.get("tax_id")) if raw.get("_company") else company_id(*COMPANY)
        did = db.ex("INSERT INTO documents(company_id, filename) VALUES(?,?)", (cid, pdf.name))
        info = documents.store_upload(did, pdf.name, pdf.read_bytes())
        db.ex("UPDATE documents SET kind=?, pages=?, has_text=? WHERE id=?",
              (info["kind"], info["pages"], info["has_text"], did))
        if raw:
            gt = metrics.normalize_ground_truth(raw)
            db.ex("UPDATE documents SET ground_truth=? WHERE id=?", (gt, did))
            jobs.rescore_document(did)
        print(f"Loaded document #{did}: {pdf.name} ({info['pages']} pages{', with ground truth' if gt_file.exists() else ''})")


if __name__ == "__main__":
    main()

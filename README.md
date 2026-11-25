# FinAI C

A **local, offline** web application for:

1. **tracking income and expenses** — web forms with drop-down menus, date pickers and numeric fields;
2. **automatically extracting key figures from financial statements** (scanned PDFs or images) with models that run on your own computer;
3. **comparing those models** — the same documents go through several models and pipelines, and the app measures accuracy, hallucinations, time and memory, so you can see which model fits which task.

Nothing is sent to the internet and no API keys are needed. The database is a single SQLite file in `data/`.

```
PDF / image ──► PNG pages ──┬──► VLM (Ollama / llama.cpp / LM Studio) ───────────────────┐
                            ├──► image + OCR text ──► VLM (hybrid) ──────────────────────┤
                            ├──► AI OCR (GLM-OCR) ──► table ──► rules ───────────────────┤
                            └──► Tesseract OCR ──► table ──┬──► rules (no language model)├──► amounts ──► indicators
                                                           ├──► embeddings (EmbeddingGemma)│
                                                           ├──► text LLM copies amounts  │
                                                           └──► text LLM picks rows ─────┘
                                                                          │
                                            ground truth ──► metrics ──► comparison / CSV
```

---

## 1. Installation (once)

**Python 3.10+**, then double-click **`start.bat`** (Windows). The first start creates the Python environment,
installs the libraries, loads the 5 example statements with their ground truth and opens http://localhost:8006.

Manual alternative:

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.seed_examples
uvicorn app.main:app --port 8006
```

**Tesseract OCR** (for the OCR pipelines and the baseline):

| System | How |
|---|---|
| Windows | the "UB Mannheim" installer (github.com/UB-Mannheim/tesseract/wiki). Optionally tick **Romanian**. The app finds it in `C:\Program Files\Tesseract-OCR` without editing PATH. |
| macOS | `brew install tesseract tesseract-lang` |
| Ubuntu | `sudo apt install tesseract-ocr tesseract-ocr-ron` |

**Ollama** (local model server): install it from ollama.com, then pull the models. Downloading needs the internet once;
everything else works offline.

## 2. Models used in the study

| Model | Command | Role |
|---|---|---|
| Qwen2.5-VL 3B | `ollama pull qwen2.5vl:3b` | vision-language model (Alibaba family) |
| Gemma 3n E2B | `ollama pull gemma3n:e2b` | the same model as on the phone (Google AI Edge Gallery) → laptop vs. phone |
| EmbeddingGemma | `ollama pull embeddinggemma` | semantic row matching (`ocr_embeddings`) |
| GLM-OCR (optional) | `ollama pull glm-ocr` | OCR specialist, AI alternative to Tesseract (`vlm_ocr_rules`) |
| Bonsai 8B (1-bit) | llama.cpp, see below | text-only 1-bit model, runs on CPU |

**Bonsai on the laptop (no GPU needed):**
1. Download the Windows **CPU x64** build of llama.cpp from the PrismML releases (github.com/PrismML-Eng/llama.cpp → Releases)
   and `Bonsai-8B.gguf` from Hugging Face (`prism-ml/Bonsai-8B-gguf`).
2. Start the server: `.\llama-server.exe -m Bonsai-8B.gguf -c 8192 --port 8090`
3. In the app → Settings → OpenAI-compatible server: `http://127.0.0.1:8090/v1` (the default).
4. The model appears with the `openai/` prefix. Run it only with the text pipelines (`ocr_llm`, `ocr_llm_rowpick`).

**On the phone:** open **Phone results**, choose what the model receives, copy the prompt (it already contains the
statement table read by OCR), paste it into the phone model in airplane mode, then paste the answer back. It is scored
with the same metrics and shown in the same comparison, labelled with the device.

## 3. Workflow

1. **Financial statements** — upload documents; for each, fill in the **ground truth** once (or import a JSON file).
2. **Settings** — choose the prompting strategy (zero-/one-shot, constrained output) and the device name.
3. **Run models** — tick documents, models and pipelines, choose repetitions, start. Models run one at a time and are
   unloaded from memory before the next one.
4. **Model comparison** — ranking, per-field accuracy, error types, accuracy vs. time; export the CSV for the paper.
5. **Charts & tables** — computed live from the database (press ↻ Refresh after new runs):
   - *All models together*: models × a chosen dimension (method, document, field, prompt, device) for any metric;
   - *Each model on its own*: every configuration of the model with all metrics;
   - charts: F1 ranking, accuracy vs. speed, hallucinations, standard vs. long documents, laptop vs. phone,
     zero- vs. one-shot, method × document and method × field heatmaps, reproducibility across repetitions.
   Every chart exports to PNG and every table to CSV.
6. In a document, **"Use in dashboard"** on the best run makes its values the official figures of the company.
7. **Income & expenses** — manual transactions; the dashboard sums them by month and category.

Command-line alternative (useful for long overnight runs):

```bash
python -m scripts.benchmark --list
python -m scripts.benchmark --models ollama/qwen2.5vl:3b ollama/gemma3n:e2b --pipelines vlm_page hybrid --rep 3
python -m scripts.benchmark --all-models --pipelines ocr_rules ocr_embeddings ocr_llm ocr_llm_rowpick
python -m scripts.benchmark --export-only      # results/summary.md, summary.csv, runs.csv
```

## 4. Pipelines

| Code | What it does |
|---|---|
| `vlm_page` | each page image → VLM, results merged |
| `vlm_document` | all pages in one call (tests long / multi-image context) |
| `hybrid` | page image + OCR text as help → VLM |
| `ocr_llm` | Tesseract → reconstructed table (item / start / end) → text LLM **copies the amounts** into JSON |
| `ocr_llm_rowpick` | Tesseract → **numbered** table → text LLM only answers **row numbers**; the app takes the exact amount from the chosen row, so the model cannot alter digits |
| `ocr_rules` | Tesseract + fuzzy label matching, **no language model** — the deterministic baseline |
| `ocr_embeddings` | Tesseract + an **embedding** model matching rows by meaning; the similarity threshold is a setting |
| `vlm_ocr_rules` | a vision model used **only as OCR** (GLM-OCR gets its own `Table Recognition:` command), then the same rules |

The OCR table is rebuilt from word positions: each amount is assigned to the start- or end-of-period column by its
horizontal position, labels spread over several lines are joined, account formulas such as `(ct.401+403…)` are removed
and rows on "sold debitor" (debit balance, i.e. a loss) become negative.

### Prompting strategies (Settings)

| Setting | Effect |
|---|---|
| Example answer: **zero-shot / one-shot** | one-shot adds an example JSON (invented figures for another document) |
| **Constrained output** | the server's grammar only allows digits, `.`, `,` and `-` in amounts, so a model cannot write a row name instead of a number (Ollama `format` / llama.cpp `response_format` with a JSON-schema `pattern`; not available on the phone). If a server rejects the schema, the run falls back to free output and the raw output says so. |
| Thinking | for reasoning models (e.g. qwen3-vl) |

All settings are stored with each run; runs with different settings are kept apart in the comparison.

## 5. Metrics

| Metric | Definition |
|---|---|
| **Accuracy** | fields extracted exactly (±1 unit) / fields present in the document |
| Accuracy ±1% | same, with a 1% tolerance |
| **Precision** | exact fields / fields for which the model returned a value |
| **F1** | harmonic mean of precision and accuracy; the ranking is sorted by it |
| **Hallucinations** | items that do NOT exist in the document (e.g. revenue on a public-institution form) for which a value was invented |
| Indicator error | mean relative error of the financial ratios computed from the extracted values vs. from the ground truth |
| Consistency | share of accounting identities respected (total assets = fixed + current assets, …); needs no ground truth |
| Valid JSON | share of answers that were clean JSON |
| Time, load, tok/s, memory | reported by Ollama / llama.cpp for each call |

Every wrong field also gets an **error type**: wrong column (start-of-period value), scale error (×10ⁿ, separator
misread), wrong sign, missing, hallucinated, close (≤ 1%), wrong.

## 6. Example documents

`examples/` contains 9 financial statements, each with its ground truth (`*.ground_truth.json`), transcribed by hand
and checked arithmetically. `scripts/seed_examples.py` loads them at every start (each under its own company).

| Document | Pages | Type | Particularity |
|---|---|---|---|
| ANAF 2013 | 3 | public institution, scanned | loss (negative result) |
| ANAF 2014 | 3 | public institution, scanned | profit, but a loss at the start of the year (column trap) |
| ANAF 2021 | 3 | public institution, digital | negative equity, loss in both columns |
| ANAF 2024 | 2 | public institution, digital | new form (FXB-SFC-002), decimals |
| ANAF 2026-06 | 2 | public institution, scanned | new form, decimals |
| Petal Q1 2025 | 11 | company (F10/F20), digital | quarterly report, loss, revenue present |
| Restart Energy One 2024 | 23 | company (F10/F20/F30/F40), digital | annual statements, loss of 20.5 million |
| Albapam S1 2025 | 17 | small company (short F10/F20), digital | abbreviated forms, loss |
| Palatul National al Copiilor 06-2026 | 18 | public institution, **scanned** | balance sheet among cash-flow and trial-balance annexes |

Fields that have no row in a form (e.g. revenue for public institutions, total assets on the company form) stay
empty in the ground truth, so any value returned for them counts as a hallucination.

## 7. Project structure

```
app/
  main.py        API (FastAPI) + serves the interface
  extract.py     prompts, pipelines, answer parsing, OCR table reconstruction, rules, embeddings, row picking
  runtimes.py    clients for Ollama and OpenAI-compatible local servers
  documents.py   PDF → PNG (PyMuPDF), OCR (Tesseract + grid-line removal with OpenCV)
  metrics.py     comparison with the ground truth + error typology
  report.py      mean ± std aggregation, CSV export
  indicators.py  financial ratios + accounting consistency checks
  numbers.py     "1.689.799,07" → 1689799.07
  schema.py      extracted fields, their labels, JSON schemas
  db.py          SQLite
static/          interface (plain HTML/CSS/JS, no CDN, works offline); charts.js = Charts & tables page
scripts/         seed_examples.py, benchmark.py
examples/        the 9 test statements + ground truth
start.bat        one-click start on Windows (port 8006)
```

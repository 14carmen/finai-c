"""Fields extracted from financial statements, with the labels under which they appear.

The same list drives the prompt, the JSON schema sent to the models, the rule-based baseline
(OCR + fuzzy label matching), the embedding matcher and the metrics.
Synonyms are mostly Romanian because the test documents are Romanian statements; English
synonyms are included so English-language statements also work.
"""

# key -> (human label, labels that may appear in the document)
NUMERIC_FIELDS = {
    "fixed_assets": ("Non-current (fixed) assets", [
        "total active necurente", "active imobilizate - total", "active imobilizate", "total active imobilizate",
        "total non-current assets", "fixed assets"]),
    "current_assets": ("Current assets", [
        "total active curente", "active circulante - total", "active circulante", "total active circulante",
        "total current assets"]),
    "inventories": ("Inventories", ["stocuri", "inventories"]),
    "receivables": ("Receivables (total current)", [
        "total creante curente", "total creante", "creante", "creanțe", "receivables"]),
    "cash": ("Cash and cash equivalents", [
        "total disponibilitati si alte valori", "total disponibilitati", "disponibilitati", "disponibilități",
        "casa si conturi la banci", "casa și conturi la bănci", "cash and cash equivalents"]),
    "total_assets": ("Total assets", ["total active", "total activ", "active totale", "total assets"]),
    "current_liabilities": ("Current liabilities (due within one year)", [
        "total datorii curente", "datorii ce trebuie platite intr-o perioada de pana la un an",
        "datorii: sumele care trebuie platite intr-o perioada de pana la un an", "total current liabilities"]),
    "non_current_liabilities": ("Non-current liabilities (due after one year)", [
        "total datorii necurente", "datorii ce trebuie platite intr-o perioada mai mare de un an",
        "datorii: sumele care trebuie platite intr-o perioada mai mare de un an", "total non-current liabilities"]),
    "total_liabilities": ("Total liabilities", ["total datorii", "datorii totale", "total liabilities"]),
    "equity": ("Total equity", [
        "total capitaluri proprii", "capitaluri proprii - total", "capitaluri proprii", "capital propriu",
        "total equity"]),
    "revenue": ("Net turnover (revenue)", ["cifra de afaceri neta", "cifra de afaceri", "net turnover", "revenue"]),
    "total_income": ("Total income", ["venituri totale", "total venituri", "total income"]),
    "total_expenses": ("Total expenses", ["cheltuieli totale", "total cheltuieli", "total expenses"]),
    "net_result": ("Net profit / loss for the period", [
        "rezultatul patrimonial al exercitiului", "rezultatul exercitiului", "profitul sau pierderea neta",
        "rezultatul net al exercitiului", "profit net", "pierdere neta", "net profit", "net result"]),
}

TEXT_FIELDS = {
    "entity": "Name of the reporting entity",
    "tax_id": "Tax identification number (CUI / CIF)",
    "period": "Reporting period",
}

ALL_FIELDS = list(TEXT_FIELDS) + list(NUMERIC_FIELDS)

# Field names used by the first (Romanian) version of the app, so old ground-truth files still import.
LEGACY_KEYS = {
    "entitate": "entity", "cui": "tax_id", "perioada": "period",
    "active_imobilizate": "fixed_assets", "active_circulante": "current_assets", "stocuri": "inventories",
    "creante": "receivables", "disponibilitati": "cash", "active_totale": "total_assets",
    "datorii_curente": "current_liabilities", "datorii_necurente": "non_current_liabilities",
    "datorii_totale": "total_liabilities", "capital_propriu": "equity", "cifra_afaceri": "revenue",
    "venituri_totale": "total_income", "cheltuieli_totale": "total_expenses", "rezultat_net": "net_result",
    "sfarsit": "end", "inceput": "start",
}

AMOUNT_PATTERN = r"^-?[0-9][0-9.,]*$"


def json_schema(constrained: bool = False) -> dict:
    """JSON schema for structured output (Ollama `format`, llama.cpp / LM Studio `response_format`).
    Amounts are requested as TEXT, exactly as written; the app converts them.
    constrained=True: amounts may only contain digits, '.', ',' and a leading '-', so the decoder
    cannot physically write a row name or a sentence instead of an amount."""
    props = {k: {"type": ["string", "null"]} for k in TEXT_FIELDS}
    for k in NUMERIC_FIELDS:
        props[k] = ({"anyOf": [{"type": "string", "pattern": AMOUNT_PATTERN}, {"type": "null"}]}
                    if constrained else {"type": ["string", "null"]})
    return {"type": "object", "properties": props, "required": ALL_FIELDS}


def row_pick_schema() -> dict:
    """Schema for the row-selection strategy: each field is a row number (integer) or null."""
    props = {k: {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]} for k in NUMERIC_FIELDS}
    return {"type": "object", "properties": props, "required": list(NUMERIC_FIELDS)}

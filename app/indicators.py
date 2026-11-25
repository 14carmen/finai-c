"""Financial indicators computed from the extracted values, plus accounting consistency checks."""


def _div(a, b, pct=False):
    if a is None or b is None or b == 0:
        return None
    r = a / b
    return round(r * 100, 2) if pct else round(r, 4)


INDICATORS = {
    "current_ratio": "Current ratio (CA / CL)",
    "quick_ratio": "Quick ratio ((CA − inventories) / CL)",
    "solvency_ratio": "Solvency ratio (TA / TL)",
    "debt_to_equity_pct": "Debt to equity (TL / E, %)",
    "equity_ratio_pct": "Equity ratio (E / TA, %)",
    "asset_turnover": "Asset turnover (revenue / TA)",
    "net_margin_pct": "Net profit margin (NR / revenue, %)",
    "roa_pct": "ROA (NR / TA, %)",
    "roe_pct": "ROE (NR / E, %)",
}


def compute(v: dict) -> dict:
    g = lambda k: v.get(k)
    ca, cl, inv = g("current_assets"), g("current_liabilities"), g("inventories")
    ta, tl, eq = g("total_assets"), g("total_liabilities"), g("equity")
    rev, nr = g("revenue"), g("net_result")
    return {
        "current_ratio": _div(ca, cl),
        "quick_ratio": _div(None if ca is None or inv is None else ca - inv, cl),
        "solvency_ratio": _div(ta, tl),
        "debt_to_equity_pct": _div(tl, eq, True),
        "equity_ratio_pct": _div(eq, ta, True),
        "asset_turnover": _div(rev, ta),
        "net_margin_pct": _div(nr, rev, True),
        "roa_pct": _div(nr, ta, True),
        "roe_pct": _div(nr, eq, True),
    }


def consistency_checks(v: dict, tol=0.005) -> list:
    """Accounting identities that need NO ground truth: a model that reads the statement correctly
    must respect them. Returns [(name, True/False/None)] (None = not enough values)."""
    def close(a, b, t=tol):
        if a is None or b is None:
            return None
        return abs(a - b) <= max(1.0, t * max(abs(a), abs(b)))

    g = v.get
    s = lambda *ks: None if any(g(k) is None for k in ks) else sum(g(k) for k in ks)
    return [
        ("Total assets = fixed + current assets", close(g("total_assets"), s("fixed_assets", "current_assets"))),
        ("Total liabilities = current + non-current", close(g("total_liabilities"),
                                                             s("current_liabilities", "non_current_liabilities"))),
        ("Equity ≈ total assets − total liabilities", close(g("equity"),
            None if g("total_assets") is None or g("total_liabilities") is None
            else g("total_assets") - g("total_liabilities"), 0.05)),   # companies also have provisions / deferred income
        ("Inventories + receivables + cash ≤ current assets",
            None if s("inventories", "receivables", "cash") is None or g("current_assets") is None
            else s("inventories", "receivables", "cash") <= g("current_assets") * (1 + tol)),
    ]

"""Parsing amounts written in Romanian or English number format."""
import re

_EMPTY = {"", "x", "-", "—", "n/a", "na", "null", "none", "nu este cazul"}


def parse_number(value):
    """'1.689.799,07' -> 1689799.07 ; '-1.651.528.098,80' -> -1651528098.8 ; '(123)' -> -123 ;
    '1,234,567.89' -> 1234567.89. Returns None for missing values ('X', '-', '', null)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    s = s.replace("lei", "").replace("ron", "").replace(" ", " ").strip()
    if s in _EMPTY:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = s.replace(" ", "").replace("'", "")
    if s.startswith(("-", "−", "–")):
        neg, s = True, s[1:]
    if not re.fullmatch(r"[0-9.,]+", s) or not re.search(r"\d", s):
        return None

    dots, commas = s.count("."), s.count(",")
    if dots and commas:
        # the last separator is the decimal one; the others are thousands separators
        last = max(s.rfind(","), s.rfind("."))
        if len(s) - last - 1 == 3:                      # "4,021.050.781" -> all are thousands separators (OCR)
            s = re.sub(r"[.,]", "", s)
        else:
            s = re.sub(r"[.,]", "", s[:last]) + "." + s[last + 1:]
    elif commas:
        tail = s.split(",")[-1]
        if commas == 1 and len(tail) != 3:
            s = s.replace(",", ".")          # 123,45 -> decimal
        else:
            s = s.replace(",", "")           # 1,234,567 -> thousands
    elif dots:
        tail = s.split(".")[-1]
        if dots > 1 or len(tail) == 3:
            s = s.replace(".", "")           # 1.234.567 / 1.250 -> thousands (Romanian convention)
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def fmt_ro(n, decimals=2):
    """Format an amount the way Romanian documents write it (1.234.567,89)."""
    if n is None:
        return ""
    s = f"{abs(n):,.{decimals}f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return ("-" if n < 0 else "") + s

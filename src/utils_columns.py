# src/utils_columns.py
import re
from typing import List
import pandas as pd

_UNNAMED_RE = re.compile(r"^\s*(unnamed|nan|null|none)\b", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"^col_\d+$", re.IGNORECASE)

def normalize_columns(df: pd.DataFrame, *, max_len: int = 63) -> pd.DataFrame:
    """
    Normalize dataframe columns so they are:
    - non-empty
    - snake_case
    - unique
    - safe identifiers (no leading digits)
    - placeholder columns are gapless: col_0, col_1, col_2...

    Also treats existing col_N names as placeholders and re-numbers them sequentially
    so you never end up with col_1..col_5 but missing col_0.
    """
    out = df.copy()

    seen: dict[str, int] = {}
    placeholder_i = 0
    cols_out: List[str] = []

    for c in list(out.columns):
        raw = "" if c is None else str(c)
        raw = raw.replace("\n", " ").replace("\r", " ").strip()
        raw = re.sub(r"\s+", " ", raw)
        low = raw.lower()

        is_missing = (not raw) or bool(_UNNAMED_RE.match(low))
        is_placeholder = (low in {"col", "column"}) or bool(_PLACEHOLDER_RE.fullmatch(low))

        if is_missing or is_placeholder:
            name = f"col_{placeholder_i}"
            placeholder_i += 1
        else:
            name = low
            name = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_")
            if not name:
                name = f"col_{placeholder_i}"
                placeholder_i += 1
            if name[0].isdigit():
                name = f"c_{name}"

        # length cap
        name = name[:max_len].rstrip("_") or f"col_{placeholder_i}"

        # ensure uniqueness
        base = name
        if base in seen:
            seen[base] += 1
            suffix = f"_{seen[base]}"
            name = (base[: max_len - len(suffix)] + suffix) if len(base) + len(suffix) > max_len else (base + suffix)
        else:
            seen[base] = 0

        cols_out.append(name)

    out.columns = cols_out
    return out


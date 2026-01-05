# src/utils_df.py
from __future__ import annotations

import datetime as _dt
import decimal as _dec
from typing import Any

import numpy as np
import pandas as pd


def df_to_records_safe(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Convert a DataFrame to JSON-safe records:
    - NaN/NaT/Inf -> None
    - numpy scalars -> python scalars
    - pandas Timestamp -> ISO string
    - Decimal -> string (preserve precision)
    """
    if df is None:
        return []

    df = df.copy()

    # Replace +/-inf with NaN
    df.replace([np.inf, -np.inf], np.nan, inplace=True)

    # IMPORTANT: allow None in columns (object dtype), then replace all NA-like with None
    df = df.astype(object).mask(pd.isna(df), None)

    records = df.to_dict(orient="records")

    def clean(v: Any) -> Any:
        if v is None or v is pd.NA:
            return None

        # numpy scalars -> python scalars
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, np.bool_):
            return bool(v)
        if isinstance(v, np.floating):
            f = float(v)
            if np.isnan(f) or np.isinf(f):
                return None
            return f

        # timestamps / dates
        if isinstance(v, pd.Timestamp):
            # JSON-safe ISO format
            try:
                return v.isoformat()
            except Exception:
                return str(v)

        if isinstance(v, np.datetime64):
            try:
                return pd.to_datetime(v).isoformat()
            except Exception:
                return str(v)

        if isinstance(v, (_dt.datetime, _dt.date)):
            try:
                return v.isoformat()
            except Exception:
                return str(v)

        # decimals
        if isinstance(v, _dec.Decimal):
            return str(v)

        # containers
        if isinstance(v, dict):
            return {k: clean(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]

        return v

    return [{k: clean(val) for k, val in r.items()} for r in records]


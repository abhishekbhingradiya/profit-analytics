import math
from datetime import date, datetime

import numpy as np
import pandas as pd


def clean(value):
    """Convert pandas/numpy values into JSON-safe Python primitives."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return records(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def records(df: pd.DataFrame) -> list[dict]:
    return [clean(row) for row in df.to_dict(orient="records")]

"""Safe sampling for preview endpoints.

privacy_mode on -> the raw-row channel is refused and a statistical summary derived
from the cached profile is returned instead (DoD #1-4: no raw rows anywhere).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .models import Dataset, TableProfile


def effective_privacy(ds: Dataset, settings) -> bool:
    if ds.privacy_mode is not None:
        return ds.privacy_mode
    return bool(settings.get_setting("privacy_mode_default", False))


def preview_from_df(df: pd.DataFrame, n: int) -> dict[str, Any]:
    truncated = len(df) > n
    head = df.head(n)
    return {
        "mode": "rows",
        "columns": [str(c) for c in df.columns],
        "rows": head.where(pd.notna(head), None).to_dict("records"),
        "truncated": truncated,
    }


def preview_summary(profile: TableProfile) -> dict[str, Any]:
    """Schema-only view: aggregates never expose individual rows."""
    return {
        "mode": "summary",
        "row_count": profile.row_count,
        "columns": [
            {
                "name": c.name,
                "dtype": c.dtype,
                "null_rate": c.null_rate,
                "cardinality": c.cardinality,
                "num_range": list(c.num_range) if c.num_range else None,
                "is_time": c.is_time,
                "time_range": [c.time_min, c.time_max] if c.is_time else None,
            }
            for c in profile.columns
        ],
    }

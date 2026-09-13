"""Column-level profiling + prompt serialization with a hard token budget.

Backend-process pandas (decision 5): profiling never occupies the kernel pools.
render_profile_for_prompt trims in reverse order sample_values -> top_values ->
ranges until the compact text fits the budget (~4 chars/token heuristic).
"""

from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd

from .models import ColumnProfile, TableProfile

_TIME_PARSE_RATIO = 0.9
_TOP_N = 3
_SAMPLE_N = 3
_TIME_SAMPLE = 200


def _jsonable(v: Any) -> Any:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalar
        try:
            return _jsonable(v.item())
        except (ValueError, TypeError):
            pass
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def profile_column(s: pd.Series, row_count: int) -> ColumnProfile:
    null_rate = float(s.isna().mean()) if row_count else 0.0
    card = int(s.nunique(dropna=True))
    out = ColumnProfile(name=str(s.name), dtype=str(s.dtype), null_rate=round(null_rate, 4),
                        cardinality=card)
    notna = s.dropna()
    if not notna.empty:
        out.sample_values = [_jsonable(v) for v in notna.head(_SAMPLE_N)]

    is_num = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
    is_stringy = pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)
    if is_num and not notna.empty:
        out.num_range = (float(notna.min()), float(notna.max()))
    elif pd.api.types.is_datetime64_any_dtype(s):
        out.is_time = True
        out.time_min = str(notna.min().isoformat())
        out.time_max = str(notna.max().isoformat())
    elif is_stringy:
        # cheap string-time heuristic on a bounded sample; if not time -> category tops
        probe = pd.to_datetime(notna.head(_TIME_SAMPLE), errors="coerce", format="mixed")
        if len(probe) and probe.notna().mean() > _TIME_PARSE_RATIO:
            out.is_time = True
            out.time_min = str(probe.min().isoformat())
            out.time_max = str(probe.max().isoformat())
        else:
            out.top_values = [_jsonable(v) for v in notna.value_counts().head(_TOP_N).index]
    out.pk_hint = bool(row_count and card == row_count and null_rate == 0.0)
    return out


def profile_dataframe(
    df: pd.DataFrame, dataset_id: str, revision: str, row_count: int
) -> TableProfile:
    cols = [profile_column(df[c], row_count) for c in df.columns]
    return TableProfile(dataset_id=dataset_id, revision=revision, row_count=row_count, columns=cols)


# -- prompt serialization (pure function, budget-trimmed) ----------------------


def _render_one(c: ColumnProfile, level: int) -> str:
    parts = [f"{c.name}({c.dtype}", f"null={c.null_rate:.0%}", f"card={c.cardinality}"]
    if level < 3:
        if c.num_range:
            parts.append(f"range={c.num_range[0]:g}..{c.num_range[1]:g}")
        if c.is_time and c.time_min:
            parts.append(f"time={c.time_min[:10]}..{c.time_max[:10] if c.time_max else ''}")
    if level < 2 and c.top_values:
        parts.append("top=" + "|".join(str(v) for v in c.top_values))
    if level < 1 and c.sample_values and c.is_time is False:
        parts.append("samples=" + "|".join(str(v) for v in c.sample_values))
    if c.pk_hint:
        parts.append("pk?")
    return " ".join(parts) + "; "


def est_tokens(text: str) -> int:
    """Cheap deterministic estimate: 4 chars/token."""
    return math.ceil(len(text) / 4)


def render_profile_for_prompt(
    profiles: TableProfile | list[TableProfile],
    budget_tokens: int = 500,
    privacy: bool = False,
) -> str:
    """Per-table budget enforcement. privacy=True strips raw-ish values outright
    (sample_values already cleared at profile time, top_values suppressed here)."""
    plist = [profiles] if isinstance(profiles, TableProfile) else list(profiles)
    for lvl in range(2 if privacy else 0, 4):
        body = "".join(
            f"[{p.dataset_id} rows={p.row_count}] "
            + "".join(_render_one(c, lvl) for c in p.columns)
            + "\n"
            for p in plist
        )
        if est_tokens(body) <= budget_tokens:
            return body
    # last resort: keep only name+dtype
    return json.dumps(
        {f"t{i}": [[c.name, c.dtype] for c in p.columns] for i, p in enumerate(plist)},
        ensure_ascii=False,
    )



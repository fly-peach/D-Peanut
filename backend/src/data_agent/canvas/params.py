"""params ⇄ PARAM_SPEC consistency validation (shared by REST PUT and N3 tools)."""

from __future__ import annotations

from typing import Any

from .models import ParamField

_TYPE_OF = {
    "int": (int,),
    "float": (int, float),
    "str": (str,),
    "bool": (bool,),
    "date": (str,),
    "select": (str, int, float),
    "multiselect": (list,),
    "column_ref": (str,),
}


def validate_params(spec: list[ParamField], params: dict[str, Any]) -> list[str]:
    """Empty list = valid. Missing keys are filled from defaults by the caller."""
    errors: list[str] = []
    by_key = {f.key: f for f in spec}
    for k in params:
        if k not in by_key:
            errors.append(f"unknown param {k!r} (not in PARAM_SPEC)")
    for f in by_key.values():
        if f.key not in params:
            errors.append(f"missing param {f.key!r}")
            continue
        v = params[f.key]
        types = _TYPE_OF.get(f.type, (str,))
        if v is None and f.type != "bool":
            continue
        if isinstance(v, bool) and f.type in ("int", "float"):
            errors.append(f"param {f.key!r}: bool given for {f.type}")
            continue
        if not isinstance(v, tuple(types)):
            errors.append(f"param {f.key!r}: expected {f.type}, got {type(v).__name__}")
            continue
        if f.type in ("int", "float"):
            if f.min is not None and v < f.min:
                errors.append(f"param {f.key!r}: {v} < min {f.min}")
            if f.max is not None and v > f.max:
                errors.append(f"param {f.key!r}: {v} > max {f.max}")
        if f.options and f.type in ("select", "multiselect"):
            vals = v if isinstance(v, list) else [v]
            bad = [x for x in vals if x not in f.options]
            if bad:
                errors.append(f"param {f.key!r}: values not in options: {bad}")
    return errors


def merge_defaults(spec: list[ParamField], params: dict[str, Any]) -> dict[str, Any]:
    out = {f.key: f.default for f in spec if f.default is not None}
    out.update(params)
    return out

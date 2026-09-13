"""Static checks for processor source before it ever reaches a kernel."""

from __future__ import annotations

import ast
from typing import Any

REQUIRED_EXPORTS = ("PARAM_SPEC", "DEFAULTS")


def check_processor_source(source: str) -> list[str]:
    """Return list of problems; empty = acceptable. Syntax-safe by construction."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"syntax error: {e.msg} (line {e.lineno})"]
    top_assigns: set[str] = set()
    top_defs: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    top_assigns.add(t.id)
        elif isinstance(node, ast.FunctionDef):
            top_defs.add(node.name)
    problems = []
    for exp in REQUIRED_EXPORTS:
        if exp not in top_assigns:
            problems.append(f"missing top-level export {exp}")
    if "process" not in top_defs:
        problems.append("missing top-level def process(ctx)")
    return problems


def extract_literals(source: str) -> tuple[list[dict], dict]:
    """Best-effort host-side read of PARAM_SPEC / DEFAULTS (must be literals —
    the processor template mandates it; non-literal falls back to empty)."""
    out: dict[str, Any] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        for t in targets:
            if isinstance(t, ast.Name) and t.id in REQUIRED_EXPORTS:
                try:
                    out[t.id] = ast.literal_eval(value)
                except (ValueError, TypeError):
                    out[t.id] = None
    spec = out.get("PARAM_SPEC")
    defaults = out.get("DEFAULTS")
    return (spec if isinstance(spec, list) else [], defaults if isinstance(defaults, dict) else {})

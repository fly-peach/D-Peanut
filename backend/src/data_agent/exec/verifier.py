"""AST whitelist verifier (TW pattern) — pure function, shared by run_in_kernel
(N3 AI trial) and any future in-kernel execution. No imports of kernels/services.

Verdict: safe -> execute; blocked -> approval flow (reason lists the hits).
Policy lives here as data; keep in sync with prompts §安全边界.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

ALLOWED_IMPORTS = {
    "pandas", "numpy", "duckdb", "math", "statistics", "datetime", "dateutil",
    "json", "re", "collections", "itertools", "functools", "random", "string",
    "textwrap", "unicodedata", "csv", "io", "os.path", "pathlib", "typing",
    "dataclasses", "enum", "abc", "copy", "decimal", "fractions", "heapq",
    "bisect", "operator", "pprint", "time",  # time: sleep only for pacing? keep allowed, cheap
    "traceback", "warnings", "contextlib", "numbers", "array", "base64", "hashlib",
    "matplotlib", "matplotlib.pyplot",
    "data_agent.schemas.chart",  # processor contract types are importable in kernel
    "data_agent.catalog.reader", "data_agent.catalog.models",  # replay shim already imports these
}

# module.root -> blocked if used
BLOCKED_MODULES = {
    "socket", "requests", "urllib", "http", "httpx", "aiohttp", "ftplib", "telnetlib",
    "smtplib", "subprocess", "multiprocessing", "threading", "asyncio",  # event loops evade timeout
    "shutil", "tempfile", "ctypes", "ssl", "queue", "signal", "sched",
    "importlib", "py_compile", "compileall", "zipfile", "tarfile", "sqlite3",  # duckdb covers sql
    "sys", "builtins", "resource", "platform", "webbrowser", "pickle", "marshal", "shelve",
    "pty", "fcntl", "pwd", "grp", "termios", "tty", "posix", "nt", "winreg", "wmi",
}

BLOCKED_BUILTINS = {"open", "eval", "exec", "compile", "__import__", "globals", "locals", "vars"}

# os.* special: os.path allowed, everything else blocked
WRITE_OPEN_MODES = {"w", "a", "x", "w+", "r+", "a+", "x+"}


@dataclass(frozen=True)
class Verdict:
    safe: bool
    reason: str = ""
    hits: tuple[str, ...] = field(default_factory=tuple)


def _root(name: str) -> str:
    return name.split(".")[0]


def _dotted(node: ast.Attribute) -> str:
    parts: list[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    else:
        return ""
    return ".".join(reversed(parts))


def verify_code(code: str) -> Verdict:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return Verdict(False, f"syntax error: {e.msg}", (f"line {e.lineno}",))

    hits: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _root(alias.name)
                if root in BLOCKED_MODULES:
                    hits.append(f"import {alias.name}")
                elif alias.name not in ALLOWED_IMPORTS and root not in {
                        _root(a) for a in ALLOWED_IMPORTS}:
                    hits.append(f"import {alias.name} (not in whitelist)")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = _root(mod)
            if root in BLOCKED_MODULES:
                hits.append(f"from {mod} import ...")
            elif mod and mod not in ALLOWED_IMPORTS \
                    and root not in {_root(a) for a in ALLOWED_IMPORTS}:
                hits.append(f"from {mod} import ... (not in whitelist)")
            if mod == "os":
                for alias in node.names:
                    if alias.name != "path":
                        hits.append(f"from os import {alias.name}")
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted.startswith("os.") and not dotted.startswith("os.path"):
                hits.append(dotted)
            elif dotted in {"sys.path", "sys.version"} or dotted.startswith(("sys.", "builtins.")):
                hits.append(dotted)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in BLOCKED_BUILTINS:
                m0 = (node.args[1].value if len(node.args) >= 2
                      and isinstance(node.args[1], ast.Constant) else None)
                if fn.id == "open" and isinstance(m0, str) and m0 not in {"r", ""} \
                        and "b" not in m0:
                    hits.append("open(... write mode)")
                elif fn.id == "open" and any(
                        kw.arg == "mode" and isinstance(kw.value, ast.Constant)
                        and str(kw.value.value) not in {"r", ""} for kw in node.keywords):
                    hits.append("open(... write mode)")
                elif fn.id == "open":
                    hits.append("open(...) (file access needs approval)")
                else:
                    hits.append(f"{fn.id}()")
            elif isinstance(fn, ast.Attribute) and _dotted(fn).startswith(("open",)):
                hits.append(_dotted(fn))

    if hits:
        uniq = tuple(dict.fromkeys(hits))
        return Verdict(False, "blocked patterns: " + ", ".join(uniq), uniq)
    return Verdict(True)

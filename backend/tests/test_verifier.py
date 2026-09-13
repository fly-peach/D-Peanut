"""AST whitelist verifier — table-driven (N3 task 1.3, >=12 cases)."""

import pytest

from data_agent.exec.verifier import verify_code

SAFE_CASES = [
    ("import pandas as pd\ndf.groupby('c').sum()", "pandas+groupby"),
    ("import duckdb\nduckdb.sql('select 1')", "duckdb"),
    ("import numpy, math, json, re, datetime", "stdlib whitelist"),
    ("from pathlib import Path\nPath('x').exists()", "pathlib"),
    ("import os.path\nos.path.join('a','b')", "os.path ok"),
    ("from data_agent.schemas.chart import RenderData", "processor contract import"),
    ("x = [i*2 for i in range(10)]\nprint(x)", "pure compute+print"),
    ("import matplotlib.pyplot as plt\nplt.plot([1],[2])", "matplotlib"),
]

BLOCKED_CASES = [
    ("import requests", "requests"),
    ("import socket", "socket"),
    ("import subprocess", "subprocess"),
    ("from urllib.request import urlopen", "urllib"),
    ("import shutil\nshutil.rmtree('/x')", "shutil"),
    ("open('/etc/passwd')", "open()"),
    ("open('/data/f.csv','w')", "open write mode"),
    ("eval('1+1')", "eval"),
    ("exec('x=1')", "exec"),
    ("import importlib", "importlib escape"),
    ("__import__('os')", "dunder import"),
    ("import os\nos.system('ls')", "os.system"),
    ("import os\nos.remove('/x')", "os.remove"),
    ("import sqlite3", "raw sqlite"),
    ("import sys\nprint(sys.argv)", "sys"),
    ("syntax error (", "syntax error"),
]


@pytest.mark.parametrize("code,name", SAFE_CASES)
def test_safe(code, name):
    v = verify_code(code)
    assert v.safe, name


@pytest.mark.parametrize("code,name", BLOCKED_CASES)
def test_blocked(code, name):
    v = verify_code(code)
    assert not v.safe and v.hits, name


def test_readonly_open_of_data_is_flagged():
    # open() without an explicit read mode must still require approval (file access)
    assert not verify_code("open('/data/sales.csv')").safe

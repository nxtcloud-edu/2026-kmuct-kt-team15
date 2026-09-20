"""Test environment (SPEC 10).

app/db.py and app/llm.py read .env at import time, so the gateway keys are cleared
here -- before those imports -- to keep any test from reaching the real llm-x.
"""

import os

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ.setdefault("DEMO_TODAY", "2026-03-16")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_llm_keys(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")

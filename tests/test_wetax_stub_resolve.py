"""resolve_stub_submit kwargs / env 우선순위."""
from __future__ import annotations

import os

from src.workflows.wetax_local_tax import resolve_stub_submit


def test_resolve_explicit_true_overrides_env(monkeypatch):
    monkeypatch.delenv("WETAX_STUB_SUBMIT", raising=False)
    assert resolve_stub_submit(True) is True
    monkeypatch.setenv("WETAX_STUB_SUBMIT", "0")
    assert resolve_stub_submit(True) is True


def test_resolve_explicit_false(monkeypatch):
    monkeypatch.setenv("WETAX_STUB_SUBMIT", "1")
    assert resolve_stub_submit(False) is False


def test_resolve_env_true(monkeypatch):
    monkeypatch.setenv("WETAX_STUB_SUBMIT", "1")
    assert resolve_stub_submit(None) is True


def test_resolve_default_false(monkeypatch):
    monkeypatch.delenv("WETAX_STUB_SUBMIT", raising=False)
    assert resolve_stub_submit(None) is False

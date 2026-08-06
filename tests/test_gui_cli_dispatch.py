"""빌드본 병렬 child CLI 디스패치의 실패 코드 회귀 테스트."""
import importlib
import sys
from types import SimpleNamespace

import pytest

import gui_main


def _set_cli_argv(monkeypatch, *rest):
    monkeypatch.setattr(sys, "argv", ["gui_main.py", "--wtax-cli", "fake.module", *rest])


def test_dispatch_accepts_bootstrap_only_and_returns_handled(monkeypatch):
    received = {}

    async def main(args):
        received["bootstrap_only"] = args.bootstrap_only
        received["auto"] = args.auto
        return True

    _set_cli_argv(monkeypatch, "--bootstrap-only")
    monkeypatch.setattr(importlib, "import_module", lambda _name: SimpleNamespace(main=main))

    assert gui_main._dispatch_cli_subprocess() is True
    assert received == {"bootstrap_only": True, "auto": False}


def test_dispatch_turns_false_cli_result_into_nonzero_exit(monkeypatch):
    async def main(_args):
        return False

    _set_cli_argv(monkeypatch, "--bootstrap-only")
    monkeypatch.setattr(importlib, "import_module", lambda _name: SimpleNamespace(main=main))

    with pytest.raises(SystemExit) as exc:
        gui_main._dispatch_cli_subprocess()
    assert exc.value.code == 1


def test_dispatch_turns_cli_exception_into_nonzero_exit(monkeypatch):
    async def main(_args):
        raise RuntimeError("boom")

    _set_cli_argv(monkeypatch, "--auto")
    monkeypatch.setattr(importlib, "import_module", lambda _name: SimpleNamespace(main=main))

    with pytest.raises(SystemExit) as exc:
        gui_main._dispatch_cli_subprocess()
    assert exc.value.code == 1

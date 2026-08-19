"""GUI 런처가 검정 콘솔(WTaxGUI)을 만들지 않는지."""
from pathlib import Path
from types import SimpleNamespace

import gui_main


ROOT = Path(__file__).resolve().parents[1]


def test_run_gui_bat_uses_pythonw_without_titled_console():
    text = (ROOT / "run_gui.bat").read_text(encoding="utf-8")
    commands = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().upper().startswith("REM")
    )
    assert 'start "WTaxGUI"' not in commands
    assert "pythonw" in commands
    assert 'start ""' in commands


def test_hide_owned_console_skips_cli_child():
    assert gui_main._hide_owned_console(argv=["gui_main.py", "--wtax-cli", "x"]) is False


def test_hide_owned_console_skips_inherited_terminal():
    calls = []

    class Kernel:
        def GetConsoleWindow(self):
            return 123
        def GetConsoleProcessList(self, _buf, _n):
            return 2  # parent terminal + this process

    class User:
        def ShowWindow(self, hwnd, cmd):
            calls.append((hwnd, cmd))

    assert gui_main._hide_owned_console(
        _kernel32=Kernel(), _user32=User(), argv=["gui_main.py"],
    ) is False
    assert calls == []


def test_hide_owned_console_hides_exclusive_python_exe_console(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "win32")
    calls = []

    class Kernel:
        def GetConsoleWindow(self):
            return 99
        def GetConsoleProcessList(self, _buf, _n):
            return 1

    class User:
        def ShowWindow(self, hwnd, cmd):
            calls.append((hwnd, cmd))
            return True

    assert gui_main._hide_owned_console(
        _kernel32=Kernel(), _user32=User(), argv=["gui_main.py"],
    ) is True
    assert calls == [(99, 0)]


def test_hide_owned_console_noop_without_console(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "win32")

    class Kernel:
        def GetConsoleWindow(self):
            return 0
        def GetConsoleProcessList(self, _buf, _n):
            raise AssertionError("should not inspect process list")

    assert gui_main._hide_owned_console(
        _kernel32=Kernel(), _user32=SimpleNamespace(), argv=["gui_main.py"],
    ) is False

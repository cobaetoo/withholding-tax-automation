"""병렬 EDI 보조 프로세스 콘솔 창 억제·Chrome 첫 실행 차단 회귀 테스트.

--windowed GUI 에서 taskkill/netstat/tasklist 같은 콘솔 프로그램을
CREATE_NO_WINDOW 없이 호출하면 호출마다 검은 콘솔 창이 깜빡인다('정지' 시 무더기).
신규 병렬 프로필은 Chrome 첫 실행 환영/기본 브라우저 확인 창이 포털 창을 가린다.
실제 프로세스는 띄우지 않고 호출 인자 계약만 검증한다.
"""
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.ui.workers import parallel_cli_worker as worker_mod
from src.utils import chrome_cdp

_NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else None


class _FakeProc:
    pid = 4242


def _hides_console(kwargs):
    return kwargs.get("creationflags") == _NO_WINDOW_FLAGS


def _record_run(monkeypatch, stdout_by_program=None):
    """subprocess.run 호출을 (args, kwargs) 로 기록하는 가짜로 교체한다."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        stdout = (stdout_by_program or {}).get(args[0], "")
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _patch_launch(monkeypatch, popen):
    monkeypatch.setattr(chrome_cdp, "kill_chrome", lambda **_kw: None)
    monkeypatch.setattr(chrome_cdp.time, "sleep", lambda _s: None)
    monkeypatch.setattr(chrome_cdp, "check_cdp_available", lambda **_kw: True)
    monkeypatch.setattr(chrome_cdp, "_launched_pids", {})
    monkeypatch.setattr(subprocess, "Popen", popen)


def test_taskkill_hides_console_and_bounds_wait(monkeypatch):
    calls = _record_run(monkeypatch)

    chrome_cdp._taskkill("/PID", "4321", "/T", "/F")

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["taskkill", "/PID", "4321", "/T", "/F"]
    assert kwargs["timeout"] == 10
    assert _hides_console(kwargs)


def test_taskkill_swallows_timeout(monkeypatch):
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)

    chrome_cdp._taskkill("/F", "/IM", "chrome.exe", "/T")  # 예외가 GUI 스레드로 새지 않음


def test_kill_chrome_by_port_hides_netstat_and_taskkill(monkeypatch):
    netstat = (
        "  TCP    127.0.0.1:9224   0.0.0.0:0   LISTENING   5555\n"
        "  TCP    127.0.0.1:9223   0.0.0.0:0   LISTENING   6666\n"
    )
    calls = _record_run(monkeypatch, {"netstat": netstat})

    assert chrome_cdp.kill_chrome_by_port(9224) == [5555]

    assert [args for args, _kw in calls] == [
        ["netstat", "-ano"],
        ["taskkill", "/PID", "5555", "/T", "/F"],
    ]
    assert all(_hides_console(kwargs) for _args, kwargs in calls)
    assert calls[1][1]["timeout"] == 10


def test_kill_chrome_pid_checks_and_kills_without_console(monkeypatch):
    tasklist = '"chrome.exe","7777","Console","1","120,000 K"'
    calls = _record_run(monkeypatch, {"tasklist": tasklist})

    chrome_cdp.kill_chrome(pid=7777)

    assert [args[0] for args, _kw in calls] == ["tasklist", "taskkill"]
    assert all(_hides_console(kwargs) for _args, kwargs in calls)


def test_attempt_launch_blocks_first_run_prompts(monkeypatch):
    launched = []

    def fake_popen(args, **kwargs):
        launched.append(args)
        return _FakeProc()

    _patch_launch(monkeypatch, fake_popen)

    result = chrome_cdp._attempt_launch(
        "chrome.exe", "profile-dir", "Default", "https://edi.nhis.or.kr/",
        port=9555, kill_wait=0,
    )

    assert result == {"success": True, "pid": 4242}
    args = launched[0]
    assert "--no-first-run" in args
    assert "--no-default-browser-check" in args
    # NHIS 보안프로그램의 webdriver 감지(로그인 무한 리로드) 방지 플래그는 유지.
    assert "--disable-blink-features=AutomationControlled" in args


@pytest.mark.skipif(sys.platform != "win32", reason="cmd start 폴백은 Windows 전용")
def test_attempt_launch_cmd_start_fallback_hides_console(monkeypatch):
    launched = []

    def fake_popen(args, **kwargs):
        launched.append((args, kwargs))
        if args[0] != "cmd":
            raise OSError("Job 분리 거부")
        return _FakeProc()

    _patch_launch(monkeypatch, fake_popen)

    result = chrome_cdp._attempt_launch(
        "chrome.exe", "profile-dir", "Default", "about:blank",
        port=9555, kill_wait=0,
    )

    assert result["success"] is True
    start_args, start_kwargs = launched[-1]
    assert start_args[:4] == ["cmd", "/c", "start", ""]
    assert _hides_console(start_kwargs)


@pytest.mark.skipif(sys.platform != "win32", reason="정지 taskkill 경로는 Windows 전용")
def test_parallel_stop_taskkill_hides_console(monkeypatch):
    class _StuckProc:
        pid = 3131

        def poll(self):
            return None

        def terminate(self):
            return None

    calls = _record_run(monkeypatch)

    worker_mod.ParallelCliRunner._terminate_processes([_StuckProc()])

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["taskkill", "/PID", "3131", "/T", "/F"]
    assert kwargs["timeout"] == 5
    assert _hides_console(kwargs)

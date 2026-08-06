"""병렬 EDI 최초 보안환경 bootstrap 회귀 테스트.

실제 Chrome/포털을 열지 않고, 준비 순서와 marker 계약만 검증한다.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.workers import parallel_cli_worker as worker_mod
from src.ui.workers.parallel_cli_worker import ParallelCliRunner
from src.utils import chrome_cdp


class _DoneProc:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = []
        self.pid = 12345

    def poll(self):
        return self.returncode

    def terminate(self):
        return None


class _PipeProc:
    def __init__(self, lines):
        self.stdout = lines


class _LiveProc:
    def __init__(self):
        self.returncode = None
        self.stdout = []
        self.pid = 12346
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15


class _Reader:
    def __init__(self):
        self.join_calls = []

    def join(self, timeout=None):
        self.join_calls.append(timeout)


def _runner():
    QApplication.instance() or QApplication([])
    return ParallelCliRunner()


def _specs():
    return [
        {"which": "nps", "label": "국민연금", "portal": "nps", "port": 9223,
         "module": "nps", "env": {}, "cwd": "."},
        {"which": "nhis", "label": "건강보험", "portal": "nhis", "port": 9224,
         "module": "nhis", "env": {}, "cwd": "."},
        {"which": "comwel", "label": "고용보험", "portal": "comwel", "port": 9225,
         "module": "comwel", "env": {}, "cwd": "."},
    ]


def test_unready_profiles_bootstrap_sequentially_then_start_normal_batch(monkeypatch):
    """신규 3개 프로필은 NPS→NHIS→고용 순서 준비 후에만 3-way 업무를 연다."""
    runner = _runner()
    specs = _specs()
    prepared = set()
    events = []

    monkeypatch.setattr(runner, "_make_specs", lambda: specs)
    monkeypatch.setattr(
        chrome_cdp, "is_parallel_profile_ready",
        lambda port, *, portal=None: (port, portal) in prepared,
    )

    def fake_bootstrap(spec):
        events.append(("bootstrap", spec["which"]))
        prepared.add((spec["port"], spec["portal"]))
        return True

    def fake_spawn(spec, *, bootstrap_only=False, clear_fresh_profile=False):
        events.append(("spawn", spec["which"], bootstrap_only, clear_fresh_profile))
        return _DoneProc()

    monkeypatch.setattr(runner, "_bootstrap_one", fake_bootstrap)
    monkeypatch.setattr(runner, "_spawn", fake_spawn)

    runner.run()

    assert events == [
        ("bootstrap", "nps"),
        ("bootstrap", "nhis"),
        ("bootstrap", "comwel"),
        ("spawn", "nps", False, True),
        ("spawn", "nhis", False, True),
        ("spawn", "comwel", False, True),
    ]


def test_ready_profiles_skip_bootstrap_and_keep_normal_parallel_launch(monkeypatch):
    """이미 준비된 프로필이면 bootstrap을 건너뛰고 기존 3개 실행 흐름을 유지한다."""
    runner = _runner()
    specs = _specs()
    events = []

    monkeypatch.setattr(runner, "_make_specs", lambda: specs)
    monkeypatch.setattr(chrome_cdp, "is_parallel_profile_ready", lambda *a, **k: True)
    monkeypatch.setattr(runner, "_bootstrap_one", lambda _spec: (_ for _ in ()).throw(
        AssertionError("ready profile must not bootstrap")))
    monkeypatch.setattr(
        runner, "_spawn",
        lambda spec, *, bootstrap_only=False, clear_fresh_profile=False:
        events.append((spec["which"], bootstrap_only, clear_fresh_profile)) or _DoneProc(),
    )

    runner.run()

    assert events == [
        ("nps", False, False),
        ("nhis", False, False),
        ("comwel", False, False),
    ]


def test_failed_bootstrap_never_starts_next_portal_or_normal_batch(monkeypatch):
    runner = _runner()
    specs = _specs()
    events = []

    monkeypatch.setattr(runner, "_make_specs", lambda: specs)
    monkeypatch.setattr(chrome_cdp, "is_parallel_profile_ready", lambda *a, **k: False)
    monkeypatch.setattr(
        runner, "_bootstrap_one",
        lambda spec: events.append(("bootstrap", spec["which"])) or False,
    )
    monkeypatch.setattr(
        runner, "_spawn",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("normal batch must not start after bootstrap failure")),
    )

    runner.run()

    assert events == [("bootstrap", "nps")]


def test_spawn_uses_bootstrap_flag_without_auto_and_normal_has_auto(monkeypatch):
    """frozen/dev 공통 child 인자 계약: 준비와 업무 배치를 섞지 않는다."""
    runner = _runner()
    runner._request = {
        "firms": ["A"], "mgmts": ["123"], "year": 2026, "month": 7,
    }
    spec = _specs()[0]
    spec["env"] = {"WTAX_FRESH_PROFILE": "1"}
    launched = []

    class _NoopThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def join(self, timeout=None):
            pass

    def fake_popen(**kwargs):
        launched.append(kwargs)
        return _DoneProc()

    monkeypatch.setattr(worker_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(worker_mod.threading, "Thread", _NoopThread)

    runner._spawn(spec, bootstrap_only=True)
    runner._spawn(spec, clear_fresh_profile=True)

    bootstrap_args = launched[0]["args"]
    normal_args = launched[1]["args"]
    assert "--bootstrap-only" in bootstrap_args
    assert "--auto" not in bootstrap_args
    assert "--auto" in normal_args
    assert "--bootstrap-only" not in normal_args
    assert "WTAX_FRESH_PROFILE" not in launched[1]["env"]


def test_bootstrap_marker_is_not_exposed_as_regular_log():
    runner = _runner()
    logs = []
    runner.log_message.connect(logs.append)
    runner._procs["nps"] = _PipeProc([
        "before\n",
        "__WTAX_BOOTSTRAP_READY__\n",
        "after\n",
    ])

    runner._pump("nps")

    assert "nps" in runner._bootstrap_ready
    assert logs == [
        "[NPS] before",
        "[NPS] 최초 보안/로그인 준비 완료",
        "[NPS] after",
    ]


def test_profile_ready_marker_requires_matching_portal_and_respects_fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(chrome_cdp, "APP_DATA_DIR", str(tmp_path))
    chrome_cdp.mark_parallel_profile_ready(9223, "nps")

    assert chrome_cdp.is_parallel_profile_ready(9223, portal="nps") is True
    assert chrome_cdp.is_parallel_profile_ready(9223, portal="nhis") is False
    assert chrome_cdp.is_parallel_profile_ready(9224, portal="nhis") is False

    monkeypatch.setenv("WTAX_FRESH_PROFILE", "1")
    assert chrome_cdp.is_parallel_profile_ready(9223, portal="nps") is False
    assert chrome_cdp.is_parallel_profile_ready(
        9223, portal="nps", respect_fresh_profile=False,
    ) is True


def test_stop_request_prevents_new_child_launch(monkeypatch):
    runner = _runner()
    runner._stop_requested.set()
    monkeypatch.setattr(
        worker_mod.subprocess,
        "Popen",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("stop-requested runner must not launch a child"),
        ),
    )

    assert runner._spawn(_specs()[0]) is None


def test_stop_between_normal_spawns_prevents_later_portals(monkeypatch):
    runner = _runner()
    events = []
    monkeypatch.setattr(runner, "_make_specs", _specs)
    monkeypatch.setattr(chrome_cdp, "is_parallel_profile_ready", lambda *a, **k: True)
    monkeypatch.setattr(chrome_cdp, "kill_chrome_by_port", lambda _port: None)

    def fake_spawn(spec, **_kwargs):
        events.append(spec["which"])
        runner._stop_requested.set()
        return _DoneProc()

    monkeypatch.setattr(runner, "_spawn", fake_spawn)
    runner.run()

    assert events == ["nps"]


def test_spawn_exception_cleans_already_started_child_and_reader(monkeypatch):
    runner = _runner()
    live_proc = _LiveProc()
    reader = _Reader()
    killed_ports = []
    monkeypatch.setattr(runner, "_make_specs", _specs)
    monkeypatch.setattr(chrome_cdp, "is_parallel_profile_ready", lambda *a, **k: True)
    monkeypatch.setattr(
        chrome_cdp,
        "kill_chrome_by_port",
        lambda port: killed_ports.append(port),
    )

    def fake_spawn(spec, **_kwargs):
        if spec["which"] == "nps":
            runner._procs["nps"] = live_proc
            runner._readers["nps"] = reader
            return live_proc
        raise OSError("simulated child launch failure")

    monkeypatch.setattr(runner, "_spawn", fake_spawn)
    runner.run()

    assert live_proc.terminated is True
    assert reader.join_calls
    assert runner._procs == {}
    assert runner._readers == {}
    assert killed_ports == [9223, 9224, 9225]

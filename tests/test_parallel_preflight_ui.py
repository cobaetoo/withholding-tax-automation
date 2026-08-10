"""병렬 EDI 사전점검 GUI 연결 회귀 테스트 (실제 Chrome/포털 미사용)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.ui.workers import parallel_preflight_worker as worker_mod
from src.ui.workers.parallel_preflight_worker import ParallelPreflightWorker


app = QApplication.instance() or QApplication([])


def test_preflight_worker_forwards_structured_report(monkeypatch):
    """워커는 UI 스레드를 건드리지 않고 구조화 결과만 전달한다."""
    expected = {"checks": [], "errors": 0, "warnings": 0, "infos": 0, "ready": True}
    monkeypatch.setattr(worker_mod, "run_parallel_preflight", lambda: expected)
    worker = ParallelPreflightWorker()
    received = []
    worker.check_done.connect(lambda report: received.append(report))

    # QThread를 기동하지 않고 run()을 직접 호출해 외부 HTTPS 접근 없이 signal 계약만 검증.
    worker.run()
    assert received == [expected]


def test_main_window_shows_preflight_only_for_parallel_phase():
    """Phase 2에서는 표시, 일반 EDI phase로 이동하면 숨김."""
    window = MainWindow()

    assert window.company_table.parallel_preflight_btn.isHidden() is True
    window._on_phase_selected(2)
    assert window.company_table.parallel_preflight_btn.isHidden() is False
    assert window.company_table.parallel_preflight_btn.isEnabled() is True

    window._on_phase_selected(3)
    assert window.company_table.parallel_preflight_btn.isHidden() is True

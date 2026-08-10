"""공단 EDI 병렬 사전점검용 단발성 QThread.

점검은 Chrome을 열거나 파일·프로필을 바꾸지 않는 읽기 전용 작업이지만,
포털 HTTPS 확인이 UI를 멈추지 않도록 별도 스레드에서 실행한다.
"""
from PySide6.QtCore import QThread, Signal

from src.utils.parallel_preflight import run_parallel_preflight


class ParallelPreflightWorker(QThread):
    """병렬 EDI 실행 전 환경 점검 결과를 GUI 스레드로 전달한다."""

    check_done = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            self.check_done.emit(run_parallel_preflight())
        except Exception as exc:
            self.failed.emit(str(exc))

"""만료 게이트(_run_expiry_update_gate) Qt 경로 회귀 테스트 (offscreen).

순수 함수(should_offer_expiry_update / should_install_downloaded)는
test_update_expiry_gate.py 가 덮는다. 여기서는 **위젯·시그널이 얽힌 실제 흐름**을
고정한다 — 리뷰에서 확인된 결함들이 전부 이 층에 있었기 때문이다.

고정하는 불변식 3가지:
  A) 확인 실패/최신 없음 → 기존 만료 안내를 보여주고, 설치는 하지 않는다.
  B) 다운로드 취소       → 설치하지 않고, 그래도 만료 안내는 반드시 보여준다.
                           (변경 전에는 창도 메시지도 없이 종료돼 '먹통' 처럼 보였다)
  C) 정상 완료           → 설치를 실행하고, 만료 안내는 띄우지 않는다.

★ C 는 실제 회귀에서 나온 케이스다. QProgressDialog 는 closeEvent 에서도
  canceled 를 emit 하므로, 정리 단계의 prog.close() 가 취소 핸들러를 불러
  '정상 완료'를 취소로 뒤집고 설치를 영구히 막았다(= 자동 업데이트 무력화).
  gate 가 close() 전에 canceled 연결을 끊는지를 이 테스트가 지킨다.

취소 시뮬레이션은 반드시 '취소 버튼 click()' 으로 한다. QProgressDialog.cancel()
은 canceled 시그널을 emit 하지 않아, 그것으로 흉내내면 테스트가 거짓 통과한다.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QPushButton
from PySide6.QtCore import QTimer

import gui_main
import src.ui.workers.update_worker as uw
from src.utils import updater

app = QApplication.instance() or QApplication([])

_OFFER = {
    "action": "optional",
    "version": "9.9.9",
    "url": "https://github.com/example/repo/releases/download/v9.9.9/whta_setup.exe",
    "sha256": "a" * 64,
    "size": 2_000_000,
}


class _FakeWorker:
    """UpdateWorker 대체 — 실제 스레드/네트워크 없이 타이머로 시그널만 흉내낸다."""

    behavior = {"check": {"action": "none"}, "path": "", "cancel": False}

    class _Sig:
        def __init__(self, owner, name):
            self.owner, self.name = owner, name

        def connect(self, fn, *a, **k):
            self.owner._cbs.setdefault(self.name, []).append(fn)

    def __init__(self, *a, **k):
        self._cbs = {}

    def __getattr__(self, item):
        if item in ("check_done", "failed", "download_done", "download_progress"):
            return _FakeWorker._Sig(self, item)
        raise AttributeError(item)

    def _emit(self, name, *args):
        for fn in list(self._cbs.get(name, [])):
            fn(*args)

    def start_check(self):
        QTimer.singleShot(30, lambda: self._emit("check_done", self.behavior["check"]))

    def start_download(self, *a):
        def go():
            if self.behavior["cancel"]:
                _click_cancel_button()
            QTimer.singleShot(40,
                              lambda: self._emit("download_done", self.behavior["path"]))
        QTimer.singleShot(60, go)

    def cancel(self):
        pass

    def wait(self, ms=0):
        return True

    def isRunning(self):
        return False


def _click_cancel_button():
    """진행률 다이얼로그의 취소 버튼을 실제로 누른다(canceled 시그널 발생)."""
    for w in QApplication.topLevelWidgets():
        if isinstance(w, QProgressDialog) and w.isVisible():
            btn = w.findChild(QPushButton)
            if btn is not None:
                btn.click()
            return


def _click_offer(label: str):
    """설치 제안 QMessageBox 가 뜨면 해당 버튼을 누른다(모달이므로 타이머로)."""
    def tick():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMessageBox) and w.isVisible():
                for b in w.buttons():
                    if label in b.text():
                        b.click()
                        return
        QTimer.singleShot(40, tick)
    QTimer.singleShot(40, tick)


@pytest.fixture
def gate(monkeypatch):
    """게이트를 frozen 분기로 몰고, 외부 부작용(설치·로그·디스크)을 전부 대체."""
    seen = {"notice": 0, "spawn": 0}

    monkeypatch.setattr(gui_main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui_main, "_show_expiry_notice",
                        lambda: seen.__setitem__("notice", seen["notice"] + 1))
    monkeypatch.setattr(uw, "UpdateWorker", _FakeWorker)
    monkeypatch.setattr(updater, "log_event", lambda m: None)
    monkeypatch.setattr(updater, "has_enough_disk", lambda n: True)
    monkeypatch.setattr(
        updater, "spawn_installer_and_detach",
        lambda p: (seen.__setitem__("spawn", seen["spawn"] + 1), True)[1],
    )
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: None))
    gui_main._ORPHANED_WORKERS.clear()
    yield seen
    gui_main._ORPHANED_WORKERS.clear()


def test_확인실패시_만료안내만_보여주고_설치하지_않는다(gate):
    """네트워크 불가/최신 없음 → 변경 전과 동일하게 안내 후 종료."""
    _FakeWorker.behavior = {"check": {"action": "none"}, "path": "", "cancel": False}

    gui_main._run_expiry_update_gate()

    assert gate["notice"] == 1
    assert gate["spawn"] == 0


def test_다운로드_취소시_설치하지_않고_만료안내를_보여준다(gate):
    """취소 → 설치 차단(F2) + 안내 누락 방지(F1). 예전엔 창도 메시지도 없었다."""
    _FakeWorker.behavior = {"check": _OFFER, "path": r"C:\fake\setup.exe",
                            "cancel": True}
    _click_offer("지금 업데이트")

    gui_main._run_expiry_update_gate()

    assert gate["spawn"] == 0, "취소했는데 설치가 진행됐다"
    assert gate["notice"] == 1, "취소 후 만료 안내가 사라졌다(창 없이 종료)"


def test_정상완료시_설치하고_만료안내는_띄우지_않는다(gate):
    """★ 회귀: prog.close() 의 canceled 재emit 으로 설치가 막히면 안 된다."""
    _FakeWorker.behavior = {"check": _OFFER, "path": r"C:\fake\setup.exe",
                            "cancel": False}
    _click_offer("지금 업데이트")

    gui_main._run_expiry_update_gate()

    assert gate["spawn"] == 1, (
        "정상 완료인데 설치가 실행되지 않았다 — QProgressDialog.close() 가 "
        "canceled 를 재emit 해 취소로 뒤집혔을 가능성(연결 해제 누락)"
    )
    assert gate["notice"] == 0


def test_종료_선택시_설치하지_않는다(gate):
    """제안 대화상자에서 '종료' → 다운로드조차 시작하지 않는다."""
    _FakeWorker.behavior = {"check": _OFFER, "path": r"C:\fake\setup.exe",
                            "cancel": False}
    _click_offer("종료")

    gui_main._run_expiry_update_gate()

    assert gate["spawn"] == 0

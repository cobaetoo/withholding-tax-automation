"""위택스 phase 선택 시 툴바 비밀번호·휴대전화 입력란 표시 테스트 (offscreen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

# 워크플로우 등록
import src.workflows.wehago_list_clients  # noqa: F401
import src.workflows.nhis_edi  # noqa: F401
import src.workflows.nps_edi  # noqa: F401
import src.workflows.comwel_edi  # noqa: F401
import src.workflows.wehago_swsa  # noqa: F401
import src.workflows.wehago_salary_pdf  # noqa: F401
import src.workflows.wehago_swta  # noqa: F401
import src.workflows.wehago_swer  # noqa: F401
import src.workflows.wehago_jitax_payment  # noqa: F401
import src.workflows.wehago_jitax_efile  # noqa: F401
import src.workflows.hometax  # noqa: F401
import src.workflows.wetax_local_tax  # noqa: F401

from src.workflows.registry import get_phase_info
from src.ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


def _shown(w) -> bool:
    """offscreen 에서 isVisible() 이 False 일 수 있어 isHidden() 으로 판정."""
    return not w.isHidden()


def _window():
    # MainWindow._load_phases 가 워크플로우·phase 2 등록
    return MainWindow()


def test_wetax_phase_meta_needs_password_and_phone():
    info = get_phase_info(13)
    assert info is not None
    assert info["portal"] == "wetax"
    assert info["needs_password"] is True
    assert info["needs_phone"] is True
    assert info["display_name"] == "위택스 지방세 신고"


def test_wetax_toolbar_shows_password_and_phone():
    """위택스(13) 선택 시 비밀번호·휴대전화 둘 다 표시, 홈택스(12)는 비밀번호만."""
    w = _window()
    # 홈택스: 비밀번호만
    w._on_phase_selected(12)
    assert _shown(w.pw_input) and _shown(w.pw_label)
    assert not _shown(w.phone_input) and not _shown(w.phone_label)
    assert w.pw_input.echoMode() == QLineEdit.EchoMode.Password

    # 위택스: 둘 다
    w._on_phase_selected(13)
    assert _shown(w.pw_input) and _shown(w.pw_label)
    assert _shown(w.phone_input) and _shown(w.phone_label)
    assert w.pw_input.echoMode() == QLineEdit.EchoMode.Password
    assert "010" in w.phone_input.placeholderText()
    assert w.phone_label.text() == "휴대전화"

    # 위하고 전자신고 등 비밀번호만 있는 phase (9)
    w._on_phase_selected(9)
    assert _shown(w.pw_input)
    assert not _shown(w.phone_input)

    # 수임처 리스트: 둘 다 숨김
    w._on_phase_selected(1)
    assert not _shown(w.pw_input)
    assert not _shown(w.phone_input)


def test_require_phone_and_password_when_filled():
    w = _window()
    w._on_phase_selected(13)
    w.pw_input.setText("testpw12")
    w.phone_input.setText("010-1234-5678")
    assert w._require_password() == "testpw12"
    assert w._require_phone() == "010-1234-5678"

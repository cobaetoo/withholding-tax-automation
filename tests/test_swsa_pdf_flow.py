"""SWSA0101 급여 PDF 회귀 테스트 (2026-07 WEHAGO 웹 모달 삽입 대응).

버그: #print → '일괄출력' 메뉴와 Duzon PrintDialog 사이에 웹 모달
      '급여대장 일괄인쇄'가 새로 끼어들었다. 그 모달의 [일괄출력] 버튼을
      누르는 단계가 없어 PrintDialog 대기가 항상 타임아웃 → PDF 0건.
      게다가 0건인데도 run_single 이 True 를 반환해 무증상 실패였다.

불변식:
  1. open_print_dialog 는 메뉴 클릭 후 **모달 내 [일괄출력]** 을 누른다.
  2. 회차 그리드를 먼저 체크한다("선택된 급여가 없습니다" 차단).
  3. 회차 그리드는 키 컬럼으로 검증한다(getActiveGrid 는 포커스 의존).
  4. 좌표 하드코딩 금지 — 웹은 getBoundingClientRect, WinForms 는 auto_id.
  5. PDF 0건은 실패다.
  6. 검색영역 접근은 위치(:first-child)가 아닌 제목 기반.
  7. 지급일은 WEHAGO 기본값을 쓰고, 비면 재유도, 끝내 비면 raise.
"""
import asyncio
import inspect
import os

import pytest

from src.automation.wehago import _swsa_constants as C
from src.automation.wehago import _swsa_pdf as P
from src.automation.wehago import _swsa_calendar as CAL


# ─────────────────────────────────────────────────────────────────
# 1~2. 모달 중간 단계 + 회차 선택
# ─────────────────────────────────────────────────────────────────

@pytest.mark.source_only
def test_open_print_dialog_clicks_modal_print_button():
    """메뉴 클릭만으로 끝내면 PrintDialog 가 뜨지 않는다(버그 회귀 방지)."""
    src = inspect.getsource(P.open_print_dialog)
    assert "BULK_MODAL_PRINT_BTN" in src
    assert "_click_modal_button" in src
    # 순서: 메뉴 클릭 → 모달 버튼 클릭 → PrintDialog 대기
    assert src.index("click_menu_item") < src.index("_click_modal_button")
    assert src.index("_click_modal_button") < src.index("_print_dialog_exists")


def test_modal_print_button_label():
    assert C.BULK_MODAL_PRINT_BTN == "일괄출력"
    assert C.BULK_MODAL_TITLE == "급여대장 일괄인쇄"


@pytest.mark.source_only
def test_open_print_dialog_selects_periods_first():
    """회차 미선택이면 모달이 '선택된 급여가 없습니다'로 막힌다."""
    src = inspect.getsource(P.open_print_dialog)
    assert "select_all_pay_periods" in src
    assert src.index("select_all_pay_periods") < src.index("click_menu_item")


def test_no_selection_aborts():
    """선택 0건이면 인쇄를 시도하지 않고 False."""
    calls = {"menu": 0}

    class FakePage:
        async def evaluate(self, js, *a):
            if js is C._PERIOD_GRID_INFO_JS:
                return {"ok": True, "items": 0}
            return None

        async def mouse_click(self, *a):
            pass

    async def fake_menu(page, text):
        calls["menu"] += 1
        return True

    orig = P.click_menu_item
    P.click_menu_item = fake_menu
    try:
        ok = asyncio.run(P.open_print_dialog(FakePage()))
    finally:
        P.click_menu_item = orig

    assert ok is False
    assert calls["menu"] == 0, "회차 0건인데 인쇄 메뉴를 눌렀다"


# ─────────────────────────────────────────────────────────────────
# 3. 회차 그리드 — 포커스 의존 대응
# ─────────────────────────────────────────────────────────────────

def test_period_grid_validated_by_key_column():
    assert C.PERIOD_GRID_KEY_COL == "ym_rvrs"
    assert "keyCol" in C._PERIOD_GRID_INFO_JS
    assert "wrong-grid" in C._PERIOD_GRID_INFO_JS


@pytest.mark.source_only
def test_period_grid_falls_back_to_container_focus():
    """엉뚱한 그리드가 활성이면 컨테이너를 순회해 포커스를 옮긴다."""
    src = inspect.getsource(P.select_all_pay_periods)
    assert "Left_grid" in src
    assert "locator" in src


# ─────────────────────────────────────────────────────────────────
# 4. 해상도 무관
# ─────────────────────────────────────────────────────────────────

@pytest.mark.source_only
def test_web_click_uses_live_element_rect():
    assert "getBoundingClientRect" in C._TOP_MODAL_BUTTON_RECT_JS
    assert "r.left + r.width / 2" in C._TOP_MODAL_BUTTON_RECT_JS
    # 좌표 상수(예: 픽셀 리터럴 기반 클릭)가 없어야 한다
    src = inspect.getsource(P._click_modal_button)
    assert 'rect["x"]' in src and 'rect["y"]' in src


@pytest.mark.source_only
def test_winforms_access_is_non_positional():
    """PrintDialog 조작은 auto_id 기반이어야 한다(보조 모니터 대응)."""
    src = inspect.getsource(P)
    assert "auto_id='cbContents'" in src
    assert "auto_id='btnSavePDF'" in src
    assert "coords=" not in src, "좌표 클릭 회귀"


# ─────────────────────────────────────────────────────────────────
# 5. PDF 0건 = 실패
# ─────────────────────────────────────────────────────────────────

class _FakeState:
    def __init__(self):
        self.failed = []
        self.done = []

    def should_skip_step(self, job_id, name):
        return False

    def before_step(self, job_id, name, idx):
        pass

    def after_step(self, job_id, name):
        self.done.append(name)

    def fail_step(self, job_id, name, msg):
        self.failed.append((name, msg))


def _run_workflow(monkeypatch, tmp_path, pdf_result):
    from src.workflows import wehago_salary_pdf as W

    wf = W.WehagoSalaryPdfWorkflow()
    state = _FakeState()
    calls = {"cleanup": 0}

    async def noop(*a, **k):
        pass

    async def fake_goto(page, name, mgmt, business_number=""):
        return True

    async def fake_nav(page, year=None, month=None):
        return True

    async def fake_dl(page, save_dir, formats):
        return pdf_result

    async def fake_cleanup(page):
        calls["cleanup"] += 1

    monkeypatch.setattr("src.automation.wehago._common.ensure_wehago_main", noop)
    monkeypatch.setattr("src.automation.wehago._common.goto_salary_page_with_fallback",
                        fake_goto)
    monkeypatch.setattr("src.automation.wehago._common.navigate_to_swsa0101", fake_nav)
    monkeypatch.setattr("src.automation.wehago._swsa_pdf.download_multi_pdf", fake_dl)
    monkeypatch.setattr(wf, "_cleanup_print_modals", fake_cleanup)
    monkeypatch.setattr(W, "make_save_dir", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(W, "human_delay", noop)

    ok = asyncio.run(wf.run_single(
        page=object(), context=object(), client_name="테스트", job_id=0,
        state=state, management_number="", year=2026, month=7,
        business_number="000-00-00000",
    ))
    return ok, state, calls


def test_workflow_fails_when_no_pdf(monkeypatch, tmp_path):
    ok, state, calls = _run_workflow(monkeypatch, tmp_path, [])
    assert ok is False
    assert any(n == "download_pdf" for n, _ in state.failed)
    assert calls["cleanup"] == 1, "실패 경로에서도 모달 정리는 수행해야 한다"


def test_workflow_succeeds_when_pdf_created(monkeypatch, tmp_path):
    ok, state, _ = _run_workflow(
        monkeypatch, tmp_path, [str(tmp_path / "급여대장.pdf")])
    assert ok is True
    assert not state.failed


# ─────────────────────────────────────────────────────────────────
# 6~7. 검색영역 / 지급일
# ─────────────────────────────────────────────────────────────────

@pytest.mark.source_only
def test_calendar_opener_is_title_based_not_positional():
    src = inspect.getsource(CAL)
    code_lines = [
        ln for ln in src.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    offending = [ln for ln in code_lines if ":first-child" in ln]
    assert not offending, f"위치 기반 셀렉터 회귀: {offending}"
    assert "open_search_calendar" in src


class _FakePage:
    def __init__(self, values):
        self._values = list(values)

    async def evaluate(self, js, *args):
        return self._values.pop(0) if self._values else None


def test_pay_date_uses_wehago_default():
    """값이 있으면 그대로 사용 — 날짜를 지어내지 않는다."""
    got = asyncio.run(CAL.ensure_swsa_pay_date(_FakePage(["2026.07.25"])))
    assert got == "2026.07.25"


def test_pay_date_refills_when_empty():
    calls = {"n": 0}

    async def refill():
        calls["n"] += 1

    got = asyncio.run(
        CAL.ensure_swsa_pay_date(_FakePage(["", "2026.03.28"]), refill=refill))
    assert got == "2026.03.28"
    assert calls["n"] == 1


def test_pay_date_raises_when_unrecoverable():
    """끝내 비면 raise — 불완전 조회로 PDF 를 뽑지 않는다."""
    async def refill():
        pass

    with pytest.raises(RuntimeError, match="지급일"):
        asyncio.run(CAL.ensure_swsa_pay_date(_FakePage(["", "", ""]), refill=refill))


@pytest.mark.source_only
def test_navigate_sets_pay_date_after_gubun():
    """지급일은 '구분' 선택 뒤에 확보해야 한다(구분 선택이 자동 채움 트리거)."""
    from src.automation.wehago import _common

    src = inspect.getsource(_common.navigate_to_swsa0101)
    assert "ensure_swsa_pay_date" in src
    assert src.index("급여+상여") < src.index("ensure_swsa_pay_date")

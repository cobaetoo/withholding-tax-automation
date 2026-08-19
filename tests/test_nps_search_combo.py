"""NPS 사업장전환 모달의 검색구분 콤보 회귀.

4edcf0c 가 넣었던 "콤보 textContent 에 원하는 구분이 이미 들어있으면 드롭다운
변경 생략" 최적화는 항상 참이 됐다 — 콤보 요소가 하위 combolist 의 항목 라벨
('사업장명'·'사업장관리번호')을 모두 포함하기 때문. 그 결과 콤보가 기본값
'사업장명'에 방치되어 관리번호 검색이 조용히 이름 검색으로 퇴화했고, 이름
fallback 이 대신 성공시켜 전환 자체는 성공해 보였다(증상 은폐).

따라서 아래 테스트는 "콤보 조작을 했는가"가 아니라
"원하는 구분 항목을 실제로 클릭했는가"를 검증한다.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import src.automation.nps._workplace as wp

MODAL_SEARCH = (
    "mainframe.VFrameSet.FrameSdi.ChangeBusi"
    ".form.divPopBg.form.divPopWork.form.div01.form"
)
COMBO = f"{MODAL_SEARCH}.cbo00"
ITEM_NAME = f"{COMBO}.combolist.item_0"    # 사업장명
ITEM_MGMT = f"{COMBO}.combolist.item_1"    # 사업장관리번호

# 실제 DOM 재현: cbo00 의 textContent 는 combolist 항목 라벨을 모두 포함한다.
# 어떤 "이미 선택됨" 부분문자열 가드도 이 값 앞에서는 항상 참이 된다.
COMBO_TEXT_WITH_ALL_LABELS = "사업장명사업장명사업장관리번호"


class _Page:
    """page.evaluate 가 무엇을 묻든 '두 라벨이 다 든 텍스트'를 돌려주는 스텁."""

    def __init__(self):
        self.evaluated = []

    async def evaluate(self, script, arg=None):
        self.evaluated.append((script, arg))
        return COMBO_TEXT_WITH_ALL_LABELS


def _run(search_by_mgmt_no, wait_click_ok=True):
    page = _Page()
    clicked_items = []
    combo_selected = []

    async def wait_and_click(_page, eid, max_wait=5):
        clicked_items.append(eid)
        return {"ok": True} if wait_click_ok else {"error": "timeout"}

    async def select_combo(_page, combo_id, item_text):
        combo_selected.append((combo_id, item_text))
        return {"ok": True, "text": item_text}

    with patch.object(wp, "dismiss_blocking_popups", new=AsyncMock(return_value=0)), \
            patch.object(wp, "human_delay", new=AsyncMock()), \
            patch.object(wp, "nexacro_click_button", new=AsyncMock(
                return_value={"ok": True})) as click_button, \
            patch.object(wp, "nexacro_wait_and_click", new=wait_and_click), \
            patch.object(wp, "nexacro_select_combo", new=select_combo):
        asyncio.run(wp._search_workplace_in_modal(
            page, "51586017090" if search_by_mgmt_no else "주식회사 근린건축",
            search_by_mgmt_no=search_by_mgmt_no,
        ))

    return {
        "items": clicked_items,
        "combo": combo_selected,
        "buttons": [c.args[1] for c in click_button.call_args_list],
    }


def test_mgmt_search_always_selects_mgmt_combo_item():
    """★핵심 회귀: 콤보 텍스트에 '사업장관리번호'가 이미 보여도 item_1 을 클릭해야 한다."""
    r = _run(search_by_mgmt_no=True)

    assert ITEM_MGMT in r["items"], (
        "관리번호 검색인데 검색구분 콤보 item_1 을 클릭하지 않았다 — "
        "'이미 선택됨' 가드가 되살아나면 콤보가 '사업장명'에 방치된다"
    )
    assert ITEM_NAME not in r["items"]
    assert f"{COMBO}.dropbutton" in r["buttons"], "드롭다운을 열지 않았다"


def test_name_search_always_selects_name_combo_item():
    """이름 fallback 도 마찬가지 — 콤보가 관리번호로 남아있을 수 있으므로 매번 설정."""
    r = _run(search_by_mgmt_no=False)

    assert ITEM_NAME in r["items"]
    assert ITEM_MGMT not in r["items"]
    assert f"{COMBO}.dropbutton" in r["buttons"]


def test_search_button_clicked_after_combo_set():
    """콤보 설정 → 검색어 입력 → 조회 버튼(btn00) 순서가 유지된다."""
    r = _run(search_by_mgmt_no=True)

    assert r["buttons"] == [f"{COMBO}.dropbutton", f"{MODAL_SEARCH}.btn00"]


def test_falls_back_to_text_based_combo_select_on_timeout():
    """인덱스 클릭이 타임아웃하면 텍스트 기반 select_combo 로 재시도한다."""
    r = _run(search_by_mgmt_no=True, wait_click_ok=False)

    assert r["combo"] == [(COMBO, "사업장관리번호")]


def test_combo_never_gated_by_textcontent_probe():
    """콤보 상태를 textContent 로 '미리 읽고 생략'하는 코드가 없어야 한다.

    소스 수준 가드 — 최적화가 다시 들어오는 것을 막는다.
    """
    import inspect

    src = inspect.getsource(wp._search_workplace_in_modal)
    body = src.split('"""', 2)[-1]  # docstring 제외
    code = "\n".join(
        ln for ln in body.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "textContent" not in code, (
        "검색구분 콤보를 textContent 로 판별하지 말 것 — "
        "cbo00 은 combolist 항목 라벨을 모두 포함해 항상 오탐한다"
    )

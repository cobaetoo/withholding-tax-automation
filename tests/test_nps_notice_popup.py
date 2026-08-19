"""NPS 로그인 직후 공지(사칭 유의사항) 팝업이 사업장전환을 가리는 회귀."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import src.automation.nps._common as nps_common
import src.automation.nps._workplace as wp

_NOTICE_ID = "mainframe.VFrameSet.FrameSdi.16398"
_CLOSE_ID = _NOTICE_ID + ".titlebar.closebutton"
_CHK_ID = (
    _NOTICE_ID
    + ".form.divPopBg.form.divPopWork.form.div01.form.chk00"
)


def _notice(chk_id=_CHK_ID):
    return {
        "id": _NOTICE_ID,
        "name": "16398",
        "title": "직원 사칭 관련 유의사항",
        "closeId": _CLOSE_ID,
        "chkId": chk_id,
    }


def test_keep_popup_names_never_close_work_modals():
    assert wp._is_keep_popup_name("ChangeBusi")
    assert wp._is_keep_popup_name("form")
    assert wp._is_keep_popup_name("UHJE0002P1")
    assert wp._is_keep_popup_name("divWork_M08010000")
    assert not wp._is_keep_popup_name("16398")


def test_dismiss_clicks_notice_close_not_changebusi():
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=[
        [_notice(chk_id=None)],
        False,
    ])
    clicks = []

    async def click(_page, eid):
        clicks.append(eid)
        return {"ok": True}

    with patch.object(wp, "nexacro_click", new=click), \
            patch.object(wp, "nexacro_click_button", new=AsyncMock()) as mouse, \
            patch.object(wp, "human_delay", new=AsyncMock()):
        n = asyncio.run(wp.dismiss_blocking_popups(page))

    assert n == 1
    assert clicks == [_CLOSE_ID]
    mouse.assert_not_called()


def test_dismiss_checks_today_hide_then_closes():
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=[
        [_notice()],
        {"exists": True, "on": False, "apiSet": False},
        {"exists": True, "on": True, "apiSet": False},
        False,
    ])
    clicks = []

    async def click(_page, eid):
        clicks.append(eid)
        return {"ok": True}

    with patch.object(wp, "nexacro_click", new=click), \
            patch.object(wp, "nexacro_click_button", new=AsyncMock()) as mouse, \
            patch.object(wp, "human_delay", new=AsyncMock()):
        n = asyncio.run(wp.dismiss_blocking_popups(page))

    assert n == 1
    assert clicks == [_CHK_ID, _CLOSE_ID]
    mouse.assert_not_called()


def test_dismiss_skips_chk_click_when_already_checked():
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=[
        [_notice()],
        {"exists": True, "on": True, "apiSet": False},
        False,
    ])
    clicks = []

    async def click(_page, eid):
        clicks.append(eid)
        return {"ok": True}

    with patch.object(wp, "nexacro_click", new=click), \
            patch.object(wp, "nexacro_click_button", new=AsyncMock()) as mouse, \
            patch.object(wp, "human_delay", new=AsyncMock()):
        n = asyncio.run(wp.dismiss_blocking_popups(page))

    assert n == 1
    assert clicks == [_CLOSE_ID]
    mouse.assert_not_called()


def test_dismiss_noop_when_no_notice():
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=[])
    with patch.object(wp, "nexacro_click", new=AsyncMock()) as click:
        n = asyncio.run(wp.dismiss_blocking_popups(page))
    assert n == 0
    click.assert_not_called()


def test_search_skips_combo_when_already_mgmt():
    clicks = []
    page = MagicMock()

    async def evaluate(script, *args, **kwargs):
        if isinstance(script, str) and "textContent" in script:
            return "사업장관리번호"
        return True

    page.evaluate = evaluate

    async def click(_page, eid):
        clicks.append(eid)
        return {"ok": True}

    with patch.object(wp, "dismiss_blocking_popups", new=AsyncMock(return_value=1)), \
            patch.object(wp, "nexacro_click_button", new=click), \
            patch.object(wp, "nexacro_wait_and_click", new=AsyncMock()) as wait_click, \
            patch.object(wp, "nexacro_select_combo", new=AsyncMock()) as sel, \
            patch.object(wp, "human_delay", new=AsyncMock()):
        asyncio.run(wp._search_workplace_in_modal(
            page, "51586017090", search_by_mgmt_no=True,
        ))

    wait_click.assert_not_called()
    sel.assert_not_called()
    assert any(eid.endswith(".btn00") for eid in clicks)
    assert not any("dropbutton" in eid or "combolist" in eid for eid in clicks)


def test_navigate_to_decision_dismisses_before_menu():
    order = []

    async def dismiss(_page):
        order.append("dismiss")
        return 0

    async def click(_page, eid):
        order.append("click")
        return {"ok": True}

    page = MagicMock()
    with patch.object(nps_common, "dismiss_blocking_popups", new=dismiss), \
            patch.object(nps_common, "nexacro_click_button", new=click), \
            patch.object(nps_common, "human_delay", new=AsyncMock()):
        ok = asyncio.run(nps_common.navigate_to_decision_details(page))

    assert ok is True
    assert order[0] == "dismiss"
    assert order.count("click") == 2


def test_run_auto_batch_dismisses_before_each_firm():
    import src.automation.nps.nps_auto_cdp as nps_cli

    order = []

    async def dismiss(_page):
        order.append("dismiss")
        return 0

    async def open_modal(_page):
        order.append("open")
        return True

    async def select(_page, _name, management_number=""):
        order.append("select")
        return True

    async def run_one(*_a, **_k):
        order.append("run")
        return True

    with patch.object(nps_cli, "dismiss_blocking_popups", new=dismiss), \
            patch.object(nps_cli, "switch_workplace_open", new=open_modal), \
            patch.object(nps_cli, "select_workplace", new=select), \
            patch.object(nps_cli, "run_single_workplace", new=run_one), \
            patch.object(nps_cli, "human_delay", new=AsyncMock()), \
            patch.object(nps_cli, "_trace", lambda *_a, **_k: None), \
            patch.object(nps_cli, "_emit_summary", lambda *_a, **_k: None):
        asyncio.run(nps_cli.run_auto_batch(
            MagicMock(), MagicMock(),
            firms=["A", "B"], year=2026, month=7, mgmts=["1", "2"],
        ))

    assert order == [
        "dismiss", "open", "select", "run",
        "dismiss", "open", "select", "run",
    ]


def test_run_single_workplace_dismisses_before_decision():
    import src.automation.nps.nps_auto_cdp as nps_cli

    order = []

    async def dismiss(_page):
        order.append("dismiss")
        return 0

    async def nav(_page):
        order.append("nav")
        return True

    async def detail(_page, year=None, month=None):
        order.append("detail")
        return {"ok": True}

    async def dl(*_a, **_k):
        order.append("dl")
        return {"excel": "x.xlsx"}

    with patch.object(nps_cli, "dismiss_blocking_popups", new=dismiss), \
            patch.object(nps_cli, "navigate_to_decision_details", new=nav), \
            patch.object(nps_cli, "open_decision_detail", new=detail), \
            patch.object(nps_cli, "download_final_integrated", new=dl), \
            patch.object(nps_cli, "human_delay", new=AsyncMock()), \
            patch.object(nps_cli, "make_save_dir", lambda *_a, **_k: "tmp"):
        ok = asyncio.run(nps_cli.run_single_workplace(
            MagicMock(), MagicMock(), "리틀치프", year=2026, month=7,
        ))

    assert ok is True
    assert order[0] == "dismiss"
    assert order[1] == "nav"

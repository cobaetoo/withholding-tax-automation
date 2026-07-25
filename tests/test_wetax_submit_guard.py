"""click_submit_report 게이트·라벨 가드·성공 시그널 단위 테스트."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.automation.wetax._form import (
    click_submit_report,
    _submit_success_signal,
)
from src.automation.wetax._constants import (
    ACCOUNTING_CONVERT_RESULT_PATH,
    ACCOUNTING_FILE_REPORT_PATH,
    ACCOUNTING_SUBMIT_RESULT_PATH,
)


def _page_with_btn(label: str, url: str):
    page = MagicMock()
    page.url = f"https://www.wetax.go.kr{url}"
    loc = MagicMock()
    loc.first = MagicMock()
    loc.first.wait_for = AsyncMock(return_value=None)
    loc.first.inner_text = AsyncMock(return_value=label)
    loc.first.scroll_into_view_if_needed = AsyncMock(return_value=None)
    loc.first.click = AsyncMock(return_value=None)
    page.locator = MagicMock(return_value=loc)
    page.evaluate = AsyncMock(return_value=None)
    return page


def test_submit_rejects_when_err_gt_zero():
    page = _page_with_btn("제출하기", ACCOUNTING_CONVERT_RESULT_PATH)

    async def _run():
        with patch(
            "src.automation.wetax._form.get_convert_result_summary",
            new=AsyncMock(return_value={"ok": 1, "err": 2, "url": page.url}),
        ):
            return await click_submit_report(page, require_ok=True)

    assert asyncio.run(_run()) is False
    page.locator.return_value.first.click.assert_not_called()


def test_submit_rejects_when_ok_zero():
    page = _page_with_btn("제출하기", ACCOUNTING_CONVERT_RESULT_PATH)

    async def _run():
        with patch(
            "src.automation.wetax._form.get_convert_result_summary",
            new=AsyncMock(return_value={"ok": 0, "err": 0, "url": page.url}),
        ):
            return await click_submit_report(page, require_ok=True)

    assert asyncio.run(_run()) is False


def test_submit_rejects_convert_button_label():
    page = _page_with_btn("파일변환하기", ACCOUNTING_FILE_REPORT_PATH)

    async def _run():
        with patch(
            "src.automation.wetax._form.get_convert_result_summary",
            new=AsyncMock(return_value={"ok": 1, "err": 0, "url": page.url}),
        ):
            return await click_submit_report(page, require_ok=True)

    assert asyncio.run(_run()) is False
    page.locator.return_value.first.click.assert_not_called()


def test_submit_rejects_label_read_failure():
    """라벨 확인 예외 시 hard-fail — 클릭 안 함."""
    page = _page_with_btn("제출하기", ACCOUNTING_CONVERT_RESULT_PATH)
    page.locator.return_value.first.inner_text = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    async def _run():
        with patch(
            "src.automation.wetax._form.get_convert_result_summary",
            new=AsyncMock(return_value={"ok": 1, "err": None, "url": page.url}),
        ):
            return await click_submit_report(page, require_ok=True)

    assert asyncio.run(_run()) is False
    page.locator.return_value.first.click.assert_not_called()


def test_submit_success_signal_m33_only():
    async def _m33():
        page = MagicMock()
        page.evaluate = AsyncMock(
            return_value={
                "url": f"https://www.wetax.go.kr{ACCOUNTING_SUBMIT_RESULT_PATH}",
                "batchMsg": True,
                "bodyHead": "일괄신고 제출처리중",
            }
        )
        return await _submit_success_signal(page)

    async def _m31_false():
        page = MagicMock()
        page.evaluate = AsyncMock(
            return_value={
                "url": f"https://www.wetax.go.kr{ACCOUNTING_FILE_REPORT_PATH}",
                "batchMsg": False,
                "bodyHead": "",
            }
        )
        return await _submit_success_signal(page)

    async def _left_etr_false():
        """구 left_m32 휴리스틱 — 더 이상 성공 아님."""
        page = MagicMock()
        page.evaluate = AsyncMock(
            return_value={
                "url": "https://www.wetax.go.kr/etr/other/foo.do",
                "batchMsg": False,
                "bodyHead": "기타",
            }
        )
        return await _submit_success_signal(page)

    assert asyncio.run(_m33())["reason"] == "m33_url"
    assert asyncio.run(_m31_false()) is None
    assert asyncio.run(_left_etr_false()) is None


def test_submit_clicks_when_ok_and_m33_signal():
    page = _page_with_btn("제출하기", ACCOUNTING_CONVERT_RESULT_PATH)

    async def eval_side_effect(script, *args, **kwargs):
        if isinstance(script, str) and "batchMsg" in script:
            return {
                "url": f"https://www.wetax.go.kr{ACCOUNTING_SUBMIT_RESULT_PATH}",
                "batchMsg": True,
                "bodyHead": "일괄신고",
            }
        return None

    page.evaluate = AsyncMock(side_effect=eval_side_effect)

    async def _run():
        with patch(
            "src.automation.wetax._form.get_convert_result_summary",
            new=AsyncMock(
                return_value={"ok": 1, "err": None, "url": page.url}
            ),
        ):
            return await click_submit_report(page, require_ok=True, timeout_s=2)

    ok = asyncio.run(_run())
    assert ok is True
    page.locator.return_value.first.click.assert_awaited()

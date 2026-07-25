"""click_submit_report 게이트·라벨 가드 단위 테스트 (브라우저 없음)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.automation.wetax._form import click_submit_report
from src.automation.wetax._constants import (
    ACCOUNTING_CONVERT_RESULT_PATH,
    ACCOUNTING_FILE_REPORT_PATH,
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


def test_submit_clicks_when_ok_and_submit_label():
    page = _page_with_btn("제출하기", ACCOUNTING_CONVERT_RESULT_PATH)
    # accept_native_dialogs evaluate + confirm msgs + success signal
    signals = [
        None,  # install dialog
        [],  # confirm msgs
        None,  # restore
    ]

    async def eval_side_effect(script, *args, **kwargs):
        # success signal path uses evaluate returning dict
        if isinstance(script, str) and "keywords" in script:
            return {
                "url": f"https://www.wetax.go.kr{ACCOUNTING_FILE_REPORT_PATH}",
                "hasPw": True,
                "btnText": "파일변환하기",
                "hit": None,
                "step3": False,
                "bodyHead": "",
            }
        if signals:
            return signals.pop(0)
        return None

    page.evaluate = AsyncMock(side_effect=eval_side_effect)

    async def _run():
        with patch(
            "src.automation.wetax._form.get_convert_result_summary",
            new=AsyncMock(
                return_value={
                    "ok": 1,
                    "err": None,
                    "url": page.url,
                }
            ),
        ):
            # force _submit_success_signal via evaluate with keywords
            return await click_submit_report(page, require_ok=True, timeout_s=2)

    ok = asyncio.run(_run())
    assert ok is True
    page.locator.return_value.first.click.assert_awaited()

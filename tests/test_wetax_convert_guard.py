"""click_convert_file 라벨 가드 hard-fail 단위 테스트."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.automation.wetax._form import click_convert_file
from src.automation.wetax._constants import (
    ACCOUNTING_CONVERT_RESULT_PATH,
    ACCOUNTING_FILE_REPORT_PATH,
)


def _page(label: str, url: str):
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


def test_convert_rejects_submit_label_on_m32():
    page = _page("제출하기", ACCOUNTING_CONVERT_RESULT_PATH)

    async def _run():
        with patch(
            "src.automation.wetax._navigation.ensure_upload_form",
            new=AsyncMock(return_value=True),
        ):
            # ensure 후 url 은 여전히 mock m32 unless we change page.url
            page.url = f"https://www.wetax.go.kr{ACCOUNTING_FILE_REPORT_PATH}"
            page.locator.return_value.first.inner_text = AsyncMock(
                return_value="제출하기"
            )
            return await click_convert_file(page, timeout_s=1)

    # after ensure we set url to M31 but label still 제출 → reject
    assert asyncio.run(_run()) is False


def test_convert_rejects_label_exception():
    page = _page("파일변환하기", ACCOUNTING_FILE_REPORT_PATH)
    page.locator.return_value.first.inner_text = AsyncMock(
        side_effect=RuntimeError("no label")
    )

    assert asyncio.run(click_convert_file(page, timeout_s=1)) is False
    page.locator.return_value.first.click.assert_not_called()


def test_convert_rejects_non_m31_url():
    page = _page("파일변환하기", "/main.do")
    assert asyncio.run(click_convert_file(page, timeout_s=1)) is False
    page.locator.return_value.first.click.assert_not_called()


def test_convert_m32_reeneters_m31():
    """이미 M32 이면 ensure_upload_form 호출 후 변환 진행 시도."""
    page = _page("파일변환하기", ACCOUNTING_CONVERT_RESULT_PATH)
    ensure = AsyncMock(return_value=False)

    async def _run():
        with patch(
            "src.automation.wetax._navigation.ensure_upload_form",
            ensure,
        ):
            return await click_convert_file(page, timeout_s=1)

    assert asyncio.run(_run()) is False
    ensure.assert_awaited()

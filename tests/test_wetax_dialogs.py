"""Wetax 안전 헬퍼 단위 테스트 — mask_phone, dialog restore (evaluate 체인 mock)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.automation.wetax._common import mask_phone
from src.automation.wetax._dialogs import accept_native_dialogs


def test_mask_phone_hyphenated():
    assert mask_phone("010-1234-5678") == "010-****-5678"


def test_mask_phone_digits_only():
    # 11 digits → head3 + mid4 + tail4
    assert mask_phone("01012345678") == "010****5678"


def test_mask_phone_short():
    # 7자리 미만: 원문 비노출 — 최소 4개 마스킹
    assert mask_phone("123") == "****"
    assert mask_phone("") == ""
    assert mask_phone(None) == ""  # type: ignore[arg-type]


def test_mask_phone_no_raw_middle():
    masked = mask_phone("010-9876-5432")
    assert "9876" not in masked
    assert masked.startswith("010")
    assert masked.endswith("5432")


def test_accept_native_dialogs_installs_and_restores():
    """evaluate 가 install 후 finally 에서 restore 를 호출하는지."""
    page = MagicMock()
    calls: list = []

    async def fake_evaluate(script, *args):
        calls.append(script if isinstance(script, str) else str(script))
        return None

    page.evaluate = AsyncMock(side_effect=fake_evaluate)

    async def _run():
        async with accept_native_dialogs(page, accept=True):
            pass

    asyncio.run(_run())
    assert len(calls) >= 2
    install_js = calls[0]
    restore_js = calls[-1]
    assert "__wetax_dialog_orig" in install_js
    assert "window.confirm" in install_js
    # restore 스크립트는 orig 를 되돌림
    assert "__wetax_dialog_orig" in restore_js
    assert "window.confirm" in restore_js


def test_accept_native_dialogs_restore_on_body_exception():
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=None)

    async def _run():
        try:
            async with accept_native_dialogs(page, accept=True):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

    asyncio.run(_run())
    # install + restore
    assert page.evaluate.await_count == 2

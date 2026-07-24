"""위택스 메뉴 네비게이션 — 특별징수 회계파일신고 등."""

from __future__ import annotations

import asyncio
import re
from typing import Callable

from src.automation.wetax._common import dismiss_popups, log
from src.automation.wetax._constants import (
    ACCOUNTING_FILE_REPORT_PATH,
    ACCOUNTING_FILE_REPORT_URL,
    WETAX_HOST,
)


async def goto_accounting_file_report(
    page,
    *,
    logger: Callable[[str], None] | None = None,
) -> bool:
    """신고 → 특별징수 → 회계파일신고 화면으로 이동.

    1순위: 확정 URL 직접 이동 (B070101M31.do) — 메뉴 hover 불안정 회피
    2순위: GNB 텍스트 클릭 폴백
    도착 판정: URL 경로 포함 또는 title 에 '회계파일신고'
    """
    _log = logger or log

    # 이미 도착
    if await _on_accounting_page(page):
        _log("  [WETAX nav] 이미 회계파일신고 화면")
        await dismiss_popups(page, logger=_log)
        return True

    # ── 1) 직접 URL ──
    try:
        _log(f"  [WETAX nav] goto {ACCOUNTING_FILE_REPORT_URL}")
        await page.goto(
            ACCOUNTING_FILE_REPORT_URL,
            wait_until="domcontentloaded",
            timeout=45000,
        )
        await asyncio.sleep(0.8)
        await dismiss_popups(page, logger=_log)
        if await _on_accounting_page(page):
            _log("  [WETAX nav] 회계파일신고 도착 (direct URL)")
            return True
    except Exception as e:
        _log(f"  [WETAX nav] direct goto 실패: {e}")

    # ── 2) GNB 메뉴 클릭 폴백 ──
    try:
        _log("  [WETAX nav] GNB 폴백: 신고→특별징수→회계파일신고")
        # 신고 호버
        loc_신고 = page.locator("li > a").filter(has_text=re.compile(r"^신고$"))
        if await loc_신고.count():
            await loc_신고.first.hover(force=True, timeout=3000)
            await asyncio.sleep(0.5)
        # 특별징수 클릭
        loc_sp = page.locator(".depth-wrap a, a").filter(has_text=re.compile(r"^특별징수$"))
        if await loc_sp.count():
            await loc_sp.first.click(force=True, timeout=3000)
            await asyncio.sleep(0.5)
        # 회계파일신고 클릭
        loc_acc = page.locator("a, button, span").filter(
            has_text=re.compile(r"회계파일\s*신고")
        )
        if await loc_acc.count():
            await loc_acc.first.click(force=True, timeout=5000)
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            await asyncio.sleep(0.8)
            await dismiss_popups(page, logger=_log)
            if await _on_accounting_page(page):
                _log("  [WETAX nav] 회계파일신고 도착 (GNB)")
                return True
    except Exception as e:
        _log(f"  [WETAX nav] GNB 폴백 실패: {e}")

    _log(f"  [WETAX nav] 실패 url={getattr(page, 'url', '?')}")
    return False


async def _on_accounting_page(page) -> bool:
    """업로드 화면(M31) 여부.

    파일변환 후 M32(서식검증) 도 제목은 '회계파일신고' 이므로 title 만으로
    판정하면 다음 수임처 때 재진입이 스킵된다. URL 경로(M31) 또는
    업로드 전용 필드(#filePw / #file_upload_0_) 존재를 본다.
    """
    try:
        url = page.url or ""
        if ACCOUNTING_FILE_REPORT_PATH in url:
            return True
        if WETAX_HOST not in url:
            return False
        # M32 등 다른 단계면 False → goto 가 M31 로 다시 이동
        if "/B070101M" in url and ACCOUNTING_FILE_REPORT_PATH not in url:
            return False
        # URL 이 애매할 때 업로드 폼 필드로 판정
        try:
            if await page.locator("#filePw, #file_upload_0_").count() > 0:
                return True
        except Exception:
            pass
        return False
    except Exception:
        return False

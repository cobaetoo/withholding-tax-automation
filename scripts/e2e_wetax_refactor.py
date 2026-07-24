"""위택스 리팩토링 항목별 E2E (CDP + 로컬 HTML + 실제 FS).

항목: W3 dialog 복원, W2 버튼 라벨 가드, W6 파일 필터, W14 마스킹,
      W4-lite summary, W10 ensure_upload_form (세션 있을 때).
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # repo root
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, bool, str]] = []


def report(item: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((item, ok, detail))
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {item}: {detail}")


def e2e_w14_mask_phone() -> None:
    from src.automation.wetax._common import mask_phone
    m = mask_phone("010-1234-5678")
    ok = m == "010-****-5678" and "1234" not in m
    report("W14 mask_phone", ok, repr(m))


def e2e_w6_file_filter() -> None:
    from src.automation.wetax._form import find_jitax_encrypted_file

    # 1) 실제 오버루트 7월 경로
    real = find_jitax_encrypted_file("주식회사 오버루트", year=2026, month=7)
    ok_real = bool(real and real.endswith(".2") and os.path.isfile(real))
    report(
        "W6 find real 오버루트/202607",
        ok_real,
        real or "None",
    )

    # 2) 오염 폴더: .xlsx 최신이어도 .2 선택
    with tempfile.TemporaryDirectory() as td:
        noise = Path(td) / "latest.xlsx"
        good = Path(td) / "efile.2"
        noise.write_bytes(b"noise")
        good.write_bytes(b"good")
        os.utime(noise, None)
        os.utime(good, (os.path.getmtime(good) - 100, os.path.getmtime(good) - 100))
        # noise is newer
        import time
        time.sleep(0.05)
        noise.write_bytes(b"noise2")
        from unittest.mock import patch
        with patch("src.automation.wetax._form.make_save_dir", return_value=td):
            got = find_jitax_encrypted_file("X", year=2026, month=7)
        ok = got is not None and got.endswith(".2")
        report("W6 ignore newer xlsx", ok, got or "None")


async def e2e_w3_dialog_restore(page) -> None:
    from src.automation.wetax._dialogs import (
        accept_native_dialogs,
        is_dialog_override_active,
    )

    await page.set_content(
        """
        <html><body>
        <button id="ask">ask</button>
        <script>
          window.__results = [];
          document.getElementById('ask').onclick = () => {
            window.__results.push(window.confirm('업로드 하신 회계 파일의 신고정보를 검증하시겠습니까?'));
          };
        </script>
        </body></html>
        """
    )
    # baseline: browser default confirm — playwright auto-dismisses? use evaluate
    # Under override accept=True
    async with accept_native_dialogs(page, accept=True, message_substr="검증"):
        active = await is_dialog_override_active(page)
        val = await page.evaluate("() => window.confirm('업로드 하신 회계 파일의 신고정보를 검증하시겠습니까?')")
        report("W3 override active during block", active is True, f"active={active} confirm={val}")
        if val is not True:
            report("W3 confirm returns true under override", False, str(val))
        else:
            report("W3 confirm returns true under override", True, str(val))

    active_after = await is_dialog_override_active(page)
    report("W3 override restored after exit", active_after is False, f"active={active_after}")

    # After restore, native confirm should not be our always-true (hard to assert fully
    # without dialog handler; check that function is not our wrapper by calling and
    # checking __wetax_dialog_orig._active)
    still = await page.evaluate(
        "() => !!(window.__wetax_dialog_orig && window.__wetax_dialog_orig._active)"
    )
    report("W3 _active flag false after restore", still is False, str(still))


async def e2e_w2_button_guards(page) -> None:
    """로컬 HTML 로 M32 제출 버튼을 변환으로 누르지 않는지."""
    from src.automation.wetax._form import click_convert_file
    from src.automation.wetax._constants import ACCOUNTING_CONVERT_RESULT_PATH

    # M32-like: same id btn_next, label 제출하기, URL 흉내 불가 → label only
    await page.set_content(
        """
        <html><body>
        <a id="btn_next" class="button">제출하기 움직이는 화살표</a>
        </body></html>
        """
    )
    # url won't be wetax M31 — label is submit only → must refuse
    ok = await click_convert_file(page, timeout_s=2)
    report("W2 refuse submit-labeled btn_next", ok is False, f"returned={ok}")

    # M31-like convert button
    await page.set_content(
        """
        <html><body>
        <a id="btn_next" class="button">파일변환하기 움직이는 화살표</a>
        <input id="filePw" type="password" />
        <script>
          document.getElementById('btn_next').onclick = () => {
            // no navigation — will timeout, but should click not refuse
            history.replaceState({}, '', '/etr/lit/b0701/B070101M31.do');
          };
        </script>
        </body></html>
        """
    )
    # Force url via evaluate before click? page.url is about:blank or data
    # Our guard: not on_m31 and looks_convert → looks_convert True → allow click
    # Then wait timeouts → returns False — still proves not refused as submit
    # Better: spy that click happened
    clicked = {"n": 0}
    await page.evaluate(
        """() => {
          const b = document.getElementById('btn_next');
          b.addEventListener('click', () => { window.__cvt_clicked = true; });
        }"""
    )
    # short timeout — will fail conversion wait but should have clicked
    await click_convert_file(page, timeout_s=1.5)
    was = await page.evaluate("() => !!window.__cvt_clicked")
    report("W2 allows convert-labeled btn_next click", was is True, f"clicked={was}")


async def e2e_w4_summary(page) -> None:
    from src.automation.wetax._form import get_convert_result_summary

    await page.set_content(
        """
        <html><body>
        <div>정상 신고 내역 0건</div>
        <div>오류 신고 내역 1건</div>
        </body></html>
        """
    )
    s = await get_convert_result_summary(page)
    ok = s.get("ok") == 0 and s.get("err") == 1
    report("W4-lite get_convert_result_summary", ok, str(s))


async def e2e_w10_ensure_upload(page) -> None:
    """CDP 위택스 세션이 살아 있을 때만 실전 검증."""
    from src.automation.wetax._navigation import ensure_upload_form, _on_accounting_page
    from src.automation.wetax._constants import ACCOUNTING_FILE_REPORT_PATH

    url = page.url or ""
    if "wetax.go.kr" not in url:
        report("W10 ensure_upload_form (live)", False, f"not on wetax: {url[:80]}")
        return
    if "logout" in url:
        report("W10 ensure_upload_form (live)", False, "session logged out")
        return

    ok = await ensure_upload_form(page)
    on = await _on_accounting_page(page)
    report(
        "W10 ensure_upload_form (live)",
        ok and on and ACCOUNTING_FILE_REPORT_PATH in (page.url or ""),
        page.url,
    )


async def e2e_w3_w2_via_playwright_local() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await e2e_w3_dialog_restore(page)
            await e2e_w2_button_guards(page)
            await e2e_w4_summary(page)
        finally:
            await browser.close()


async def e2e_cdp_live() -> None:
    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9223")
            page = None
            for ctx in browser.contexts:
                for pg in ctx.pages:
                    if "wetax.go.kr" in (pg.url or ""):
                        page = pg
                        break
            if page is None:
                report("W10 ensure_upload_form (live)", False, "no wetax tab on CDP")
                return
            await e2e_w10_ensure_upload(page)
    except Exception as e:
        report("W10 ensure_upload_form (live)", False, f"CDP error: {e}")


def main() -> int:
    print("=== Wetax refactor E2E ===")
    e2e_w14_mask_phone()
    e2e_w6_file_filter()
    asyncio.run(e2e_w3_w2_via_playwright_local())
    asyncio.run(e2e_cdp_live())

    print("\n=== Summary ===")
    fails = 0
    for item, ok, detail in RESULTS:
        print(f"  {'OK' if ok else 'NG'}  {item} — {detail[:100]}")
        if not ok:
            fails += 1
    print(f"\n{len(RESULTS) - fails}/{len(RESULTS)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

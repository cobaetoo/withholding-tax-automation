"""W10 ensure_upload_form 라이브 E2E (CDP 9223).

1) 위택스 탭 확보 → main.do
2) 로그인 대기 (Human-in-the-loop, 최대 ~10분)
3) M32 URL 로 이동 후 ensure_upload_form → M31 + #filePw 확인
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # repo root
sys.path.insert(0, str(ROOT))

CDP = "http://127.0.0.1:9223"
WETAX_MAIN = "https://www.wetax.go.kr/main.do"
M32 = "https://www.wetax.go.kr/etr/lit/b0701/B070101M32.do"
M31_PATH = "/etr/lit/b0701/B070101M31.do"


async def find_wetax_page(browser):
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if "wetax.go.kr" in (pg.url or ""):
                return pg
    # open new tab if needed
    ctx = browser.contexts[0] if browser.contexts else None
    if ctx is None:
        return None
    return await ctx.new_page()


async def wetax_logged_in(page) -> bool:
    try:
        if "wetax.go.kr" not in (page.url or ""):
            return False
        if "logout.do" in (page.url or ""):
            return False
        return await page.evaluate(
            """() => {
              const vis = (el) => {
                if (!el) return false;
                const s = getComputedStyle(el);
                if (s.display === 'none' || s.visibility === 'hidden') return false;
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
              };
              const btn = document.querySelector('a.btnLogout');
              if (vis(btn)) return true;
              const all = document.querySelectorAll('a, button, span, div, li');
              for (const el of all) {
                if (!vis(el)) continue;
                const txt = (el.value || el.innerText || el.title || '')
                  .replace(/\\s+/g, ' ').trim();
                if (txt === '로그아웃' || txt === '로그인연장' || txt.includes('로그인연장'))
                  return true;
              }
              return false;
            }"""
        )
    except Exception:
        return False


async def wait_login(page, max_sec: int = 600) -> bool:
    print(f"[W10] 로그인 대기 중... 위택스 전자세금용 공인인증서로 로그인해 주세요. (최대 {max_sec}s)")
    for i in range(max_sec // 5):
        if await wetax_logged_in(page):
            print(f"[W10] 로그인 확인 ({(i + 1) * 5}s) url={page.url}")
            return True
        if i % 6 == 5:
            print(f"  ... 대기 중 {(i + 1) * 5}s  url={page.url[:80]}")
        await asyncio.sleep(5)
    return False


async def main() -> int:
    from playwright.async_api import async_playwright
    from src.automation.wetax._common import dismiss_popups
    from src.automation.wetax._navigation import ensure_upload_form, _on_accounting_page
    from src.automation.wetax._constants import ACCOUNTING_FILE_REPORT_PATH

    print("=== W10 ensure_upload_form LIVE E2E ===")
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP)
        except Exception as e:
            print(f"FAIL: CDP 연결 실패 {e}")
            return 1

        page = await find_wetax_page(browser)
        if page is None:
            print("FAIL: 페이지 없음")
            return 1

        print(f"[W10] start url={page.url}")
        # logout 화면이면 main 으로
        try:
            await page.goto(WETAX_MAIN, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(1)
            try:
                await dismiss_popups(page)
            except Exception:
                pass
        except Exception as e:
            print(f"[W10] main.do goto 경고: {e}")

        if not await wetax_logged_in(page):
            ok = await wait_login(page)
            if not ok:
                print("FAIL: 로그인 타임아웃")
                return 1
            try:
                await dismiss_popups(page)
            except Exception:
                pass

        # --- Case A: 이미 M31 이면 ensure no-op ---
        try:
            await page.goto(
                f"https://www.wetax.go.kr{ACCOUNTING_FILE_REPORT_PATH}",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            await asyncio.sleep(1)
            await dismiss_popups(page)
        except Exception as e:
            print(f"FAIL: M31 직접 이동 실패: {e}")
            return 1

        on_m31 = await _on_accounting_page(page)
        print(f"[W10] A pre: on_m31={on_m31} url={page.url}")
        ok_a = await ensure_upload_form(page)
        on_a = await _on_accounting_page(page)
        has_pw = await page.locator("#filePw").count()
        print(f"[W10] A ensure ok={ok_a} on_m31={on_a} filePw={has_pw} url={page.url}")
        pass_a = ok_a and on_a and ACCOUNTING_FILE_REPORT_PATH in (page.url or "")
        print(f"[{'PASS' if pass_a else 'FAIL'}] W10-A already M31 ensure no-op/keep")

        # --- Case B: M32 로 보낸 뒤 ensure → M31 ---
        try:
            await page.goto(M32, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(1)
        except Exception as e:
            print(f"[W10] M32 goto 경고(권한/세션): {e}")
            # 실패해도 URL 만 확인
            pass

        url_b0 = page.url or ""
        on_m32ish = M32.split("/")[-1].replace(".do", "") in url_b0 or "M32" in url_b0
        print(f"[W10] B pre: url={url_b0} m32ish={on_m32ish}")
        ok_b = await ensure_upload_form(page)
        on_b = await _on_accounting_page(page)
        has_pw_b = await page.locator("#filePw").count()
        print(f"[W10] B ensure ok={ok_b} on_m31={on_b} filePw={has_pw_b} url={page.url}")
        pass_b = (
            ok_b
            and on_b
            and ACCOUNTING_FILE_REPORT_PATH in (page.url or "")
            and has_pw_b > 0
        )
        print(f"[{'PASS' if pass_b else 'FAIL'}] W10-B from M32/other → M31 + filePw")

        # screenshot
        try:
            await page.screenshot(path="results/wetax_w10_e2e.png", full_page=False)
            print("[W10] screenshot results/wetax_w10_e2e.png")
        except Exception:
            pass

        if pass_a and pass_b:
            print("\n=== W10 LIVE E2E: ALL PASS ===")
            return 0
        print("\n=== W10 LIVE E2E: PARTIAL/FAIL ===")
        print(f"  A={pass_a} B={pass_b}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""위택스 Phase 13 라이브 단건 실행 (GUI 없이 코드 경로).

수임처 1건: 로그인 → 회계파일신고 → 전화·비번·파일 → 변환 → 제출(M33).
운영 기본은 실제 제출. 스텁만 필요 시 WETAX_STUB_SUBMIT=1.

사용 예:
  python scripts/run_wetax_live.py ^
    --client "주식회사 드류" --year 2026 --month 7 ^
    --password "파일비번" --phone "010-1234-5678"

  # 서식검증/결과 화면에 멈춰 M31 복귀 안 함
  python scripts/run_wetax_live.py ... --stay-m32

환경변수: WETAX_PASSWORD, WETAX_PHONE, WETAX_STUB_SUBMIT
Chrome CDP 9223. 전자세금용 공인인증서 로그인은 Human-in-the-loop.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WETAX_MAIN = "https://www.wetax.go.kr/main.do"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="위택스 회계파일신고 라이브 단건")
    p.add_argument("--client", default="주식회사 드류", help="수임처명")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--month", type=int, default=7)
    p.add_argument(
        "--password",
        default=os.environ.get("WETAX_PASSWORD", ""),
        help="전자신고 파일 비밀번호 (또는 WETAX_PASSWORD)",
    )
    p.add_argument(
        "--phone",
        default=os.environ.get("WETAX_PHONE", ""),
        help="휴대전화번호 (또는 WETAX_PHONE)",
    )
    p.add_argument(
        "--login-timeout",
        type=int,
        default=600,
        help="로그인 대기 초 (기본 600)",
    )
    p.add_argument(
        "--no-launch",
        action="store_true",
        help="Chrome 실행 생략 — 이미 CDP 9223 연결 가정",
    )
    p.add_argument(
        "--stay-m32",
        action="store_true",
        help="제출 스텁 후 M31 복귀 생략 — 서식검증 화면에 유지",
    )
    return p.parse_args()


async def _find_wetax_page(browser):
    for ctx in browser.contexts:
        for pg in ctx.pages:
            try:
                if "wetax.go.kr" in (pg.url or ""):
                    return pg, ctx
            except Exception:
                continue
    ctx = browser.contexts[0] if browser.contexts else None
    if ctx is None:
        return None, None
    page = await ctx.new_page()
    return page, ctx


async def _wait_login(page, max_sec: int) -> bool:
    from src.automation.wetax._session import is_logged_in

    print(
        f"[WETAX] 로그인 대기 중... 전자세금용 공인인증서로 로그인해 주세요. "
        f"(최대 {max_sec}s)"
    )
    for i in range(max(1, max_sec // 5)):
        if await is_logged_in(page):
            print(f"[WETAX] 로그인 확인 ({(i + 1) * 5}s) url={page.url}")
            return True
        if i % 6 == 5:
            print(f"  ... 대기 {(i + 1) * 5}s  url={(page.url or '')[:80]}")
        await asyncio.sleep(5)
    return False


async def main() -> int:
    args = _parse_args()
    password = (args.password or "").strip()
    phone = (args.phone or "").strip()
    if not password:
        print("FAIL: --password 또는 WETAX_PASSWORD 필요 (전자신고 파일 비밀번호)")
        return 2
    if not phone:
        print("FAIL: --phone 또는 WETAX_PHONE 필요 (휴대전화번호)")
        return 2

    from src.automation.wetax._form import find_jitax_encrypted_file
    from src.automation.wetax._common import dismiss_popups, mask_phone
    from src.automation.wetax._session import is_logged_in
    from src.batch.state import NoopStateManager
    from src.utils.chrome_cdp import CDP_URL, check_cdp_available, launch_chrome
    from src.workflows.wetax_local_tax import WetaxLocalTaxWorkflow, resolve_stub_submit

    efile = find_jitax_encrypted_file(
        args.client, year=args.year, month=args.month
    )
    if not efile:
        print(
            f"FAIL: 전자신고 파일 없음 — "
            f"지방소득세전자신고_{args.year}{args.month:02d}/"
            f"{args.client.replace(' ', '_')}/ 아래 .1/.2 확인"
        )
        return 2
    print(f"[WETAX] client={args.client!r} period={args.year}-{args.month:02d}")
    print(f"[WETAX] efile={efile}")
    stub = resolve_stub_submit()
    print(
        f"[WETAX] phone={mask_phone(phone)} stub_submit={stub} "
        f"stay_on_m32={args.stay_m32}"
    )

    if not args.no_launch:
        print("[WETAX] Chrome CDP launch → wetax main.do")
        launched = launch_chrome(WETAX_MAIN)
        if not launched.get("success"):
            print(f"FAIL: Chrome 실행 실패: {launched.get('error')}")
            return 1
        print(
            f"[WETAX] chrome ok reused={launched.get('reused')} "
            f"pid={launched.get('pid')}"
        )
    elif not check_cdp_available():
        print("FAIL: CDP 9223 비활성 (--no-launch 인데 연결 불가)")
        return 1

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"FAIL: CDP 연결 실패: {e}")
            return 1

        page, context = await _find_wetax_page(browser)
        if page is None or context is None:
            print("FAIL: 페이지/컨텍스트 없음")
            return 1

        try:
            if "wetax.go.kr" not in (page.url or ""):
                await page.goto(WETAX_MAIN, wait_until="domcontentloaded", timeout=45000)
            else:
                # 이미 위택스면 main 으로 정리 (세션 유지)
                if "main.do" not in (page.url or "") and "login" not in (page.url or ""):
                    pass
                elif "logout" in (page.url or "").lower():
                    await page.goto(
                        WETAX_MAIN, wait_until="domcontentloaded", timeout=45000
                    )
            await asyncio.sleep(1)
            try:
                n = await dismiss_popups(page)
                print(f"[WETAX] 팝업 닫기 (로그인 전) actions={n}")
            except Exception as e:
                print(f"[WETAX] 팝업 닫기 스킵: {e}")
        except Exception as e:
            print(f"[WETAX] main.do 경고: {e}")

        if not await is_logged_in(page):
            ok = await _wait_login(page, args.login_timeout)
            if not ok:
                print("FAIL: 로그인 타임아웃")
                return 1
            await asyncio.sleep(0.8)
            try:
                n = await dismiss_popups(page)
                print(f"[WETAX] 팝업 닫기 (로그인 후) actions={n}")
            except Exception as e:
                print(f"[WETAX] 로그인 후 팝업 스킵: {e}")

        # 로그인 후 활성 탭이 바뀌었을 수 있음
        page2, context2 = await _find_wetax_page(browser)
        if page2 is not None:
            page, context = page2, context2 or context

        print(f"[WETAX] run_single 시작 url={page.url}")
        wf = WetaxLocalTaxWorkflow()
        state = NoopStateManager()
        ok = await wf.run_single(
            page,
            context,
            args.client,
            job_id=0,
            state=state,
            password=password,
            phone=phone,
            year=args.year,
            month=args.month,
            stay_on_m32=args.stay_m32,
        )
        print(f"[WETAX] run_single result={ok} url={page.url}")

        # stay-m32: 서식검증 요약·본문 일부 덤프
        try:
            from src.automation.wetax._form import get_convert_result_summary
            from src.automation.wetax._constants import (
                ACCOUNTING_CONVERT_RESULT_PATH,
                ACCOUNTING_FILE_REPORT_PATH,
            )

            summary = await get_convert_result_summary(page)
            print(
                f"[WETAX] post summary ok={summary.get('ok')} err={summary.get('err')} "
                f"url={summary.get('url')}"
            )
            url_now = page.url or ""
            if ACCOUNTING_CONVERT_RESULT_PATH in url_now:
                print("[WETAX] on M32 서식검증·제출 화면")
            elif ACCOUNTING_FILE_REPORT_PATH in url_now:
                print("[WETAX] still on M31 업로드 화면 (변환 미도착 또는 복귀됨)")
            try:
                body_snip = await page.evaluate(
                    """() => {
                      const t = (document.body && document.body.innerText) || '';
                      return t.replace(/\\s+/g, ' ').trim().slice(0, 500);
                    }"""
                )
                print(f"[WETAX] body_snip: {body_snip}")
            except Exception as e:
                print(f"[WETAX] body_snip skip: {e}")
        except Exception as e:
            print(f"[WETAX] post summary skip: {e}")

        try:
            name = (
                "wetax_drew_m32.png" if args.stay_m32 else "wetax_drew_live.png"
            )
            out = ROOT / "results" / name
            out.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(out), full_page=False)
            print(f"[WETAX] screenshot {out}")
        except Exception as e:
            print(f"[WETAX] screenshot skip: {e}")

        if ok:
            print("\n=== WETAX LIVE: SUCCESS ===")
            if stub and args.stay_m32:
                print("  (제출 스텁 · stay_on_m32 — 서식검증 화면 유지)")
            elif stub:
                print("  (제출 스텁 — 변환·M31 복귀. 실제출은 WETAX_STUB_SUBMIT 미설정)")
            elif args.stay_m32:
                print("  (제출 실클릭 · stay_on_m32 — 결과 화면 유지)")
            else:
                print("  (제출 실클릭 · M31 복귀)")
            return 0
        print("\n=== WETAX LIVE: FAIL ===")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

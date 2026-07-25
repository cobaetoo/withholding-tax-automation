"""위택스 다건(선택건) 라이브 — GUI start_selected_clients 와 동일 루프.

드류 전자신고 파일을 여러 수임처 폴더에 복제해 둔 뒤, 이름만 다른 수임처처럼
순차 run_single 한다.

기본: 제출 스텁(WETAX_STUB_SUBMIT=1) — 동일 파일 중복 실제출 방지.
  전화·비번 재입력 → 파일 교체 → 변환 → M31 복귀 루프 검증용.
실제출: --real-submit (동일 세무 데이터 N회 제출 위험 있음)

예:
  python scripts/run_wetax_multi_live.py ^
    --password test1234 --phone 010-1234-5678
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

DEFAULT_CLIENTS = [
    "주식회사 드류 다건A",
    "주식회사 드류 다건B",
    "주식회사 드류 다건C",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="위택스 다건 라이브")
    p.add_argument(
        "--clients",
        nargs="+",
        default=DEFAULT_CLIENTS,
        help="수임처명 목록 (기본: 드류 다건A/B/C)",
    )
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--month", type=int, default=7)
    p.add_argument(
        "--password",
        default=os.environ.get("WETAX_PASSWORD", ""),
    )
    p.add_argument(
        "--phone",
        default=os.environ.get("WETAX_PHONE", ""),
    )
    p.add_argument("--login-timeout", type=int, default=600)
    p.add_argument(
        "--real-submit",
        action="store_true",
        help="실제 제출 클릭 (기본은 스텁 — 동일 파일 중복제출 방지)",
    )
    p.add_argument(
        "--pause",
        type=float,
        default=0.0,
        help="수임처 사이·주요 단계 전 대기 초 (눈 확인용, 기본 0)",
    )
    p.add_argument(
        "--no-shot",
        action="store_true",
        help="종료 스크린샷 생략",
    )
    p.add_argument("--no-launch", action="store_true")
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
    return await ctx.new_page(), ctx


async def _wetax_logged_in(page) -> bool:
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


async def _wait_login(page, max_sec: int) -> bool:
    print(f"[MULTI] 로그인 대기... 전자세금용 공인인증서 (최대 {max_sec}s)")
    for i in range(max(1, max_sec // 5)):
        if await _wetax_logged_in(page):
            print(f"[MULTI] 로그인 확인 ({(i + 1) * 5}s)")
            return True
        if i % 6 == 5:
            print(f"  ... {(i + 1) * 5}s  {(page.url or '')[:80]}")
        await asyncio.sleep(5)
    return False


async def main() -> int:
    args = _parse_args()
    password = (args.password or "").strip()
    phone = (args.phone or "").strip()
    if not password or not phone:
        print("FAIL: --password / --phone 필요")
        return 2

    # 제출 스텁 토글 (모듈 로드 전 env 도 지원)
    if not args.real_submit:
        os.environ["WETAX_STUB_SUBMIT"] = "1"

    from src.automation.wetax._form import find_jitax_encrypted_file
    from src.automation.wetax._common import dismiss_popups, mask_phone
    from src.batch.state import NoopStateManager
    from src.utils.chrome_cdp import CDP_URL, check_cdp_available, launch_chrome
    import src.workflows.wetax_local_tax as wetax_wf
    from src.workflows.wetax_local_tax import WetaxLocalTaxWorkflow

    if not args.real_submit:
        wetax_wf._STUB_SUBMIT = True
    else:
        wetax_wf._STUB_SUBMIT = False

    clients = list(args.clients)
    print(f"[MULTI] clients={clients}")
    print(
        f"[MULTI] period={args.year}-{args.month:02d} phone={mask_phone(phone)} "
        f"stub_submit={wetax_wf._STUB_SUBMIT} real_submit={args.real_submit}"
    )
    if wetax_wf._STUB_SUBMIT:
        print(
            "[MULTI] 제출 스텁 모드 — 변환·M31 복귀 루프만 검증 "
            "(실제출은 --real-submit)"
        )

    for name in clients:
        path = find_jitax_encrypted_file(name, year=args.year, month=args.month)
        if not path:
            print(f"FAIL: 파일 없음 — {name}")
            return 2
        print(f"  efile OK {name}: {path}")

    if not args.no_launch:
        launched = launch_chrome(WETAX_MAIN)
        if not launched.get("success"):
            print(f"FAIL: Chrome: {launched.get('error')}")
            return 1
        print(f"[MULTI] chrome reused={launched.get('reused')} pid={launched.get('pid')}")
    elif not check_cdp_available():
        print("FAIL: CDP 비활성")
        return 1

    from playwright.async_api import async_playwright

    results: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        page, context = await _find_wetax_page(browser)
        if page is None:
            print("FAIL: page 없음")
            return 1

        try:
            if "wetax.go.kr" not in (page.url or ""):
                await page.goto(WETAX_MAIN, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(0.8)
            await dismiss_popups(page)
        except Exception as e:
            print(f"[MULTI] main 경고: {e}")

        if not await _wetax_logged_in(page):
            if not await _wait_login(page, args.login_timeout):
                print("FAIL: 로그인 타임아웃")
                return 1
            await asyncio.sleep(0.8)
            try:
                await dismiss_popups(page)
            except Exception:
                pass

        page2, context2 = await _find_wetax_page(browser)
        if page2 is not None:
            page, context = page2, context2 or context

        wf = WetaxLocalTaxWorkflow()
        total = len(clients)
        pause = max(0.0, float(args.pause or 0))
        for i, name in enumerate(clients):
            print(f"\n[MULTI] ({i + 1}/{total}) {name} 시작 url={page.url}")
            if pause:
                print(f"[MULTI] 시작 전 {pause}s 대기 — CDP 창 확인")
                await asyncio.sleep(pause)
            state = NoopStateManager()
            try:
                ok = await wf.run_single(
                    page,
                    context,
                    name,
                    job_id=0,
                    state=state,
                    password=password,
                    phone=phone,
                    year=args.year,
                    month=args.month,
                    stay_on_m32=False,  # 다음 건 위해 M31 복귀
                )
            except Exception as e:
                print(f"[MULTI] ({i + 1}/{total}) {name} 예외: {e}")
                results.append({"name": name, "ok": False, "error": str(e)})
                break
            print(f"[MULTI] ({i + 1}/{total}) {name} result={ok} url={page.url}")
            results.append({"name": name, "ok": ok, "url": page.url})
            if not ok:
                print(f"[MULTI] 실패 — 이후 수임처 중단 (선택건 러너와 유사하게 계속 가능하나 여기선 중단)")
                # GUI runner continues on fail if browser alive; multi smoke stops to inspect
                break
            # 수임처 간 대기 (pause 우선, 없으면 짧은 간격)
            if i + 1 < total:
                gap = pause if pause > 0 else 1.5
                print(f"[MULTI] 다음 수임처 전 {gap}s 대기")
                await asyncio.sleep(gap)

        if not args.no_shot:
            try:
                out = ROOT / "results" / "wetax_multi_live.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(out), full_page=False)
                print(f"[MULTI] screenshot {out}")
            except Exception as e:
                print(f"[MULTI] screenshot skip: {e}")
        else:
            print("[MULTI] screenshot skipped (--no-shot)")

    print("\n=== MULTI SUMMARY ===")
    for r in results:
        flag = "OK" if r.get("ok") else "FAIL"
        print(f"  [{flag}] {r.get('name')} {r.get('error', '')}")
    n_ok = sum(1 for r in results if r.get("ok"))
    print(f"  {n_ok}/{len(clients)} success  stub={wetax_wf._STUB_SUBMIT}")

    if n_ok == len(clients):
        print("\n=== WETAX MULTI: ALL PASS ===")
        return 0
    print("\n=== WETAX MULTI: PARTIAL/FAIL ===")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

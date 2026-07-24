"""지방소득세 특별징수 전자신고 자동화 (SWER0109) — 원천전자신고 run_swer0101.py 의 지방세 카운터파트.

원천전자신고(SWER0101)와 동일한 흐름: 같은 위하고(SmartA)에서 다른 메뉴로 들어가
지급기간 → 수임처 선택 → 제작(F4) → 변환파일 비밀번호 → 파일 제작 → 저장.

라이브 확인(2026-07-21, [테스트]리틀치프코리아):
  - 메뉴 코드 SWER0109 (click_menu SWSA0101 → goto_menu_page SWER0109 코드-스왑).
  - 지급기간 = 표준 구조(div4+sprite2) → set_period_fields 그대로 동작.
  - 수임처 picker + 코드도움 = SWER0101 과 동일.
  - 제작(F4) → '변환파일 비밀번호' 모달 + '전자신고 파일 제작(Enter)' 버튼 = SWER0101 과 동일
    → set_password_and_submit 재사용. (비밀번호 규칙만 다름: 영문 소문자+숫자만)
  - ★저장처: SWER0101 과 동일하게 WehagoNTS 폴더 저장으로 확인됨.
  - ★전제조건: 지방소득세특별징수납부서(SWTA0112)를 먼저 마감해야 전자신고 데이터가
    생성됨 (마감 안 하면 수임처 조회 시 데이터 없음 → 파일 미생성). 원천세의
    '원천이행상황 마감 → 원천전자신고 제작' 과 동일한 순서 의존성.

사전 조건:
- page 가 이미 SmartA 급여 페이지에 있어야 함
- Chrome CDP 모드(port 9223) 실행 상태
"""
import asyncio
import sys

from src.automation.wehago._common import (
    log, dismiss_dialogs, goto_menu_page, set_period_fields,
    click_codehelp_confirm, compute_target_period, click_menu,
)
from src.automation.wehago._nts import select_nts_folder
# 변환파일 비밀번호 입력 + 전자신고 파일 제작(Enter) — SWER0101 과 동일 메커니즘 재사용.
from src.automation.wehago.run_swer0101 import set_password_and_submit
from src.utils.human import net_mult

# 지방소득세 특별징수 전자신고 SmartA 메뉴 코드 (라이브 확인 2026-07-21, SWER 계열).
JITAX_EFILE_MENU_CODE = "SWER0109"


async def run_jitax_efile(page, password, nts_folder="지방소득세전자신고",
                          year: int = None, month: int = None,
                          save_dir: str = None):
    """지방소득세 특별징수 전자신고 전체 자동화. run_swer0101 과 동일 계약."""
    # [0] SPA 라우팅 초기화: SWSA0101 사이드바 클릭
    log("[JITAX_EFILE] 급여자료입력(SWSA0101) 사이드바 클릭 (SPA 라우팅 초기화)...")
    await click_menu(page, "SWSA0101")
    await asyncio.sleep(net_mult(3.0))
    await dismiss_dialogs(page)

    # [1] SWER0109 이동 (URL 경로 교체)
    log(f"[JITAX_EFILE] 지방소득세특별징수전자신고 이동 (menu={JITAX_EFILE_MENU_CODE})...")
    await goto_menu_page(page, JITAX_EFILE_MENU_CODE)
    await asyncio.sleep(net_mult(3.0))

    # 모달 닫기 (제출자등록 안내 등) + z-index overlay 정리 (SWER0101 동일)
    log("[JITAX_EFILE] 모달 확인...")
    await dismiss_dialogs(page)
    for _ in range(5):
        closed = await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 100) continue;
                    const txt = el.textContent.trim();
                    if (txt.length === 0) continue;
                    const btns = el.querySelectorAll('button');
                    for (const btn of btns) {
                        const t = btn.textContent.trim();
                        if ((t === '확인' || t === '닫기' || t === 'X') && btn.offsetWidth > 0) {
                            btn.click(); return t;
                        }
                    }
                } catch(e) {}
            }
            return null;
        }""")
        if not closed:
            break
        log(f"    overlay closed ({closed})")
        await asyncio.sleep(0.5)

    # [2] 지급기간 설정 (표준 구조 → set_period_fields 그대로)
    if year is None or month is None:
        year, month = compute_target_period()
    log(f"[JITAX_EFILE] 지급기간: {year}년 {month:02d}월")
    await set_period_fields(page, year, month, month)

    # [3] 수임처 아이콘 → 코드도움 확인 (SWER0101 동일)
    log("[JITAX_EFILE] 수임처 아이콘 클릭...")
    await page.evaluate("""() => {
        const items = document.querySelectorAll('#SearchMain .item');
        for (const item of items) {
            const title = item.querySelector('.item_title, strong');
            if (!title || !title.textContent.includes('수임처')) continue;
            const btns = item.querySelectorAll('button.WSC_LUXButton');
            for (const btn of btns) {
                const r = btn.getBoundingClientRect();
                if (r.width > 0 && r.height > 0 && !btn.textContent.trim()) {
                    btn.click(); return;
                }
            }
        }
    }""")
    await asyncio.sleep(net_mult(2.0))
    confirmed = await click_codehelp_confirm(page)
    log(f"  코드도움: {confirmed}")
    await asyncio.sleep(net_mult(2.0))

    # [4] 제작(F4) 버튼 클릭 — 잔여 다이얼로그(수임처 코드도움 등) 정리 후 클릭.
    #     ★어댑터 경로(사업자번호 재진입)에서 _isDialog WSC_LUXDialog 오버레이가 제작(F4)
    #     Playwright 클릭을 인터셉트하는 사례 확인 → dismiss 후 클릭, Playwright 실패 시
    #     JS 클릭 폴백(오버레이 pointer-events 인터셉트를 우회). 수임처 선택됨=버튼 활성.
    log("[JITAX_EFILE] 제작(F4) 클릭...")
    await dismiss_dialogs(page)
    await asyncio.sleep(net_mult(0.5))
    clicked_f4 = False
    try:
        f4_btn = page.locator('button.WSC_LUXButton:has-text("제작(F4)")')
        if await f4_btn.count() > 0:
            await f4_btn.first.click(timeout=5000)
            clicked_f4 = True
            log("  clicked (Playwright)")
    except Exception as e:
        log(f"  Playwright click 실패({type(e).__name__}) → 다이얼로그 정리 후 JS 폴백")
        await dismiss_dialogs(page)
    if not clicked_f4:
        js_ok = await page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button.WSC_LUXButton')) {
                if (btn.textContent.trim() === '제작(F4)' && btn.offsetWidth > 0) {
                    btn.click(); return true;
                }
            }
            return false;
        }""")
        log(f"  clicked (JS 폴백): {js_ok}")

    # [5] 모달 대기: 참고사항 vs 변환파일 비밀번호 (SWER0101 동일)
    log("[JITAX_EFILE] 모달 대기...")
    modal_found = False
    _f4_polls = 20
    for i in range(_f4_polls):
        await asyncio.sleep(net_mult(1.0))
        found = await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호'))
                    return 'pwd';
                if (d.offsetWidth > 100 && d.textContent.includes('참고사항'))
                    return 'ref';
            }
            return null;
        }""")
        if found:
            log(f"  [{i+1}s] modal: {found}")
            modal_found = True
            if found == "pwd":
                break
            elif found == "ref":
                log("  참고사항 모달 닫기...")
                await dismiss_dialogs(page)

    if not modal_found:
        raise RuntimeError(
            "[JITAX_EFILE] 제작(F4) 후 변환파일 비밀번호/참고사항 모달이 "
            f"{_f4_polls}회 폴링 내 미출현 — 네트워크 지연 또는 F4 처리 실패 의심."
        )

    # 비밀번호 모달 ready 대기
    _pwd_polls = 15
    for i in range(_pwd_polls):
        await asyncio.sleep(net_mult(1.0))
        if await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호'))
                    return true;
            }
            return false;
        }"""):
            log(f"  [{i+1}s] 비밀번호 modal ready")
            break
    else:
        raise RuntimeError(
            "[JITAX_EFILE] 변환파일 비밀번호 모달이 ready 상태에 도달하지 않음 "
            f"({_pwd_polls}회 폴링 초과) — 네트워크 지연 의심."
        )

    await asyncio.sleep(net_mult(2.0))

    # [6] 비밀번호 입력 + 전자신고 파일 제작 (SWER0101 set_password_and_submit 재사용)
    log("[JITAX_EFILE] 비밀번호 입력 + 전자신고 파일 제작...")
    success = await set_password_and_submit(page, password)
    if not success:
        raise RuntimeError(
            "[JITAX_EFILE] 변환파일 비밀번호 제출 실패(3회 재시도 후 실패) — "
            "비밀번호 규칙(영문 소문자+숫자) 미충족 또는 처리 실패."
        )

    # [7] 저장 — WehagoNTS 폴더 저장 (SWER0101 동일, 라이브 확인 2026-07-21).
    log("[JITAX_EFILE] WehagoNTS 폴더 선택...")
    loop = asyncio.get_event_loop()
    if save_dir:
        nts_ok = await loop.run_in_executor(None, select_nts_folder, None, save_dir)
    else:
        nts_ok = await loop.run_in_executor(None, select_nts_folder, nts_folder)

    if nts_ok:
        log("[JITAX_EFILE] 완료 - 전자신고 파일 저장 성공")
    else:
        log("[JITAX_EFILE] WARNING: NTS 폴더 선택 실패")


# ═══════════════════════════════════════════════════════════════════════
# 독립 실행 (스모크용 CDP-attach 진입점)
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import io

    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

    async def _main():
        from playwright.async_api import async_playwright
        from src.utils.chrome_cdp import launch_chrome, connect_page
        from src.automation.wehago._common import (
            wait_for_login, goto_salary_page,
        )

        company = input("수임처 이름: ").strip()
        password = input("전자신고 비밀번호(영문 소문자+숫자): ").strip()
        nts_folder = input("저장 폴더명 (기본=지방소득세전자신고): ").strip() or "지방소득세전자신고"

        if not company or not password:
            print("수임처 이름과 비밀번호가 필요합니다.")
            return

        launch_chrome()
        async with async_playwright() as p:
            browser, context, page = await connect_page(p)
            if not await wait_for_login(page):
                return
            await dismiss_dialogs(page)
            if not await goto_salary_page(page, company):
                return
            await dismiss_dialogs(page)

            await run_jitax_efile(page, password, nts_folder)

    asyncio.run(_main())

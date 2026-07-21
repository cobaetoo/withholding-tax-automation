"""지방소득세 특별징수 전자신고 자동화 — 스캐폴드 (원천전자신고 run_swer0101.py 의 지방세 카운터파트)

원천전자신고(SWER0101)와 동일한 개념: 같은 위하고(SmartA)에서 **다른 메뉴 페이지**로
들어가 지급기간 설정 → 수임처 선택 → 제작 → 비밀번호 → 파일 저장. 유일한 실질 차이는
SmartA 메뉴 코드(SWER0101 → 지방세 코드)와 저장처(WehagoNTS vs 위택스)이다.

★현재 상태(Part A 스캐폴드):
  - 네비게이션(SWSA0101 SPA 초기화 → 메뉴 코드 URL 교체)과 지급기간 설정은 SWER 재사용.
  - 메뉴 코드(JITAX_EFILE_MENU_CODE)와 온-페이지 로직(수임처 picker + 제작(F4) +
    변환파일 비밀번호 모달 + 저장처)은 라이브 발견 후 채운다.
  - 참고: 비밀번호 모달 로직이 SWER 과 동일하면 run_swer0101.set_password_and_submit 를
    재사용, 저장이 WehagoNTS 면 _nts.select_nts_folder 재사용(위택스면 별도 구현).

사전 조건:
- page 가 이미 SmartA 급여 페이지에 있어야 함
- Chrome CDP 모드(port 9223) 실행 상태
"""
import asyncio
import sys

from src.automation.wehago._common import (
    log, dismiss_dialogs, goto_menu_page, set_period_fields,
    compute_target_period, click_menu,
)
from src.utils.human import net_mult


# ═══════════════════════════════════════════════════════════════════════
# TODO(LIVE): 지방소득세 특별징수 전자신고 SmartA 메뉴 코드.
#   원천세 = "SWER0101". 캡처 방법은 run_jitax_payment.py 상단 주석과 동일
#   (사이드바 a#<CODE>.text_link id, [A-Z]+\d+ 형태).
JITAX_EFILE_MENU_CODE = "<<TODO_DISCOVER_LIVE>>"
# ═══════════════════════════════════════════════════════════════════════


async def run_jitax_efile(page, password, nts_folder="지방소득세전자신고",
                          year: int = None, month: int = None,
                          save_dir: str = None):
    """지방소득세 특별징수 전자신고 전체 자동화 (스캐폴드).

    Args 계약은 run_swer0101 과 동일. 현재는 네비게이션 + 지급기간까지만 수행하고
    온-페이지 로직(수임처/제작/비밀번호/저장)은 NotImplementedError.
    """
    # [0] SPA 라우팅 초기화: SWSA0101 사이드바 클릭
    log("[JITAX_EFILE] 급여자료입력(SWSA0101) 사이드바 클릭 (SPA 라우팅 초기화)...")
    await click_menu(page, "SWSA0101")
    await asyncio.sleep(net_mult(3.0))
    await dismiss_dialogs(page)

    # [1] 지방소득세 특별징수 전자신고 메뉴 이동 (URL 경로 교체)
    assert JITAX_EFILE_MENU_CODE != "<<TODO_DISCOVER_LIVE>>", (
        "[JITAX_EFILE] JITAX_EFILE_MENU_CODE 미설정 — 라이브 발견(Part B) 후 채울 것"
    )
    log(f"[JITAX_EFILE] 지방소득세특별징수전자신고 이동 (menu={JITAX_EFILE_MENU_CODE})...")
    await goto_menu_page(page, JITAX_EFILE_MENU_CODE)
    await asyncio.sleep(net_mult(3.0))
    await dismiss_dialogs(page)
    # LIVE-VERIFY: 진입 안내 모달/제출자등록 오버레이가 있으면 run_swer0101.py:169-193 의
    #   z-index overlay 정리 루프를 이식.

    # [2] 지급기간 설정 — SWER 미러.
    #     LIVE-VERIFY: set_period_fields DOM 호환(_common.py:1206) — 지방세 페이지 확인.
    if year is None or month is None:
        year, month = compute_target_period()
    log(f"[JITAX_EFILE] 지급기간: {year}년 {month:02d}월")
    await set_period_fields(page, year, month, month)

    # ═══════════════════════════════════════════════════════════════════════
    # TODO(LIVE): 지방소득세 전자신고 온-페이지 로직 (원천전자신고 SWER 미러):
    #   - 수임처 아이콘 클릭 + 코드도움 확인  (run_swer0101.py:202-220)
    #   - 제작(F4) 클릭                       (run_swer0101.py:222-244)
    #   - 변환파일 비밀번호 모달 대기/입력     (run_swer0101.py:245-312;
    #                                          동일하면 set_password_and_submit 재사용)
    #   - 파일 저장  ★NTS(_nts.select_nts_folder) vs 위택스/기타 — 라이브 확인 필수.
    #   확정 전까지 loud 실패(전자신고 파일 미산출을 성공으로 오인 방지).
    # ═══════════════════════════════════════════════════════════════════════
    raise NotImplementedError(
        "[JITAX_EFILE] 온-페이지 로직 미구현 — 라이브 발견(Part B) 후 구현. "
        f"현재 네비게이션+지급기간까지만 검증 가능(menu={JITAX_EFILE_MENU_CODE})."
    )


# ═══════════════════════════════════════════════════════════════════════
# 독립 실행 (Part B 라이브 발견/스모크용 CDP-attach 진입점)
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
        password = input("전자신고 비밀번호: ").strip()
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

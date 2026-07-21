"""지방소득세 특별징수 납부서 자동화 (SWTA0112) — 원천세 SWTA0101 의 지방세 카운터파트.

동작: '마감만' (원천징수이행상황신고서와 동일 목표). 단 페이지 위젯이 달라 전용 로직 사용:
  기간(귀속년월=월 단일 / 지급년월=연·월 범위) → 조회(회색 LUX_basic_btn '조회') → 마감.
  마감/마감해제/재조회/재마감 처리는 run_swta0101 헬퍼(WSC_LUXButton 기반) 재사용.
  신고구분(매월/반기)은 이 화면에 라디오가 없어 '신고 : 매월/반기' 라벨을 ground truth 로 읽음.

라이브 확인(2026-07, [테스트]리틀치프코리아 매월·끽비어컴퍼니 반기):
  - 메뉴 코드 SWTA0112 (click_menu SWSA0101 → goto_menu_page SWTA0112 코드-스왑).
  - 귀속년월 div=['MM'](연도 사업연도 고정), 지급년월 div=['YYYY','MM','YYYY','MM'].
  - 조회=button.LUX_basic_btn(WSC_LUXButton 아님), 마감=button.WSC_LUXButton.
  - 반기도 라이브 확인 — 6·12월에만 실행, 귀속=반기 종료월(원천세와 동일).

사전 조건:
- page 가 이미 SmartA 급여 페이지에 있어야 함
- Chrome CDP 모드(port 9223) 실행 상태
"""
import asyncio
import sys

from src.automation.wehago._common import (
    log, dismiss_dialogs, goto_menu_page, compute_target_period, click_menu,
)
# 마감/마감해제 버튼 읽기·대기 헬퍼(제네릭, WSC_LUXButton '마감'/'마감해제') 재사용.
# 단 확인 모달은 SWTA0112 가 '마감(F3)'(원천세는 '확인')이라 로컬 _click_modal_button 사용.
from src.automation.wehago.run_swta0101 import (
    _wait_close_button, _read_close_button, compute_half_period, half_period_target,
)
from src.utils.human import net_mult

# 지방소득세 특별징수 납부서 SmartA 메뉴 코드 (라이브 확인 2026-07-21, SWTA 계열).
JITAX_PAYMENT_MENU_CODE = "SWTA0112"


async def _read_jitax_cycle(page) -> str:
    """'신고 : 매월/반기' 라벨에서 신고구분 읽기(라디오 없음 → 라벨이 ground truth)."""
    txt = await page.evaluate("""() => {
        const items = document.querySelectorAll('#SearchMain .item');
        for (const it of items) {
            const t = (it.querySelector('.item_title, strong')?.textContent || '').trim();
            if (t.includes('신고')) return t;
        }
        return '';
    }""")
    if "반기" in txt:
        return "반기"
    if "매월" in txt:
        return "매월"
    return ""


async def _set_year_div(page, item_idx: int, div_i: int, year: int) -> None:
    """item#idx 의 div[tabindex=0][div_i] 에 연도 입력(3연클릭 → 타이핑 → Enter)."""
    rect = await page.evaluate("""(a) => {
        const item = document.querySelectorAll('#SearchMain .item')[a.idx];
        if (!item) return null;
        const d = item.querySelectorAll('div[tabindex="0"]')[a.i];
        if (!d) return null;
        const r = d.getBoundingClientRect();
        return {x: r.x, y: r.y, w: r.width, h: r.height};
    }""", {"idx": item_idx, "i": div_i})
    if not rect:
        return
    await page.mouse.click(rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2, click_count=3)
    await asyncio.sleep(net_mult(0.3))
    await page.keyboard.type(str(year))
    await page.keyboard.press("Enter")
    await asyncio.sleep(net_mult(0.5))


async def _select_month(page, item_idx: int, sprite_i: int, month: int) -> bool:
    """item#idx 의 sprite[sprite_i] 드롭다운을 열고 열린 목록의 li 중 MM 선택.

    ★페이지에 이미 표시된 다른 'MM' div(귀속년월 등)와 충돌하지 않도록 li 로 한정한다
      (naive textContent 매칭은 귀속년월 div 를 잘못 클릭 — 라이브에서 확인된 함정).
    """
    await page.evaluate("""(a) => {
        const item = document.querySelectorAll('#SearchMain .item')[a.idx];
        if (!item) return;
        const b = item.querySelectorAll('button .WSC_LUXSpriteIcon')[a.i]?.closest('button');
        if (b) b.click();
    }""", {"idx": item_idx, "i": sprite_i})
    await asyncio.sleep(net_mult(1.0))
    ok = await page.evaluate("""(t) => {
        const lis = document.querySelectorAll('li');
        for (const li of lis) {
            if (li.offsetWidth > 0 && li.textContent.trim() === t) { li.click(); return true; }
        }
        return false;
    }""", f"{month:02d}")
    # ★드롭다운 닫기 강제 금지: display:none(공유 컨테이너 숨김) 도, Escape(월 선택 취소/
    #   되돌림) 도 라이브에서 지급년월 월선택을 깨뜨렸다. li 클릭 자체가 값 커밋 + 드롭다운
    #   닫기를 수행하므로 settle sleep 만 둔다.
    await asyncio.sleep(net_mult(0.6))
    return ok


async def _read_period_state(page):
    """귀속년월(월)·지급년월(연/월) 현재값 읽기(검증용). 제목 기반 item 탐색."""
    return await page.evaluate("""() => {
        const grab = (it) => it ? [...it.querySelectorAll('div[tabindex="0"]')].map(d => d.textContent.trim()) : null;
        let gui = null, jigeup = null;
        document.querySelectorAll('#SearchMain .item').forEach((it) => {
            const t = (it.querySelector('.item_title, strong')?.textContent || '').trim();
            if (t.includes('귀속년월')) gui = grab(it);
            else if (t.includes('지급년월')) jigeup = grab(it);
        });
        return {gui, jigeup};
    }""")


async def _set_jitax_period(page, year: int, start_month: int, end_month: int) -> None:
    """SWTA0112 기간 설정 (매월/반기 공통). 3회 검증.

    - 귀속년월(단일) = end_month  (매월=대상월, 반기=반기 종료월; 연도는 사업연도 고정)
    - 지급년월(범위) = year/start_month ~ year/end_month
      (매월 start==end, 반기 상반기=01~06 / 하반기=07~12)  — 라이브 확인 값.
    """
    y = str(year)
    sm, em = f"{start_month:02d}", f"{end_month:02d}"
    for attempt in range(1, 4):
        # ★순서 불변식(라이브 확인): 귀속년월을 건드리면 지급년월 '월'이 blank 로 초기화된다.
        #   따라서 반드시 귀속을 먼저, 지급을 마지막에 설정한다.
        # 1) 귀속년월 = 종료월(단일). (연도는 사업연도 고정 텍스트)
        await _select_month(page, 0, 0, end_month)
        # 2) 지급년월 연도 보정 — 목표와 다를 때만(매월은 기본 사업연도, 반기는 공란일 수 있음).
        pre = await _read_period_state(page)
        jg = pre.get("jigeup") or ["", "", "", ""]
        if len(jg) >= 3 and (jg[0] != y or jg[2] != y):
            await _set_year_div(page, 1, 0, year)
            await _set_year_div(page, 1, 2, year)
        # 3) 지급년월 시작월 → (범위가 다르면) 종료월. 시작만 선택 시 종료 자동연동(매월).
        await _select_month(page, 1, 0, start_month)
        if start_month != end_month:
            await _select_month(page, 1, 1, end_month)

        await asyncio.sleep(net_mult(0.3))
        state = await _read_period_state(page)
        gui_ok = state.get("gui") == [em]
        jigeup_ok = state.get("jigeup") == [y, sm, y, em]
        log(f"    [JITAX_PAY] 기간 검증(시도 {attempt}): 귀속={state.get('gui')} 지급={state.get('jigeup')}")
        if gui_ok and jigeup_ok:
            return
        await asyncio.sleep(net_mult(0.5))
    raise RuntimeError(
        f"[JITAX_PAY] 기간 설정 검증 실패(3회): 귀속년월={em} / 지급년월={y}/{sm}~{y}/{em} 로 "
        f"세팅되지 않음 — 위젯 구조 변경 의심."
    )


async def _click_jitax_search(page) -> None:
    """지방세 납부서 화면의 '조회'(회색 LUX_basic_btn, 화면 최우측) 클릭 후 모달 정리."""
    clicked = await page.evaluate("""() => {
        const btns = [...document.querySelectorAll('button')]
            .filter(b => b.textContent.trim() === '조회' && b.offsetWidth > 0);
        if (!btns.length) return false;
        btns.sort((a, b) => {   // 우측끝(x+width) 큰 것 우선 = 가장 오른쪽 조회
            const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
            return (rb.x + rb.width) - (ra.x + ra.width);
        });
        btns[0].click();
        return true;
    }""")
    if not clicked:
        raise RuntimeError("[JITAX_PAY] 조회 버튼(회색 LUX_basic_btn '조회')을 찾지 못함.")
    log("  [JITAX_PAY] 조회 클릭")
    await asyncio.sleep(net_mult(2.0))
    await dismiss_dialogs(page)


async def _click_modal_button(page, texts, max_polls: int = 15, interval: float = 0.5):
    """열린 모달(._isDialog / .LUX_basic_dialog)에서 texts 중 하나와 일치하는 버튼 클릭.

    SWTA0112 마감 확인 모달은 '마감(F3)'(원천세 '확인'과 다름). 확정 버튼 텍스트를
    리스트로 받아 폴링 클릭한다. 클릭한 텍스트 반환, 못 찾으면 None.
    """
    for _ in range(max_polls):
        await asyncio.sleep(net_mult(interval))
        clicked = await page.evaluate("""(texts) => {
            const dialogs = document.querySelectorAll('._isDialog, .LUX_basic_dialog');
            for (const d of dialogs) {
                const cs = window.getComputedStyle(d);
                if (cs.display === 'none' || d.offsetWidth < 30) continue;
                for (const btn of d.querySelectorAll('button')) {
                    const t = btn.textContent.trim();
                    if (texts.includes(t) && btn.offsetWidth > 0) { btn.click(); return t; }
                }
            }
            return null;
        }""", texts)
        if clicked:
            return clicked
    return None


async def _apply_jitax_close(page) -> str | None:
    """마감 버튼 클릭 → '마감 리스트' 확인 모달의 '마감(F3)' 클릭 → 후속 모달 확인.

    Returns: 마감 적용 후 버튼 텍스트("마감해제" 예상).
    """
    log("  [JITAX_PAY] 마감 버튼 클릭 (마감 적용)...")
    await page.evaluate("""() => {
        for (const b of document.querySelectorAll('button.WSC_LUXButton')) {
            if (b.textContent.trim() === '마감' && b.offsetWidth > 0) { b.click(); return; }
        }
    }""")
    # 1) '마감 리스트' 확인 모달 → '마감(F3)'
    clicked = await _click_modal_button(page, ["마감(F3)"], max_polls=15, interval=0.5)
    if clicked:
        log(f"  마감 확인 모달 클릭: {clicked}")
    # 2) 후속 '마감 완료' 등 안내 모달 → 확인/마감(F3)
    await asyncio.sleep(net_mult(2.0))
    clicked2 = await _click_modal_button(page, ["확인(enter)", "확인", "마감(F3)"], max_polls=6)
    if clicked2:
        log(f"  후속 모달 클릭: {clicked2}")
        await asyncio.sleep(net_mult(1.0))
    await asyncio.sleep(net_mult(1.0))
    new_btn = await _read_close_button(page)
    log(f"  마감 후 버튼 상태: {new_btn}")
    return new_btn


async def run_jitax_payment(page, year: int = None, month: int = None,
                            report_cycle: str = "", client_id: int = None) -> str:
    """지방소득세 특별징수 납부서 마감 자동화. 사용된 신고구분("매월"/"반기") 반환.

    Args/Returns 계약은 run_swta0101 과 동일(주기 문자열 반환 → 어댑터 역충전).
    """
    # [0] SPA 라우팅 초기화
    log("[JITAX_PAY] 급여자료입력(SWSA0101) 사이드바 클릭 (SPA 라우팅 초기화)...")
    await click_menu(page, "SWSA0101")
    await asyncio.sleep(net_mult(3.0))
    await dismiss_dialogs(page)

    # [1] 지방소득세특별징수납부서(SWTA0112) 이동
    log(f"[JITAX_PAY] 지방소득세특별징수납부서 이동 (menu={JITAX_PAYMENT_MENU_CODE})...")
    await goto_menu_page(page, JITAX_PAYMENT_MENU_CODE)
    await asyncio.sleep(net_mult(3.0))
    await dismiss_dialogs(page)

    # [2] 신고구분: DB report_cycle 우선, 없으면 '신고 : 매월/반기' 라벨(ground truth)
    cycle = (report_cycle or "").strip()
    page_cycle = await _read_jitax_cycle(page)
    if cycle not in ("매월", "반기"):
        log(f"[JITAX_PAY] 신고구분: DB='{cycle or '비어있음'}' → 페이지 라벨='{page_cycle}'")
        cycle = page_cycle
    else:
        log(f"[JITAX_PAY] 신고구분: DB report_cycle='{cycle}' (페이지 라벨='{page_cycle}')")

    if cycle not in ("매월", "반기"):
        raise RuntimeError(
            "[JITAX_PAY] 신고구분 확정 불가(DB 공란 + 페이지 라벨 판별 실패). 마감 중단."
        )

    # [3] 기간 설정
    if cycle == "반기":
        # 원천세와 동일: 6·12월만 실행. 상반기=(y,1,6)/하반기=(y,7,12). 귀속=종료월.
        target, skip = half_period_target(year, month)
        if skip:
            log(f"[JITAX_PAY] 반기 → 비신고월({target.month}월) 스킵 (반기는 6·12월만)")
            return "반기"
        y, sm, em = compute_half_period(target)
        half = "상반기(01~06)" if sm == 1 else "하반기(07~12)"
        log(f"[JITAX_PAY] 반기 → {y}년 {sm:02d}~{em:02d}월 ({half})")
        await _set_jitax_period(page, y, sm, em)
    else:  # 매월
        if year is None or month is None:
            year, month = compute_target_period()
        log(f"[JITAX_PAY] 매월 → {year}년 {month:02d}월")
        await _set_jitax_period(page, year, month, month)

    # [4] 조회
    await _click_jitax_search(page)

    # [5] 마감/마감해제 처리 (마감 확인 모달 '마감(F3)' — SWTA0112 전용)
    log("[JITAX_PAY] 마감 상태 확인...")
    btn_text = await _wait_close_button(page)
    if btn_text == "마감":
        result = await _apply_jitax_close(page)
        if result != "마감해제":
            raise RuntimeError(
                f"[JITAX_PAY] 마감 후 버튼이 '{result}' (예상 '마감해제') — 마감 미완료 의심."
            )
    elif btn_text == "마감해제":
        # 이미 마감 → 마감해제 → 재조회 → 재마감 (SWTA 동일 정책: 최신 자료로 재마감)
        log("  [JITAX_PAY] 마감해제 클릭 (해제 후 재마감)...")
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button.WSC_LUXButton');
            for (const btn of btns) {
                if (btn.textContent.trim() === '마감해제' && btn.offsetWidth > 0) { btn.click(); return; }
            }
        }""")
        # 마감해제 확인 모달(버튼 텍스트 유동 — 마감해제(F3)/확인 등) 폴링 클릭
        clicked = await _click_modal_button(
            page, ["마감해제(F3)", "확인(enter)", "확인", "마감(F3)"], max_polls=15)
        if clicked:
            log(f"  마감해제 확인 모달 클릭: {clicked}")
        clicked2 = await _click_modal_button(page, ["확인(enter)", "확인"], max_polls=5)
        if clicked2:
            log(f"  후속 모달 클릭: {clicked2}")
        await asyncio.sleep(net_mult(1.0))
        new_btn = await _read_close_button(page)
        if new_btn != "마감":
            raise RuntimeError(
                f"[JITAX_PAY] 마감해제 확인 실패: 버튼이 '{new_btn}' (예상 '마감')."
            )
        log(f"  마감해제 완료 후 버튼 상태: {new_btn}")
        await _click_jitax_search(page)          # 재조회
        new_btn = await _wait_close_button(page)
        if new_btn != "마감":
            raise RuntimeError(
                f"[JITAX_PAY] 재조회 후 마감 버튼 상태가 '{new_btn}' (예상 '마감'). 재마감 불가."
            )
        result = await _apply_jitax_close(page)  # 재마감
        if result != "마감해제":
            raise RuntimeError(
                f"[JITAX_PAY] 재마감 후 버튼이 '{result}' (예상 '마감해제') — 재마감 미완료 의심."
            )
    else:
        raise RuntimeError(
            f"[JITAX_PAY] 마감/마감해제 버튼을 찾지 못함 (current={btn_text!r}). "
            "잘못된 기간·잔여 모달·미렌더링 의심 — 확인 후 재실행."
        )

    await dismiss_dialogs(page)
    log("[JITAX_PAY] 완료")
    return cycle


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
        if not company:
            print("수임처 이름이 필요합니다.")
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

            await run_jitax_payment(page)

    asyncio.run(_main())

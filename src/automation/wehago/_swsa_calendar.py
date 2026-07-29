"""SWSA0101 귀속연월 설정 모듈 (React LS_calendar)

SWSA0101은 SWTA/SWER와 다른 React 기반 달력(LS_calendar)을 사용.
Playwright locator.click으로 캘린더 열고, React setState로 연도 변경 후 월 선택.
"""

import asyncio
import sys

from src.automation.wehago._common import log, _safe_evaluate
from src.automation.wehago._swsa_constants import (
    _READ_SWSA_YM_JS,
    _READ_CALENDAR_YEAR_JS,
    _REACT_SET_CALENDAR_YEAR_JS,
    _FIND_SEARCH_ITEM_IDX_JS,
    _READ_SEARCH_ITEM_JS,
    SEARCH_ITEM_YM,
    SEARCH_ITEM_PAY_DATE,
)


# ═══════════════════════════════════════════════════════════════════════
# 검색영역(#SearchMain) 항목 접근 — 제목 기반 (위치 하드코딩 금지)
# ═══════════════════════════════════════════════════════════════════════

async def read_search_item(page, title: str) -> str:
    """검색영역 항목의 현재 표시값(.fakeinput) 반환. 항목이 없으면 None."""
    return await _safe_evaluate(page, _READ_SEARCH_ITEM_JS, title)


async def find_search_item_index(page, title: str) -> int:
    """검색영역에서 제목이 일치하는 .item 의 인덱스. 없으면 -1."""
    idx = await _safe_evaluate(page, _FIND_SEARCH_ITEM_IDX_JS, title)
    return idx if isinstance(idx, int) else -1


async def open_search_calendar(page, title: str) -> bool:
    """제목으로 검색영역 항목을 찾아 그 항목의 달력을 연다.

    ★해상도 무관: 좌표를 계산하지 않고 Playwright locator 로 요소 자체를 클릭한다.
      (JS evaluate click 은 합성 이벤트라 LS_calendar 가 열리지 않는다 —
       기존 set_swsa_ym 주석과 동일한 함정.)
    """
    idx = await find_search_item_index(page, title)
    if idx < 0:
        log(f"    [{title}] 검색영역에 항목 없음")
        return False
    try:
        await page.locator("#SearchMain .item").nth(idx).locator(
            ".fakebutton"
        ).first.click(timeout=5000)
        await asyncio.sleep(1)
        return True
    except Exception as e:
        log(f"    [{title}] 달력 열기 실패: {e}")
        return False


async def set_swsa_ym(page, year: int, month: int) -> bool:
    """SWSA0101 귀속연월 설정 (React LS_calendar component)

    SWSA0101은 SWTA/SWER와 다른 React 기반 달력(LS_calendar)을 사용.
    Playwright locator.click으로 캘린더 열고, React setState로 연도 변경 후 월 선택.

    Args:
        page: SWSA0101 페이지에 위치한 Playwright page
        year: 목표 연도 (예: 2026)
        month: 목표 월 (1-12)

    Returns:
        True if 귀속연월 설정 성공, False otherwise
    """
    target_ym = f"{year}.{month:02d}"

    for attempt in range(3):
        log(f"    [귀속연월] 시도 {attempt+1}/3: {target_ym}")

        # ── 현재 값 읽기 ──────────────────────────────────────
        cur_ym = await _safe_evaluate(page, _READ_SWSA_YM_JS)
        if cur_ym == target_ym:
            log(f"    [귀속연월] 이미 {target_ym} — 스킵")
            return True

        log(f"    [귀속연월] 현재: {cur_ym} → 목표: {target_ym}")

        # ── 캘린더 열기 (반드시 Playwright click — JS evaluate는 합성 이벤트) ──
        # 제목 기반 조회. 과거엔 '.item:first-child' 로 위치를 고정했는데, 그러면
        # 지급일 등 다른 항목에는 재사용할 수 없다(open_search_calendar 로 일반화).
        if not await open_search_calendar(page, SEARCH_ITEM_YM):
            await asyncio.sleep(1)
            continue

        # ── 연도 확인 및 React setState ──────────────────────
        cal_yr_text = await _safe_evaluate(page, _READ_CALENDAR_YEAR_JS)
        if not cal_yr_text:
            log("    [귀속연월] 캘린더 연도 읽기 실패")
            await asyncio.sleep(1)
            continue

        try:
            cal_yr = int(cal_yr_text)
        except (ValueError, TypeError):
            cal_yr = None

        if cal_yr is not None and cal_yr != year:
            log(f"    [귀속연월] React setState: {cal_yr} → {year}")
            result = await _safe_evaluate(
                page, _REACT_SET_CALENDAR_YEAR_JS, year,
            )
            if not result or not result.get("success"):
                log(f"    [귀속연월] React setState 실패: {result}")
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(1)

            # 연도 변경 확인
            new_cal_yr = await _safe_evaluate(page, _READ_CALENDAR_YEAR_JS)
            if new_cal_yr != str(year):
                log(f"    [귀속연월] 연도 변경 확인 실패: {new_cal_yr}")
                await asyncio.sleep(1)
                continue

        # ── 월 클릭 ──────────────────────────────────────────
        try:
            month_btn = page.locator(
                f'.LS_calendar td.date_day button:has-text("{month}월")'
            )
            await month_btn.first.click(timeout=3000)
            await asyncio.sleep(1)
        except Exception as e:
            log(f"    [귀속연월] {month}월 클릭 실패: {e}")
            await asyncio.sleep(1)
            continue

        # ── 최종 검증 ────────────────────────────────────────
        final_ym = await _safe_evaluate(page, _READ_SWSA_YM_JS)
        if final_ym == target_ym:
            log(f"    [귀속연월] 설정 완료: {target_ym}")
            return True

        log(f"    [귀속연월] 검증 실패: {final_ym} (예상: {target_ym})")
        await asyncio.sleep(1)

    log(f"    [귀속연월] 3회 재시도 후 실패")
    return False


# ═══════════════════════════════════════════════════════════════════════
# 지급일
# ═══════════════════════════════════════════════════════════════════════

async def ensure_swsa_pay_date(page, refill=None) -> str:
    """지급일이 채워져 있는지 확인하고, 비어 있으면 WEHAGO 기본값으로 복구.

    귀속연월만 넣고 조회하면 결과가 불완전하다 — 지급일까지 채워져야 해당 회차가
    정확히 조회된다. 지급일은 '구분'(급여+상여 등) 선택 시 WEHAGO 가 자동으로
    채워주므로, **우리가 날짜를 지어내지 않고 그 기본값을 그대로 쓴다.**
    비어 있을 때만 refill(구분 재선택)로 자동 채움을 다시 유도한다.

    Args:
        page: SWSA0101 페이지
        refill: 지급일이 비었을 때 호출할 async 콜백(구분 재선택 등). None 이면 생략.

    Returns:
        확정된 지급일 문자열(예: '2026.07.25').

    Raises:
        RuntimeError: 복구 후에도 지급일이 비어 있는 경우. 조용히 진행하면
            불완전 조회 상태로 PDF 를 뽑게 되므로 여기서 중단한다.
    """
    val = await read_search_item(page, SEARCH_ITEM_PAY_DATE)
    if val:
        log(f"    [지급일] {val} (WEHAGO 기본값 사용)")
        return val

    log("    [지급일] 비어 있음 — 자동 채움 재시도")
    for attempt in range(2):
        if refill is not None:
            try:
                await refill()
            except Exception as e:
                log(f"    [지급일] 재채움 콜백 실패(무시): {e}")
        await asyncio.sleep(1.5)
        val = await read_search_item(page, SEARCH_ITEM_PAY_DATE)
        if val:
            log(f"    [지급일] 복구됨: {val}")
            return val
        log(f"    [지급일] 재시도 {attempt + 1}/2 후에도 비어 있음")

    raise RuntimeError(
        "[SWSA0101] 지급일이 비어 있어 조회가 불완전합니다. "
        "귀속연월/구분 설정 후에도 지급일이 자동 채워지지 않았습니다 — "
        "해당 귀속연월에 급여 자료가 없는지 확인하세요."
    )

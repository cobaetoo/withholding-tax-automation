"""SWSA0101 (급여자료입력) 전용 상수

JS 상수 문자열(React LS_calendar) + Windows PrintDialog 상수.
"""

import sys

# ─── Windows PrintDialog 상수 ─────────────────────────────────────────────────
PRINT_DIALOG_TITLE_RE = r"Duzon.*PrintDialog"
PRINT_DIALOG_CLASS_RE = r"WindowsForms10\.Window.*"
SAVE_DIALOG_CLASS = "#32770"
DEFAULT_PRINT_FORMAT = "급여명세(사원당 한장)"

# 급여명세 PDF 페이즈(6번)에서 수임처별로 함께 다운로드할 인쇄형태 목록.
# 같은 수임처 폴더에 각각 저장.
# ★cbContents 드롭다운 "상단→하단" 순서로 기재★ — click_input 선택이 스크롤 위치의
# 영향을 받아, 역순(하단→상단) 선택 시 스크롤 업이 꼬여 잘못된 항목이 선택된다.
# cbContents 순서: 급여명세(구)[0], 급여대장[1], ..., 급여명세(사원당 한장)[5], ...
# 급여대장[1](상단)을 먼저, 급여명세(사원당 한장)[5](하단)을 나중에 받는다.
SALARY_PDF_FORMATS = ["급여대장", DEFAULT_PRINT_FORMAT]

# ─── 웹 모달 중간 단계 (2026-07 WEHAGO 개편) ─────────────────────────────────
# ★버그 원인★ 과거엔 #print → '일괄출력' 메뉴 클릭만으로 Duzon PrintDialog 가 떴다.
#   지금은 그 사이에 브라우저 내 모달 '급여대장 일괄인쇄'(z=1200, Canvas 미리보기)가
#   끼어들고, **그 모달 안의 [일괄출력] 버튼을 한 번 더 눌러야** PrintDialog 가 뜬다.
#   이 단계가 없어 open_print_dialog 가 30초 타임아웃 → PDF 0건이 되었다.
#   PrintDialog(자체)와 cbContents/btnSavePDF/'다른 이름으로 저장'은 그대로 유효하다.
BULK_MODAL_TITLE = "급여대장 일괄인쇄"
BULK_MODAL_PRINT_BTN = "일괄출력"      # ← 이 버튼이 PrintDialog 를 띄운다
BULK_MODAL_PDF_BTN = "일괄PDF저장"     # (대안 경로: 폴더 일괄 저장. 인쇄형태 선택 불가)
BULK_MODAL_CLOSE_BTN = "닫기(Esc)"

# 회차 그리드 식별용 키 컬럼(귀속월).
# getActiveGrid() 는 포커스에 따라 다른 그리드를 반환하므로(실측) 이 컬럼으로 검증한다.
PERIOD_GRID_KEY_COL = "ym_rvrs"

# 검색영역(#SearchMain) 항목 제목
SEARCH_ITEM_YM = "귀속연월"
SEARCH_ITEM_PAY_DATE = "지급일"


# ═══════════════════════════════════════════════════════════════════════════════
# SWSA0101 귀속연월 설정용 JS 상수 (React LS_calendar)
# ═══════════════════════════════════════════════════════════════════════════════

_READ_SWSA_YM_JS = """() => {
    const items = document.querySelectorAll('#SearchMain .item');
    for (const item of items) {
        const title = item.querySelector('.item_title, strong');
        if (title && title.textContent.trim() === '귀속연월') {
            return item.querySelector('.fakeinput')?.textContent.trim() || '';
        }
    }
    return '';
}"""

_READ_CALENDAR_YEAR_JS = """() => {
    return document.querySelector('.LS_calendar .date_day_title')?.textContent.trim() || '';
}"""

# ── 검색영역 항목 범용 접근 (제목 기반 — 위치 하드코딩 금지) ──────────────────
# 구 set_swsa_ym 은 '#SearchMain .item:first-child' 로 첫 항목만 열 수 있었다.
# 지급일은 3번째 항목이라 제목으로 인덱스를 찾아 locator().nth(idx) 로 접근한다.
_FIND_SEARCH_ITEM_IDX_JS = """(title) => {
    const items = document.querySelectorAll('#SearchMain .item');
    for (let i = 0; i < items.length; i++) {
        const t = items[i].querySelector('.item_title, strong');
        if (t && t.textContent.trim() === title) return i;
    }
    return -1;
}"""

_READ_SEARCH_ITEM_JS = """(title) => {
    for (const it of document.querySelectorAll('#SearchMain .item')) {
        const t = it.querySelector('.item_title, strong');
        if (t && t.textContent.trim() === title) {
            return it.querySelector('.fakeinput')?.textContent.trim() || '';
        }
    }
    return null;
}"""

# ── 웹 모달 버튼: 최상위(z 최대) 오버레이에서 라벨 정확일치 버튼의 실시간 rect 중심 ──
# ★해상도 무관★ 좌표 상수를 쓰지 않고 getBoundingClientRect() 로 매번 계산한다.
#   LUX 버튼은 JS .click() 이 무시되는 경우가 있어 real mouse click 이 필요하다.
_TOP_MODAL_BUTTON_RECT_JS = """(label) => {
    let best = null, bestZ = -1;
    for (const el of document.querySelectorAll('*')) {
        const cs = getComputedStyle(el);
        if (cs.position !== 'fixed' && cs.position !== 'absolute') continue;
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        const z = parseInt(cs.zIndex);
        if (!(z >= 1000)) continue;
        for (const b of el.querySelectorAll('button')) {
            if (b.offsetWidth > 0 && b.textContent.trim() === label && z >= bestZ) {
                best = b; bestZ = z;
            }
        }
    }
    if (!best) return null;
    const r = best.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    return {x: r.left + r.width / 2, y: r.top + r.height / 2, z: bestZ};
}"""

# 회차 그리드 조회 — 키 컬럼 유무로 "지금 활성 그리드가 맞는지" 검증
_PERIOD_GRID_INFO_JS = """(keyCol) => {
    const g = window.Grids && window.Grids.getActiveGrid && window.Grids.getActiveGrid();
    if (!g || typeof g.getItemCount !== 'function') return {ok: false, reason: 'no-grid'};
    let cols = [];
    try { cols = g.getColumns().map(c => c.fieldName); } catch (e) {}
    if (cols.indexOf(keyCol) < 0) return {ok: false, reason: 'wrong-grid', cols: cols};
    return {ok: true, cols: cols, items: g.getItemCount(),
            checked: g.getCheckedRows ? g.getCheckedRows().length : -1};
}"""

_CHECK_ALL_ROWS_JS = """() => {
    const g = window.Grids.getActiveGrid();
    g.checkAll(true);
    return {items: g.getItemCount(), checked: g.getCheckedRows().length};
}"""

_REACT_SET_CALENDAR_YEAR_JS = """(targetYear) => {
    const all = document.querySelectorAll('*');
    for (const el of all) {
        const keys = Object.keys(el).filter(k => k.startsWith('__reactInternalInstance'));
        for (const key of keys) {
            let node = el[key];
            const queue = [node];
            const visited = new Set();
            for (let depth = 0; depth < 25 && queue.length > 0; depth++) {
                const current = queue.shift();
                if (!current || visited.has(current)) continue;
                visited.add(current);
                const inst = current._instance;
                if (inst && inst.state && inst.state.selectedDate
                    && typeof inst.state.selectedDate.year === 'number') {
                    const oldYear = inst.state.selectedDate.year;
                    const oldMonth = inst.state.selectedDate.month;
                    const newMax = {year: targetYear, month: 12};
                    const newMin = inst.state.minDate
                        ? {year: Math.min(inst.state.minDate.year, targetYear - 1), month: 1}
                        : {year: targetYear - 1, month: 1};
                    inst.setState({
                        selectedDate: {year: targetYear, month: oldMonth},
                        maxDate: newMax,
                        minDate: newMin,
                    });
                    return {success: true, oldYear, oldMonth, newMax, newMin};
                }
                if (current._renderedChildren) {
                    for (const child of Object.values(current._renderedChildren)) {
                        if (child) queue.push(child);
                    }
                }
                if (current._renderedComponent) queue.push(current._renderedComponent);
                if (current.child) queue.push(current.child);
                if (current.sibling) queue.push(current.sibling);
                if (current.return) queue.push(current.return);
            }
        }
    }
    return {success: false};
}"""

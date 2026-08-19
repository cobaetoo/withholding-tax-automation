"""국민연금 EDI 사업장 선택/검색 모듈

사업장전환 모달, 검색, 더블클릭 선택, 목록 조회.
"""

import sys
import os
import asyncio
import re
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.utils.human import human_delay
from src.utils.nexacro import (
    nexacro_click,
    nexacro_dblclick_cell_viewport,
    nexacro_click_button_viewport,
    nexacro_wait_and_click,
    nexacro_select_combo,
    nexacro_find_row,
    nexacro_get_grid_data,
)
from src.automation.nps._constants import GRID_WORKPLACE, BTN_CHANGE_WORKPLACE, NPS_URL

# 로컬 별칭
nexacro_dblclick_cell = nexacro_dblclick_cell_viewport
nexacro_click_button = nexacro_click_button_viewport

# ─── 로그인/전환 차단 공지 팝업 ──────────────────────────────────────────────

# 2026-08 라이브: '직원 사칭 관련 유의사항' ChildFrame.
# ID 가 FrameSdi.16398 처럼 숫자라 고정 불가 → 제목/본문 힌트로 찾는다.
# ChangeBusi(사업장전환)·UHJE*(출력 모달) 는 절대 닫지 않는다.
_NOTICE_HINTS = ("유의사항", "사칭", "오늘 하루 그만보기", "사기 주의")
_NOTICE_KEEP_NAMES = ("form", "ChangeBusi")
_NOTICE_KEEP_PREFIXES = ("UHJE", "divWork")


def _is_keep_popup_name(name):
    if name in _NOTICE_KEEP_NAMES:
        return True
    return any(name.startswith(p) for p in _NOTICE_KEEP_PREFIXES)


_JS_FIND_NOTICE_POPUPS = """
(args) => {
    const hints = args.hints;
    const keepNames = new Set(args.keepNames);
    const keepPrefixes = args.keepPrefixes;
    const vis = (el) => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    const keep = (name) => {
        if (keepNames.has(name)) return true;
        return keepPrefixes.some((p) => name.startsWith(p));
    };
    const out = [];
    for (const el of document.querySelectorAll('[id^="mainframe.VFrameSet.FrameSdi."]')) {
        const id = el.id || '';
        const parts = id.split('.');
        if (parts.length !== 4) continue;
        const name = parts[3];
        if (keep(name) || !vis(el)) continue;
        const titleEl = document.getElementById(id + '.titlebar');
        const blob = ((titleEl && titleEl.textContent) || '') + ' ' + (el.innerText || '');
        const text = blob.replace(/\\s+/g, ' ');
        if (!hints.some((h) => text.includes(h))) continue;
        const closeId = id + '.titlebar.closebutton';
        if (!document.getElementById(closeId)) continue;
        const guessed = id + '.form.divPopBg.form.divPopWork.form.div01.form.chk00';
        const chk = document.getElementById(guessed) || el.querySelector('[id$=".chk00"]');
        out.push({
            id, name, title: text.trim().slice(0, 80), closeId,
            chkId: chk ? chk.id : null,
        });
    }
    return out;
}
"""

# Nexacro CheckBox: set_value(true) 가 있으면 토글 없이 켠다.
# 클래스/aria 로 on/off 를 알 수 있으면 그 값을 쓰고, 모르면 on=null.
_JS_CHECKBOX_STATE = """
(chkId) => {
    const el = document.getElementById(chkId);
    if (!el) return {exists: false, on: null, apiSet: false};
    const readOn = () => {
        const aria = (el.getAttribute('aria-checked') || '').toLowerCase();
        if (aria === 'true') return true;
        if (aria === 'false') return false;
        const cls = (el.className || '').toString();
        if (/\\b(nexaselected|selected|checked|nexachecked)\\b/i.test(cls)) return true;
        try {
            const comp = el.linkedcontrol
                || (el._linked_element && el._linked_element.linkedcontrol);
            if (comp) {
                if (typeof comp.isChecked === 'function') return !!comp.isChecked();
                if (comp.value === true || comp.value === 'true' || comp.value === 1) return true;
                if (comp.value === false || comp.value === 'false' || comp.value === 0) return false;
            }
        } catch (e) {}
        return null;
    };
    try {
        const comp = el.linkedcontrol
            || (el._linked_element && el._linked_element.linkedcontrol);
        if (comp && typeof comp.set_value === 'function') {
            comp.set_value(true);
            return {exists: true, on: true, apiSet: true};
        }
    } catch (e) {}
    return {exists: true, on: readOn(), apiSet: false};
}
"""


async def _ensure_notice_checkbox_on(page, chk_id):
    """'오늘 하루 그만보기' 를 켠다. 이미 켜져 있으면 클릭하지 않는다."""
    if not chk_id:
        return False
    try:
        state = await page.evaluate(_JS_CHECKBOX_STATE, chk_id)
    except Exception as e:
        log(f"  WARN: NPS 공지 체크 상태 확인 실패 - {e}")
        return False
    if not state or not state.get("exists"):
        return False
    if state.get("apiSet") or state.get("on") is True:
        if state.get("apiSet"):
            log("  NPS 공지 '오늘 하루 그만보기' 체크")
        return True
    # 미체크이거나 판정 불가면 한 번 클릭 후 꺼졌으면 다시 클릭
    result = await nexacro_click(page, chk_id)
    if not result.get("ok"):
        log(f"  WARN: NPS 공지 체크 클릭 실패 - {result}")
        return False
    await human_delay(0.2)
    try:
        after = await page.evaluate(_JS_CHECKBOX_STATE, chk_id)
    except Exception:
        after = None
    if after and after.get("on") is False:
        await nexacro_click(page, chk_id)
        await human_delay(0.2)
    log("  NPS 공지 '오늘 하루 그만보기' 체크")
    return True


async def find_notice_popups(page):
    """차단 공지 ChildFrame 목록. page.evaluate 결과만 반환(테스트 훅)."""
    return await page.evaluate(_JS_FIND_NOTICE_POPUPS, {
        "hints": list(_NOTICE_HINTS),
        "keepNames": list(_NOTICE_KEEP_NAMES),
        "keepPrefixes": list(_NOTICE_KEEP_PREFIXES),
    })


async def dismiss_blocking_popups(page):
    """사업장전환/검색을 가리는 NPS 공지 ChildFrame 을 닫는다.

    라이브(2026-08): '직원 사칭 관련 유의사항'이 ChangeBusi 위(z=1000003)에
    떠 콤보 item_0/item_1 클릭이 5초 타임아웃으로 실패했다.
    닫기 전 '오늘 하루 그만보기'(chk00)를 켠다. 클릭은 nexacro_click
    (dispatchEvent)만 쓴다 — 병렬에서 NPS 창이 가려지면 mouse.click 은
    앞 창을 치고 {ok:True} 거짓 양성이 난다.
    """
    try:
        pops = await find_notice_popups(page)
    except Exception as e:
        log(f"  WARN: NPS 공지 팝업 탐색 실패 - {e}")
        return 0
    if not pops:
        return 0
    closed = 0
    for pop in pops:
        title = pop.get("title") or pop.get("id")
        close_id = pop.get("closeId")
        if not close_id:
            continue
        await _ensure_notice_checkbox_on(page, pop.get("chkId"))
        # dispatchEvent 전용 — 병렬에서 NPS 창이 뒤에 가려지면
        # page.mouse.click(좌표)은 앞 창을 치고 {ok:True} 거짓 양성이 난다.
        result = await nexacro_click(page, close_id)
        if not result.get("ok"):
            log(f"  WARN: NPS 공지 닫기 실패 ({title}) - {result}")
            continue
        log(f"  NPS 공지 팝업 닫음: {title}")
        closed += 1
        # 닫힘 대기 (다음 클릭이 오버레이에 먹히지 않게)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                still = await page.evaluate(
                    '(id) => { const e = document.getElementById(id); '
                    'if (!e) return false; '
                    'const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }',
                    pop.get("id"),
                )
                if not still:
                    break
            except Exception:
                break
            await asyncio.sleep(0.2)
        await human_delay(0.3)
    return closed


# ─── 사업장 전환 ───────────────────────────────────────────────────────────────

async def _open_workplace_modal_verified(page, max_attempts=3):
    """사업장전환 모달 오픈 — 그리드 행 출현으로 유일하게 검증.

    nexacro_click_button 의 {ok:True} 는 거짓 양성이므로, BTN_CHANGE_WORKPLACE
    클릭 후 GRID_WORKPLACE 그리드가 로드(행≥1)되어야 성공으로 본다.
    실패 시 메뉴(open_workplace_selector) 폴백 후 재시도.
    """
    await dismiss_blocking_popups(page)
    for attempt in range(max_attempts):
        # 시도 A: BTN_CHANGE_WORKPLACE (화면 상태 무관, 헤더 버튼)
        await nexacro_click_button(page, BTN_CHANGE_WORKPLACE)
        if await _wait_workplace_grid(page, timeout=6):
            log(f"  사업장전환 모달 오픈 (BTN, 시도 {attempt + 1}/{max_attempts})")
            return True
        # 시도 B: 메뉴 (메인 화면에서만 동작)
        await open_workplace_selector(page)
        if await _wait_workplace_grid(page, timeout=6):
            log(f"  사업장전환 모달 오픈 (메뉴, 시도 {attempt + 1}/{max_attempts})")
            return True
        log(f"  WARN: 사업장전환 모달 오픈 재시도 ({attempt + 1}/{max_attempts})")
    log("  ERROR: 사업장전환 모달 오픈 실패")
    return False


async def _wait_workplace_closed(page, timeout=10, interval=0.5):
    """사업장전환 모달 닫힘 대기 + Nexacro 프레임워크 안정화.

    사업장 선택(더블클릭) 후 모달이 닫히며 화면이 리프레시되는데, 이 대기가
    없으면 다음 단계에서 컨텍스트 불일치/그리드 0개 가 발생한다(다중 사업장
    2번째부터의 주원인).
    """
    modal_id = "mainframe.VFrameSet.FrameSdi.ChangeBusi"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            visible = await page.evaluate(
                '(id) => { const e = document.getElementById(id); '
                'return !!(e && e.offsetParent !== null); }', modal_id)
            if not visible:
                break
        except Exception:
            break
        await asyncio.sleep(interval)
    # Nexacro 프레임워크 재준비 대기 (BTN_CHANGE_WORKPLACE 출현)
    from src.automation.nps._common import wait_for_nexacro_ready
    await wait_for_nexacro_ready(page, max_wait=10)


async def reset_workplace_page(page):
    """사업장전환 모달 + "조회결과 없음" alert 이 백그라운드 창에서 닫히지 않아
    다음 수임처 진행이 막히는 것(병렬 NPS 멈춤)을 막기 위해 NPS 페이지를 재로드해
    모두 강제 종료한다. run_auto_batch 가 미발견/실패 시 스킵 전에 호출.

    이전 close_workplace_modal(Escape/BTN_MODAL_CANCEL)이 신뢰 불가했던 이유:
    (1) BTN_MODAL_CANCEL 은 출력모달(UHJE0002P1)의 버튼이라 ChangeBusi 모달에
        안 닿음(ChangeBusi 닫기 버튼 상수 자체 없음),
    (2) nexacro_click_button(page.mouse.click)이 occluded 백그라운드 창에서
        no-op 인데 {ok:True} 를 반환해 dispatchEvent 폴백이 안 돌아감,
    (3) page.keyboard.press 는 Nexacro 내부 messageBox(브라우저 alert 아님)에
        도달 못 함,
    (4) _wait_workplace_closed 가 timeout 후 거짓성공.
    page.goto(네비게이션)은 입력이벤트가 아니라 모달/alert/occlusion 무관하게
    동작하고 세션(쿠키)이 유지돼 재로그인이 불필요하다. ensure_login_page/main()
    이 쓰는 검증 패턴(page.goto(NPS_URL) + wait_for_nexacro_ready) 재사용.
    """
    from src.automation.nps._common import wait_for_nexacro_ready
    try:
        await page.goto(NPS_URL, wait_until="domcontentloaded", timeout=60000)
        log("  NPS 페이지 리셋(재로드) — 모달/alert 강제 종료")
    except Exception as e:
        log(f"  WARN: NPS 페이지 리셋(goto) 실패 - {e}")
    await wait_for_nexacro_ready(page)


async def switch_workplace(page, workplace_name, management_number=""):
    """사업장전환 모달 오픈(검증) → 사업장 선택."""
    if not await _open_workplace_modal_verified(page):
        return False
    ok = await select_workplace(page, workplace_name, management_number)
    if ok:
        log(f"  사업장 전환 완료: {workplace_name}")
    return ok


async def switch_workplace_open(page):
    """사업장전환 모달 열기(검증). 선택은 하지 않는다.

    nps_auto_cdp.run_full_auto 가 모달 열기/목록 조회/선택을 분리 제어하기 위해
    사용. 본체는 _open_workplace_modal_verified 에 위임.
    """
    return await _open_workplace_modal_verified(page)


async def _search_workplace_in_modal(page, search_text, search_by_mgmt_no=False):
    """사업장전환 모달의 검색 입력란에 텍스트 입력 후 검색 실행"""
    await dismiss_blocking_popups(page)
    MODAL_SEARCH = (
        "mainframe.VFrameSet.FrameSdi.ChangeBusi"
        ".form.divPopBg.form.divPopWork.form.div01.form"
    )
    combo_id = f"{MODAL_SEARCH}.cbo00"
    want = "사업장관리번호" if search_by_mgmt_no else "사업장명"

    # 검색구분 콤보는 조건 없이 매번 명시적으로 설정한다.
    # ★"이미 원하는 값이면 드롭다운 생략" 최적화 금지 — 콤보 요소(cbo00)의
    # textContent 에는 하위 combolist 의 항목 라벨('사업장명'·'사업장관리번호')이
    # 모두 들어 있어 어떤 부분문자열 비교도 항상 참이 된다. 그러면 else 블록이
    # 통째로 죽어 콤보가 기본값('사업장명')에 방치되고, 관리번호 검색이 숫자를
    # 사업장명으로 검색해 0건 → 이름 fallback 이 대신 성공시키므로 전환 자체는
    # 성공해 보인다. 즉 관리번호 정확일치 보호만 조용히 사라진다(4edcf0c 회귀).
    # 아끼는 값은 콤보 조작 1회(≈2초)뿐이고, 공지 오버레이로 인한 클릭 타임아웃은
    # 이 함수 첫 줄 dismiss_blocking_popups 가 이미 근본 해결한다.
    await nexacro_click_button(page, f"{combo_id}.dropbutton")
    await human_delay(1)
    item = "item_1" if search_by_mgmt_no else "item_0"
    result = await nexacro_wait_and_click(
        page, f"{combo_id}.combolist.{item}", max_wait=5
    )
    if not result.get("ok"):
        result = await nexacro_select_combo(page, combo_id, want)
    if not result.get("ok"):
        log(f"  WARN: 드롭다운 항목 선택 실패 - {result}")
    await human_delay(1)

    await page.evaluate("""(args) => {
        const input = document.getElementById(args.inputId + ":input");
        if (input) {
            input.value = '';
            input.dispatchEvent(new Event("input", {bubbles: true}));
            input.value = args.text;
            input.dispatchEvent(new Event("input", {bubbles: true}));
            input.dispatchEvent(new Event("change", {bubbles: true}));
            return true;
        }
        return false;
    }""", {"inputId": f"{MODAL_SEARCH}.edt08", "text": search_text})
    await human_delay(0.5)

    await nexacro_click_button(page, f"{MODAL_SEARCH}.btn00")


async def open_workplace_selector(page):
    """사업장 선택 모달(업무대행서비스) 열기"""
    clicked = await page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.offsetParent === null) continue;
            const text = (el.textContent || '').trim();
            if (text !== '업무대행서비스') continue;
            if (el.tagName === 'A' || el.tagName === 'SPAN' || el.tagName === 'DIV') {
                el.click();
                return 'clicked: ' + el.tagName;
            }
        }
        return null;
    }""")
    if clicked:
        log(f"  업무대행서비스 메뉴 클릭: {clicked}")
    await human_delay(2)

    clicked2 = await page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.offsetParent === null) continue;
            const text = (el.textContent || '').trim();
            if (text !== '위탁사업장') continue;
            if (el.tagName === 'A' || el.tagName === 'SPAN' || el.tagName === 'DIV') {
                el.click();
                return 'clicked: ' + el.tagName;
            }
        }
        return null;
    }""")
    if clicked2:
        log(f"  위탁사업장 메뉴 클릭: {clicked2}")
    await human_delay(2)


async def _find_workplace_row_by_mgmt(page, management_number):
    """현재 사업장 그리드에서 사업장관리번호가 정확히 일치하는 행을 찾는다.

    NHIS select_firm 의 정확일치 로직과 대칭. 관리번호 검색이 모달 필터를
    좁히지 못해(백그라운드 Chrome / biz+"0" 불일치 등) 표가 전체 목록이더라도,
    일치 행만 골라 클릭하므로 blind row=0 으로 잘못된(첫) 사업장이 선택되지 않는다.

    Returns:
        (row_index, workplace_name) or None
    """
    want = re.sub(r"\D", "", management_number or "")
    if not want:
        return None
    data = await nexacro_get_grid_data(page, GRID_WORKPLACE)
    for i, row in enumerate(data):
        # col=1 = 사업장관리번호, col=2 = 사업장명 (list_workplaces 가 입증).
        row_mgmt = re.sub(r"\D", "", row[1]) if len(row) > 1 else ""
        if row_mgmt and row_mgmt == want:
            name = row[2] if len(row) > 2 else ""
            return (i, name)
    return None


async def select_workplace(page, workplace_name, management_number=""):
    """사업장 선택 모달에서 특정 사업장을 더블클릭으로 선택.

    management_number 가 제공되면 사업장관리번호가 정확히 일치(숫자 정규화)하는
    행만 더블클릭 — blind row=0 클릭 금지(잘못된 첫 사업장 반복 선택 방지).
    일치 행이 없거나 management_number 가 없으면 이름(workplace_name)으로 fallback.
    양쪽 성공 경로 모두 _wait_workplace_closed 로 모달 닫힘 + Nexacro 안정화 대기
    (select_workplace_by_index 와 평행).
    """
    if management_number:
        log(f"  사업장 검색: 관리번호 '{management_number}'")
        await _search_workplace_in_modal(page, management_number, search_by_mgmt_no=True)
        await _wait_workplace_grid(page, timeout=3)  # 검색 후 그리드 갱신 대기(빈 목록 읽기 방지)
        await human_delay(2)
        found = await _find_workplace_row_by_mgmt(page, management_number)
        if found is not None:
            row, name = found
            log(f"  관리번호 '{management_number}' 일치 행 (row={row}, '{name}'). 더블클릭 선택 중...")
            result = await nexacro_dblclick_cell(page, GRID_WORKPLACE, row=row, col=2)
            if result.get("ok"):
                log(f"  사업장 선택 완료: {result.get('text', '') or name}")
                await _wait_workplace_closed(page)
                return True
            log(f"  사업장 선택 실패: {result}")
            return False
        log(f"  관리번호 '{management_number}' 일치 행 없음 — 이름으로 재시도")

    # 이름 fallback (management_number 미제공 또는 관리번호 매칭 실패)
    log(f"  사업장 검색: '{workplace_name}'")

    row = await nexacro_find_row(page, GRID_WORKPLACE, col=2, text=workplace_name)

    if row is None:
        log(f"  표시 목록에 없음 — 모달 검색으로 찾는 중...")
        await _search_workplace_in_modal(page, workplace_name)
        await _wait_workplace_grid(page, timeout=3)  # 검색 후 그리드 갱신 대기(빈 목록 읽기 방지)
        await human_delay(2)
        row = await nexacro_find_row(page, GRID_WORKPLACE, col=2, text=workplace_name)

    if row is None:
        log(f"  '{workplace_name}' 사업장을 찾지 못했습니다.")
        return False

    log(f"  '{workplace_name}' 발견 (row={row}). 더블클릭 선택 중...")
    result = await nexacro_dblclick_cell(page, GRID_WORKPLACE, row=row, col=2)

    if result.get("ok"):
        log(f"  사업장 선택 완료: {result.get('text', '')}")
        await _wait_workplace_closed(page)
        return True

    log(f"  사업장 선택 실패: {result}")
    return False


async def select_workplace_by_index(page, index):
    """사업장 선택 모달에서 N번째(0-based) 사업장 선택"""
    log(f"  사업장 {index + 1}번째 행 선택 중...")
    result = await nexacro_dblclick_cell(page, GRID_WORKPLACE, row=index, col=2)

    if result.get("ok"):
        log(f"  사업장 선택 완료: {result.get('text', '')}")
        await _wait_workplace_closed(page)  # 모달 닫힘 + nexacro 안정화 대기
        return True

    log(f"  사업장 선택 실패: {result}")
    return False


async def _wait_workplace_grid(page, timeout=10, interval=0.5):
    """GRID_WORKPLACE 그리드 행(gridrow_N)이 출현할 때까지 폴링.

    사업장전환 모달 오픈 후 그리드가 비동기로 로드되므로 human_delay만으로는
    레이스 컨디션(빈 목록)이 발생한다. 행이 1개라도 보일 때까지 대기.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            count = await page.evaluate(
                '(gid) => document.querySelectorAll(\'[id^="\' + gid + \'.body.gridrow_"]\').length',
                GRID_WORKPLACE,
            )
            if count and count > 0:
                return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


async def list_workplaces(page, *, retry=True):
    """현재 사업장 목록의 가시 행 데이터 반환.

    retry=True(기본)면 그리드 행 출현까지 폴링 후 읽는다(모달 오픈 후 비동기
    로드 대기). 내부 경로에서 이미 대기한 경우 retry=False로 스킵.
    """
    if retry and not await _wait_workplace_grid(page):
        return []
    data = await nexacro_get_grid_data(page, GRID_WORKPLACE)
    workplaces = []
    for i, row in enumerate(data):
        workplaces.append({
            "index": i,
            "number": row[1] if len(row) > 1 else "",
            "name": row[2] if len(row) > 2 else "",
        })
    return workplaces

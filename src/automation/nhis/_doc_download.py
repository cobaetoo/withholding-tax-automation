"""NHIS EDI 문서 다운로드 모듈

인쇄 버튼 3전략 클릭, PDF 다운로드, Crownix 뷰어 제어, 탭 정리.

인쇄 버튼 클릭:
  _click_print_button() — JS MouseEvent → Playwright locator → DOM click 3전략.
  각 전략 후 find_preview_tab()으로 미리보기 탭 오픈 검증, 최대 3회 재시도.
  NPS _download.py의 _click_output_button 패턴과 동일.

Nexacro 그리드 셀 ID:
  패턴 = gridrow_{rowIdx}_cell_{rowIdx}_{colIdx}
  colIdx: 0=순번, 1=받은일자, 2=번호, 3=서식명, 4=구분, 5=최종받은일자
  중간 번호도 행 인덱스이므로 _cell_0_ 하드코딩 금지.
"""

import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.utils.save_path import make_save_dir

# 저장 최상위 폴더명(site_name). CLI --save-site 로 오버라이드 — 병렬 실행 시
# NPS 와 공통 폴더("공단EDI" 등)로 묶어 같은 수임처 폴더에 건강보험/국민연금 자료를 함께 저장.
# 미지정 시 "국민건강보험" (단독 실행 기본값: ~/Desktop/국민건강보험_{YYYYMM}/{수임처}/).
_SAVE_SITE = "국민건강보험"
_SAVE_SUBDIR = None  # 병렬(--save-site 공단EDI) 시 포털 하위폴더명; 단일 시 None
from src.utils.human import human_delay
from src.automation.nhis._constants import (
    NHIS_EDI_MAIN,
    BTN_PRINT,
    GRID_BODY_ID,
    PRINT_CLICK_RETRIES,
    PRINT_PREVIEW_TIMEOUT_S,
    PRINT_BUTTON_READY_TIMEOUT_S,
    CROWNIX_LOAD_TIMEOUT_S,
    PDF_DOWNLOAD_TIMEOUT_S,
    PAGE_STABLE_TIMEOUT_S,
)
from src.automation.nhis._doc_access import (
    open_received_docs,
    select_doc_type,
    find_preview_tab,
)
from src.utils.nexacro import nexacro_click_button_viewport


# ═══════════════════════════════════════════════════════════════════════════════
# 인쇄 버튼 준비 / 클릭
# ═══════════════════════════════════════════════════════════════════════════════

async def _print_button_geometry(edi_page):
    """인쇄 버튼 bounding box. 없거나 예외 시 None."""
    try:
        return await edi_page.evaluate(f"""() => {{
            const btn = document.getElementById('{BTN_PRINT}');
            if (!btn) return null;
            const r = btn.getBoundingClientRect();
            const style = window.getComputedStyle(btn);
            return {{
                w: r.width, h: r.height, x: r.x, y: r.y,
                display: style.display, visibility: style.visibility,
                opacity: style.opacity,
            }};
        }}""")
    except Exception:
        return None


async def _wait_print_button_ready(edi_page, timeout_s=PRINT_BUTTON_READY_TIMEOUT_S):
    """문서 상세 진입 후 인쇄 툴바가 실제 조작 가능해질 때까지 대기.

    목록 화면에서도 인쇄 버튼 DOM id 는 존재하지만 w/h=0 인 경우가 많다.
    합성 클릭만 하면 'ok' 로 보이지만 Nexacro 가 no-op → 미리보기 미오픈.
    """
    try:
        await edi_page.bring_to_front()
    except Exception:
        pass
    for i in range(timeout_s):
        geo = await _print_button_geometry(edi_page)
        if geo and geo.get("w", 0) > 2 and geo.get("h", 0) > 2:
            if geo.get("visibility") != "hidden" and geo.get("display") != "none":
                log(f"  인쇄 버튼 준비 완료 ({i + 1}초, {geo['w']:.0f}x{geo['h']:.0f})")
                return True
        if i % 5 == 4:
            log(f"  인쇄 버튼 가시 대기 중... ({i + 1}s) geo={geo!r}")
            try:
                await edi_page.bring_to_front()
            except Exception:
                pass
        await asyncio.sleep(1)
    geo = await _print_button_geometry(edi_page)
    log(f"  ERROR: 인쇄 버튼이 가시 상태가 아님 ({timeout_s}s) geo={geo!r}")
    return False


async def _click_print_once(edi_page, context, pages_before, strategy: str,
                            *, preview_timeout: int = 5):
    """한 전략으로 인쇄 클릭 후 미리보기 탭 탐색. 성공 시 Page, 아니면 None.

    preview_timeout: 전략당 대기(초). 전체 라운드 폭주를 막기 위해 기본 5초.
    """

    async def _after_click(label: str):
        # 새 탭이 뜨는 동안 expect 대신 폴링 — 이미 열린 탭도 find_preview 가 커버.
        preview = await find_preview_tab(
            context, pages_before, timeout=preview_timeout,
        )
        if preview:
            url = ""
            try:
                url = (preview.url or "")[:100]
            except Exception:
                pass
            log(f"  [{label}] 성공 — 미리보기 탭 오픈 ({url})")
            return preview
        log(f"  [{label}] 클릭 후 미리보기 탭 미감지")
        return None

    try:
        await edi_page.bring_to_front()
    except Exception:
        pass

    if strategy == "nexacro_api":
        log("  [1] Nexacro 컴포넌트 click() API (좌표 비의존)...")
        try:
            result = await edi_page.evaluate("""() => {
                try {
                    var n = window.nexacro;
                    if (!n || !n.Application) return {ok: false, msg: 'no nexacro'};
                    var form = n.Application.mainframe.childframe.form;
                    if (!form) return {ok: false, msg: 'no form'};
                    var candidates = [];
                    function walk(comp, depth) {
                        if (!comp || depth > 6) return;
                        try {
                            if (comp.id && String(comp.id).toLowerCase().indexOf('print') >= 0)
                                candidates.push(comp);
                            if (comp.components) {
                                var keys = comp.components._idArray
                                    || Object.keys(comp.components);
                                if (keys && keys.length !== undefined) {
                                    for (var i = 0; i < keys.length; i++) {
                                        var k = keys[i];
                                        var child = comp.components[k]
                                            || (comp.components.getComponent
                                                && comp.components.getComponent(k));
                                        walk(child, depth + 1);
                                    }
                                }
                            }
                        } catch (e) {}
                    }
                    walk(form, 0);
                    if (!candidates.length) {
                        try {
                            var top = form.components.div_top || form.div_top;
                            var inner = top && (top.form || top);
                            var img = inner && (inner.components
                                && (inner.components.img_print || inner.img_print));
                            if (img) candidates.push(img);
                        } catch (e) {}
                    }
                    if (!candidates.length)
                        return {ok: false, msg: 'print component not found'};
                    var btn = candidates[0];
                    if (typeof btn.click === 'function') btn.click();
                    try {
                        if (btn.on_fire_onclick) btn.on_fire_onclick(btn, null);
                    } catch (e) {}
                    return {ok: true, id: btn.id || ''};
                } catch (e) {
                    return {ok: false, msg: String(e)};
                }
            }""")
            if not result.get("ok"):
                log(f"  [1] 실패 — {result}")
                return None
            return await _after_click("1")
        except Exception as e:
            log(f"  [1] 예외 — {e}")
            return None

    if strategy == "locator_force":
        log("  [2] Playwright locator.click(id, force)...")
        try:
            btn = edi_page.locator(f'[id="{BTN_PRINT}"]')
            await btn.scroll_into_view_if_needed(timeout=3000)
            await btn.click(force=True, timeout=5000)
            return await _after_click("2")
        except Exception as e:
            log(f"  [2] 예외 — {e}")
            return None

    if strategy == "nexacro_viewport":
        log("  [3] Nexacro viewport 클릭...")
        try:
            result = await nexacro_click_button_viewport(edi_page, BTN_PRINT)
            if result.get("error"):
                log(f"  [3] 실패 — {result}")
                return None
            return await _after_click("3")
        except Exception as e:
            log(f"  [3] 예외 — {e}")
            return None

    if strategy == "mouse":
        log("  [4] 실마우스 클릭 (CSS 좌표, viewport 내만)...")
        try:
            geo = await _print_button_geometry(edi_page)
            if not geo or geo.get("w", 0) < 2:
                log(f"  [4] 버튼 비가시 — geo={geo!r}")
                return None
            vp = await edi_page.evaluate(
                "() => ({iw: innerWidth, ih: innerHeight, dpr: devicePixelRatio})"
            )
            cx = geo["x"] + geo["w"] / 2
            cy = geo["y"] + geo["h"] / 2
            iw, ih = vp.get("iw", 0), vp.get("ih", 0)
            if not (0 <= cx <= iw and 0 <= cy <= ih):
                log(
                    f"  [4] 스킵 — 좌표 ({cx:.0f},{cy:.0f}) 가 "
                    f"viewport {iw}x{ih} 밖 (해상도/스크롤)"
                )
                return None
            await edi_page.mouse.click(cx, cy)
            return await _after_click("4")
        except Exception as e:
            log(f"  [4] 예외 — {e}")
            return None

    if strategy == "js_mouse":
        log("  [5] JS MouseEvent 시뮬레이션...")
        try:
            result = await edi_page.evaluate(f'''() => {{
                var btn = document.getElementById('{BTN_PRINT}');
                if (!btn) return {{ok: false, msg: 'print btn not found'}};
                var rect = btn.getBoundingClientRect();
                if (rect.width < 2 || rect.height < 2)
                    return {{ok: false, msg: 'print btn not visible',
                            w: rect.width, h: rect.height}};
                var cx = rect.x + rect.width / 2;
                var cy = rect.y + rect.height / 2;
                var base = {{bubbles: true, cancelable: true, view: window,
                    screenX: cx, screenY: cy, clientX: cx, clientY: cy,
                    button: 0, buttons: 1, relatedTarget: null}};
                btn.dispatchEvent(new MouseEvent('mousemove',
                    {{...base, detail: 0, buttons: 0}}));
                var t = performance.now();
                while (performance.now() - t < 30 + Math.random() * 50) {{}}
                btn.dispatchEvent(new MouseEvent('mousedown', {{...base, detail: 1}}));
                btn.dispatchEvent(new MouseEvent('mouseup', {{...base, detail: 1}}));
                btn.dispatchEvent(new MouseEvent('click', {{...base, detail: 1}}));
                return {{ok: true}};
            }}''')
            if not result.get("ok"):
                log(f"  [5] 버튼 상태 불량 — {result}")
                return None
            return await _after_click("5")
        except Exception as e:
            log(f"  [5] 예외 — {e}")
            return None

    if strategy == "dom_click":
        log("  [6] DOM element.click()...")
        try:
            await edi_page.evaluate(f'''() => {{
                var el = document.getElementById('{BTN_PRINT}');
                if (!el) throw new Error('print btn not found');
                el.focus();
                el.click();
            }}''')
            return await _after_click("6")
        except Exception as e:
            log(f"  [6] 예외 — {e}")
            return None

    return None


async def _click_print_button(edi_page, context, pages_before):
    """인쇄 버튼 다전략 클릭. 미리보기 탭 Page 반환 또는 None.

    0) 인쇄 버튼 가시 대기 (문서 상세 진입 확인)
    1) 해상도 비의존 우선: Nexacro API → locator(id) → 그다음 좌표/합성
    """
    await _ensure_edi_viewport(edi_page)
    await _log_viewport_diag(edi_page, "print")
    # locator/nexacro 를 mouse 좌표보다 앞에 두어 DPI·창 크기 차이를 줄인다.
    strategies = (
        "nexacro_api",
        "locator_force",
        "nexacro_viewport",
        "mouse",
        "js_mouse",
        "dom_click",
    )
    for attempt in range(PRINT_CLICK_RETRIES):
        log(f"  인쇄 클릭 라운드 {attempt + 1}/{PRINT_CLICK_RETRIES}")
        if not await _wait_print_button_ready(edi_page):
            # 상세 미진입 — 호출부(download_first_doc_pdf)가 행 재선택을 함.
            return None
        for i, strategy in enumerate(strategies):
            # 마지막 전략·마지막 라운드만 긴 대기 (전체 폭주 방지).
            long_wait = (
                attempt == PRINT_CLICK_RETRIES - 1
                and i == len(strategies) - 1
            )
            preview = await _click_print_once(
                edi_page, context, pages_before, strategy,
                preview_timeout=(
                    PRINT_PREVIEW_TIMEOUT_S if long_wait else 5
                ),
            )
            if preview:
                return preview
        if attempt < PRINT_CLICK_RETRIES - 1:
            log("  모든 전략 실패 — 2초 후 재시도...")
            await asyncio.sleep(2)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# PDF 다운로드
# ═══════════════════════════════════════════════════════════════════════════════

async def _locate_target_row(edi_page, target_yyyymm):
    """그리드에서 고지년월(YYYYMM) 매칭 행을 찾고 셀 좌표/텍스트를 반환 (클릭 없음).

    매칭: 행 textContent 숫자 정규화 후 target_yyyymm 부분문자열.
    동일 년월 여러 행이면 고지차수 숫자가 있는 첫 행을 사용(목록 순서 유지).
    """
    log(f"  문서 검색 (고지년월: {target_yyyymm})...")
    result = await edi_page.evaluate("""(args) => {
        var body = document.getElementById(args.gridBodyId);
        if (!body) return {ok: false, msg: 'grid body not found'};

        var allRows = body.querySelectorAll('[id*="gridrow_"]');
        var candidates = [];
        for (var i = 0; i < allRows.length; i++) {
            var row = allRows[i];
            if (row.id.includes('gridrow_-1')) continue;
            if (row.id.includes('G')) continue;
            var text = (row.textContent || '').replace(/\\s+/g, ' ').trim();
            var digits = text.replace(/\\D+/g, '');
            if (digits.indexOf(args.target) === -1) continue;
            var m = row.id.match(/gridrow_(\\d+)$/);
            if (!m) continue;
            var idx = m[1];
            // 고지차수: '고지차수' 근처 숫자 또는 행 내 단독 1~2자리 힌트
            var chasu = null;
            var cm = text.match(/고지차수\\s*[:：]?\\s*(\\d+)/);
            if (cm) chasu = cm[1];
            candidates.push({
                rowIdx: idx,
                text: text.substring(0, 120),
                chasu: chasu,
                digits: digits
            });
        }
        if (!candidates.length)
            return {ok: false, msg: 'no matching row for ' + args.target
                    + ' (rows seen: ' + allRows.length + ')',
                    rowsSeen: allRows.length};

        // 목록 상위(보통 최신/1차) 우선
        var pick = candidates[0];
        var cellId = args.gridBodyId
            + '_gridrow_' + pick.rowIdx + '_cell_' + pick.rowIdx + '_3';
        var cell = document.getElementById(cellId);
        if (!cell)
            return {ok: false, msg: 'cell not found: ' + cellId};

        try { cell.scrollIntoView({block: 'center', inline: 'nearest'}); } catch (e) {}
        var rect = cell.getBoundingClientRect();
        return {
            ok: true,
            rowIdx: pick.rowIdx,
            text: pick.text,
            chasu: pick.chasu,
            cellId: cellId,
            x: rect.x, y: rect.y, w: rect.width, h: rect.height,
            candidates: candidates.length
        };
    }""", {"gridBodyId": GRID_BODY_ID, "target": target_yyyymm})

    if not result or not result.get("ok"):
        log(f"  ERROR: 문서 검색 실패 - {result}")
        return None
    log(
        f"  문서 발견 (row {result['rowIdx']}"
        + (f", 고지차수 {result.get('chasu')}" if result.get("chasu") else "")
        + f", 후보 {result.get('candidates', 1)}건): "
        f"{(result.get('text') or '')[:80]}"
    )
    return result


async def _log_viewport_diag(edi_page, label: str = "") -> dict:
    """해상도/DPI/뷰포트 진단 — 좌표 클릭 실패 원인 분리용."""
    try:
        info = await edi_page.evaluate("""() => ({
            iw: window.innerWidth,
            ih: window.innerHeight,
            dpr: window.devicePixelRatio || 1,
            sx: window.scrollX || 0,
            sy: window.scrollY || 0,
            ow: window.outerWidth,
            oh: window.outerHeight
        })""")
        prefix = f"  [viewport{(' ' + label) if label else ''}] "
        log(
            f"{prefix}inner={info.get('iw')}x{info.get('ih')} "
            f"outer={info.get('ow')}x{info.get('oh')} "
            f"dpr={info.get('dpr')} scroll=({info.get('sx')},{info.get('sy')})"
        )
        return info or {}
    except Exception as e:
        log(f"  [viewport] 진단 실패: {e}")
        return {}


async def _ensure_edi_viewport(edi_page) -> None:
    """EDI 탭 viewport 를 고정해 해상도/모니터 차이를 줄인다.

    Chrome 은 --window-size=1920,1080 으로 뜨지만, OS DPI·창 배치에 따라
    Playwright page viewport 가 달라질 수 있다. 문서 그리드/툴바 레이아웃을
    맞추기 위해 CSS 픽셀 기준으로 맞춤.
    """
    try:
        await edi_page.set_viewport_size({"width": 1920, "height": 1080})
    except Exception:
        pass
    try:
        await edi_page.bring_to_front()
    except Exception:
        pass


async def _open_document_row(edi_page, row_info) -> bool:
    """목록 행을 열어 문서 상세(인쇄 버튼 가시)로 진입.

    해상도/좌표 의존을 줄이기 위해 우선순위:
      A) Nexacro grid API (행·열 인덱스 — 좌표 불필요)
      B) Playwright locator 더블클릭 (element id — Playwright 가 스크롤/hit 처리)
      C) page.mouse (CSS 좌표 — viewport 안일 때만, 클릭 직전 재측정)
      D) 합성 MouseEvent (최후 수단)
    """
    import random

    await _ensure_edi_viewport(edi_page)
    vp = await _log_viewport_diag(edi_page, "open-row")

    row_idx = str(row_info.get("rowIdx", "0"))
    cell_id = row_info.get("cellId") or (
        f"{GRID_BODY_ID}_gridrow_{row_idx}_cell_{row_idx}_3"
    )

    async def _cell_geo():
        return await edi_page.evaluate("""(cellId) => {
            var cell = document.getElementById(cellId);
            if (!cell) return null;
            try { cell.scrollIntoView({block: 'center', inline: 'nearest'}); } catch (e) {}
            var r = cell.getBoundingClientRect();
            return {
                x: r.x, y: r.y, w: r.width, h: r.height,
                text: (cell.textContent||'').trim().substring(0,60),
                inView: r.bottom > 0 && r.right > 0
                    && r.top < window.innerHeight && r.left < window.innerWidth
                    && r.width > 1 && r.height > 1
            };
        }""", cell_id)

    geo = await _cell_geo()
    if not geo or geo.get("w", 0) < 2:
        log(f"  WARN: 문서 셀 비가시 — geo={geo!r}")
    else:
        log(
            f"  문서 셀 위치 {geo['w']:.0f}x{geo['h']:.0f} @ "
            f"({geo['x']:.0f},{geo['y']:.0f}) inView={geo.get('inView')}"
        )

    # ── 전략 A: Nexacro grid API (해상도/좌표 무관) ──
    try:
        log("  문서 행 열기 [A] Nexacro grid API (좌표 비의존)...")
        api = await edi_page.evaluate("""(args) => {
            try {
                var n = window.nexacro;
                if (!n || !n.Application) return {ok: false, msg: 'no nexacro'};
                var form = n.Application.mainframe.childframe.form;
                if (!form || !form.components) return {ok: false, msg: 'no form'};
                var body = form.components.div_body || form.div_body;
                var bodyForm = body && (body.form || body);
                var grid = bodyForm && (bodyForm.components
                    && (bodyForm.components.grid_list || bodyForm.grid_list));
                if (!grid) {
                    function findGrid(comp, depth) {
                        if (!comp || depth > 5) return null;
                        try {
                            if (comp.id && String(comp.id).indexOf('grid_list') >= 0)
                                return comp;
                            var cs = comp.components;
                            if (!cs) return null;
                            var keys = cs._idArray || Object.keys(cs);
                            for (var i = 0; i < keys.length; i++) {
                                var ch = cs[keys[i]] || (cs.getComponent && cs.getComponent(keys[i]));
                                var g = findGrid(ch, depth + 1);
                                if (g) return g;
                            }
                        } catch (e) {}
                        return null;
                    }
                    grid = findGrid(form, 0);
                }
                if (!grid) return {ok: false, msg: 'grid not found'};
                var row = parseInt(args.rowIdx, 10);
                var col = 3;
                try {
                    if (typeof grid.setSelect === 'function') grid.setSelect(row, col);
                    else if (typeof grid.selectRow === 'function') grid.selectRow(row);
                } catch (e) {}
                try {
                    if (typeof grid.on_fire_oncelldblclick === 'function') {
                        grid.on_fire_oncelldblclick(grid, {row: row, cell: col, col: col});
                        return {ok: true, via: 'on_fire_oncelldblclick'};
                    }
                } catch (e1) {}
                try {
                    if (grid.oncelldblclick && typeof grid.oncelldblclick._fireEvent === 'function') {
                        grid.oncelldblclick._fireEvent(grid, {row: row, cell: col});
                        return {ok: true, via: 'oncelldblclick._fireEvent'};
                    }
                } catch (e2) {}
                try {
                    if (typeof grid.callEvent === 'function') {
                        grid.callEvent('oncelldblclick', [row, col]);
                        return {ok: true, via: 'callEvent'};
                    }
                } catch (e3) {}
                return {ok: false, msg: 'no dblclick API on grid'};
            } catch (e) {
                return {ok: false, msg: String(e)};
            }
        }""", {"rowIdx": row_idx})
        log(f"  [A] Nexacro 결과: {api}")
        if api and api.get("ok"):
            if await _wait_print_button_ready(edi_page, timeout_s=8):
                log("  문서 상세 진입 성공 (Nexacro API — 해상도 비의존)")
                return True
    except Exception as e:
        log(f"  [A] Nexacro 예외 — {e}")

    # ── 전략 B: Playwright locator (id 기반 — 좌표 수동 계산 없음) ──
    try:
        log("  문서 행 열기 [B] locator.dblclick(id)...")
        loc = edi_page.locator(f'[id="{cell_id}"]')
        await loc.scroll_into_view_if_needed(timeout=5000)
        # force=True: Nexacro 오버레이/opacity 에도 동작, 해상도별 hit-test 완화
        await loc.dblclick(timeout=5000, force=True)
        if await _wait_print_button_ready(edi_page, timeout_s=8):
            log("  문서 상세 진입 성공 (locator — id 기반)")
            return True
    except Exception as e:
        log(f"  [B] locator 예외 — {e}")

    # ── 전략 C: page.mouse (CSS 좌표 — viewport 안일 때만) ──
    # getBoundingClientRect 와 Playwright mouse 는 모두 CSS 픽셀.
    # 단, 요소가 viewport 밖이거나 w/h=0 이면 해상도/스크롤 문제로 실패한다.
    geo = await _cell_geo()
    if geo and geo.get("inView") and geo.get("w", 0) >= 2 and geo.get("h", 0) >= 2:
        iw = float(vp.get("iw") or 0) or 9999
        ih = float(vp.get("ih") or 0) or 9999
        cx = geo["x"] + geo["w"] / 2
        cy = geo["y"] + geo["h"] / 2
        if 0 <= cx <= iw and 0 <= cy <= ih:
            try:
                log(
                    f"  문서 행 열기 [C] page.mouse.dblclick "
                    f"@({cx:.0f},{cy:.0f}) vp={iw:.0f}x{ih:.0f} dpr={vp.get('dpr')}..."
                )
                await edi_page.mouse.click(cx + random.uniform(-1, 1),
                                           cy + random.uniform(-1, 1))
                await asyncio.sleep(0.12)
                await edi_page.mouse.dblclick(cx, cy)
                if await _wait_print_button_ready(edi_page, timeout_s=8):
                    log("  문서 상세 진입 성공 (실마우스 CSS 좌표)")
                    return True
            except Exception as e:
                log(f"  [C] 실마우스 예외 — {e}")
        else:
            log(
                f"  [C] 스킵 — 셀 중심 ({cx:.0f},{cy:.0f}) 이 "
                f"viewport {iw:.0f}x{ih:.0f} 밖 (해상도/스크롤 이슈 가능)"
            )
    else:
        log(f"  [C] 스킵 — 셀 inView/크기 부족 geo={geo!r}")

    # ── 전략 D: 합성 MouseEvent (최후) ──
    try:
        log("  문서 행 열기 [D] 합성 dblclick...")
        syn = await edi_page.evaluate("""(cellId) => {
            var cell = document.getElementById(cellId);
            if (!cell) return {ok: false, msg: 'cell missing'};
            try { cell.scrollIntoView({block: 'center'}); } catch (e) {}
            var rect = cell.getBoundingClientRect();
            var cx = rect.x + rect.width / 2;
            var cy = rect.y + rect.height / 2;
            var base = {bubbles: true, cancelable: true, view: window,
                screenX: cx, screenY: cy, clientX: cx, clientY: cy,
                button: 0, buttons: 1, relatedTarget: null};
            cell.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
            var t = performance.now();
            while (performance.now() - t < 40) {}
            cell.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
            cell.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
            cell.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
            t = performance.now();
            while (performance.now() - t < 40) {}
            cell.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 2}));
            cell.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 2}));
            cell.dispatchEvent(new MouseEvent('click', {...base, detail: 2}));
            cell.dispatchEvent(new MouseEvent('dblclick', {...base, detail: 2}));
            return {ok: true, w: rect.width, h: rect.height,
                    inView: rect.bottom > 0 && rect.top < window.innerHeight};
        }""", cell_id)
        log(f"  [D] 합성 결과: {syn}")
        if await _wait_print_button_ready(edi_page, timeout_s=8):
            log("  문서 상세 진입 성공 (합성 이벤트)")
            return True
    except Exception as e:
        log(f"  [D] 합성 예외 — {e}")

    log(
        "  ERROR: 문서 행 더블클릭으로 상세 진입 실패 "
        "(인쇄 버튼 계속 숨김). viewport/DPI 로그 위 참고."
    )
    return False


async def _find_target_row(edi_page, target_yyyymm):
    """그리드에서 YYYYMM 매칭 행 찾기 + 상세 진입까지 수행.

    Returns:
        row_info dict (상세 진입 성공 시) 또는 None
    """
    info = await _locate_target_row(edi_page, target_yyyymm)
    if not info:
        return None
    opened = await _open_document_row(edi_page, info)
    if not opened:
        return None
    return info


async def _setup_crownix_download(context, preview, save_dir):
    """reportview iframe → Crownix 뷰어 대기 → CDP 다운로드 세션 설정

    Returns:
        (report_frame, cdp_session) or (None, None)
    """
    # ── reportview iframe 찾기 ──
    report_frame = None
    for attempt in range(10):
        for f in preview.frames:
            if "reportview" in f.url:
                report_frame = f
                break
        if report_frame:
            break
        await asyncio.sleep(1)

    if not report_frame:
        log("  ERROR: 리포트 프레임을 찾지 못했습니다 (10초 대기).")
        try:
            await preview.close()
        except Exception:
            pass
        return None, None

    # ── Crownix 뷰어 로딩 대기 ──
    log("  Crownix 뷰어 로딩 대기...")
    pdf_btn_found = False
    for attempt in range(CROWNIX_LOAD_TIMEOUT_S):
        try:
            pdf_btn_found = await report_frame.evaluate("""() => {
                const btn = document.querySelector('button[title="PDF 저장"]');
                return !!btn;
            }""")
            if pdf_btn_found:
                log(f"  Crownix 뷰어 준비 완료 ({attempt + 1}초)")
                break
        except Exception:
            pass
        await asyncio.sleep(1)

    if not pdf_btn_found:
        log(f"  ERROR: Crownix PDF 버튼을 찾지 못했습니다 ({CROWNIX_LOAD_TIMEOUT_S}초 대기).")
        try:
            await preview.close()
        except Exception:
            pass
        return None, None

    # ── CDP 다운로드 경로 설정 ──
    os.makedirs(save_dir, exist_ok=True)
    cdp_session = await context.new_cdp_session(preview)
    await cdp_session.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": save_dir,
        "eventsEnabled": True,
    })

    return report_frame, cdp_session


async def _wait_and_rename_pdf(save_dir, before, year, month):
    """다운로드 완료 대기 + PDF 헤더 검증 + 이름변경

    Returns:
        str: 저장된 PDF 경로, 또는 None
    """
    _y = year
    _m = month

    checked_files = set()
    for i in range(PDF_DOWNLOAD_TIMEOUT_S):
        await asyncio.sleep(1)
        after = set(os.listdir(save_dir))
        new_files = after - before
        downloading = [f for f in new_files if f.endswith(".crdownload")]
        done = [f for f in new_files if not f.endswith(".crdownload")]

        if not downloading and done:
            for fname in sorted(done):
                if fname in checked_files:
                    continue
                checked_files.add(fname)
                filepath = os.path.join(save_dir, fname)
                try:
                    with open(filepath, "rb") as fh:
                        header = fh.read(5)
                except Exception:
                    continue

                if header == b"%PDF-":
                    new_name = f"가입자고지내역서_건강_{_y}{_m:02d}.pdf"
                    new_path = os.path.join(save_dir, new_name)
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(filepath, new_path)
                    log(f"  PDF 저장 완료: {new_path}")
                    for f in os.listdir(save_dir):
                        if not f.lower().endswith(".pdf"):
                            try:
                                os.remove(os.path.join(save_dir, f))
                                log(f"  정리: {f} 삭제")
                            except Exception:
                                pass
                    return new_path
                else:
                    log(f"  비-PDF 파일 (무시): {fname} header={header!r}")

        if i % 10 == 9:
            log(f"  PDF 다운로드 대기... ({i + 1}초) downloading={len(downloading)} done={done}")

    log(f"  ERROR: PDF 다운로드 시간 초과 ({PDF_DOWNLOAD_TIMEOUT_S}초)")
    return None


def _resolve_period(year: int | None, month: int | None) -> tuple[int, int, str]:
    """year/month 의 None 폴백(당월) + 정규화. (year, month, target_yyyymm) 반환.

    target_yyyymm 은 6자리(예: 202605). None 이면 datetime.now() 의 년/월 사용.
    받은문서 그리드 행의 숫자정규화 text 와 부분문자열 매칭(_find_target_row)의 기준.
    """
    now = datetime.now()
    _y = year if year is not None else now.year
    _m = month if month is not None else now.month
    return _y, _m, f"{_y}{_m:02d}"


async def download_first_doc_pdf(edi_page, context, save_dir, firm_name,
                                  year: int | None = None, month: int | None = None):
    """웹EDI 받은문서 목록에서 YYYYMM 매칭 행 더블클릭 → 인쇄 → PDF 다운로드

    서식명(가입자 고지(산출) 내역서) 필터링 후, 그리드에서 고지년월이
    year/month와 일치하는 첫 번째 행을 찾아 상세 진입 후 PDF 저장.

    Nexacro 그리드 셀 ID 패턴: gridrow_{idx}_cell_{idx}_{col}
    중간 번호도 행 인덱스이므로 _cell_0_ 고정 금지.
    """
    # YYYYMM 타겟 계산 (None → 당월 폴백)
    _y, _m, target_yyyymm = _resolve_period(year, month)

    try:
        await edi_page.bring_to_front()
    except Exception:
        pass

    # 그리드에서 YYYYMM(+고지차수 목록) 매칭 → 상세 진입(실마우스/Nexacro/합성)
    # → 인쇄. 병렬 Chrome 에서 합성 dblclick no-op 이 주원인.
    preview = None
    for open_try in range(3):
        try:
            await edi_page.bring_to_front()
        except Exception:
            pass
        result = await _find_target_row(edi_page, target_yyyymm)
        if not result:
            log(
                f"  문서 상세 미진입 (시도 {open_try + 1}/3) "
                "— 행 재검색/재더블클릭"
            )
            await asyncio.sleep(1)
            continue
        # _find_target_row 성공 시 이미 인쇄 버튼 가시
        pages_before = set(id(pg) for pg in context.pages)
        log("  인쇄 버튼 클릭 (다전략)...")
        preview = await _click_print_button(edi_page, context, pages_before)
        if preview:
            break
        log(
            f"  인쇄 클릭 실패 (문서 오픈 시도 {open_try + 1}/3) "
            "— 행 재선택 후 재시도"
        )
        await asyncio.sleep(1)

    if not preview:
        log(
            "  ERROR: 미리보기 탭을 찾지 못했습니다 "
            "(문서 상세 진입 + 인쇄 다전략 실패)."
        )
        return None
    log("  미리보기 탭 열림")

    # ── Crownix 뷰어 + CDP 세션 ──
    report_frame, cdp_session = await _setup_crownix_download(context, preview, save_dir)
    if not report_frame:
        return None

    try:
        before = set(os.listdir(save_dir))

        # 전략 1: DOM element.click()
        log("  PDF 버튼 클릭 (DOM .click())...")
        clicked = await report_frame.evaluate("""() => {
            const btn = document.querySelector('button[title="PDF 저장"]');
            if (btn) { btn.click(); return true; }
            return false;
        }""")

        download_started = False
        for _ in range(5):
            await asyncio.sleep(1)
            after = set(os.listdir(save_dir))
            new_files = after - before
            if new_files:
                download_started = True
                log(f"  다운로드 시작 감지: {list(new_files)[:3]}")
                break

        # 전략 2: Playwright locator.click(force=True)
        if not download_started:
            log("  PDF 버튼 DOM 클릭으로 다운로드 미시작 — Playwright locator 클릭...")
            try:
                pdf_btn = report_frame.locator('button[title="PDF 저장"]')
                await pdf_btn.click(force=True, timeout=5000)
                for _ in range(5):
                    await asyncio.sleep(1)
                    after = set(os.listdir(save_dir))
                    new_files = after - before
                    if new_files:
                        download_started = True
                        log(f"  다운로드 시작 감지 (전략2): {list(new_files)[:3]}")
                        break
            except Exception as e:
                log(f"  Playwright locator 클릭 예외 — {e}")

        if not download_started:
            log("  WARN: PDF 다운로드가 감지되지 않음 — 추가 대기 진행...")

        # 다운로드 완료 대기 + PDF 검증 + 이름변경
        pdf_path = await _wait_and_rename_pdf(save_dir, before, _y, _m)

        if not pdf_path:
            try:
                await preview.close()
                log("  미리보기 탭 닫기 완료 (타임아웃 정리)")
            except Exception:
                pass

        return pdf_path

    finally:
        if cdp_session:
            try:
                await cdp_session.detach()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# 워크플로우 오케스트레이터
# ═══════════════════════════════════════════════════════════════════════════════

async def reset_main_page(page):
    """retrieveMain 페이지를 재로드해 로그인 사업장(기본 사업장) 상태로 리셋.

    not-found/예외 등으로 run_single_firm_workflow 의 we_btn_relogin 복귀가
    생략된 뒤, 다음 수임처의 select_firm 클릭이 stale 페이지에서 no-op 가 되는
    것(N+1 lag/state-bleed)을 막기 위해 매 run_single 시작에 호출한다.

    page.goto(네비게이션)은 입력이벤트가 아니라 모달/alert/occlusion/선택된
    수임처 상태 무관하게 동작하며 세션(공동인증서 쿠키)이 유지돼 재로그인이
    불필요하다.

    주의: retrieveMain 은 일반 HTML 페이지라 Nexacro 가 없음에도 예전에
    wait_for_nexacro_ready 를 호출해 매번 30초 타임아웃(속도 저하 + 시간초과
    에러 로그)을 유발했다. NPS 와 달리 NHIS 의 Nexacro 는 '받은문서' 웹EDI
    탭에서만 로드되므로 여기서는 goto(domcontentloaded) 만으로 충분하다.
    이후 open_firm_selector 가 수임사업장선택 버튼을 직접 폴링(최대 25s)한다.
    """
    try:
        await page.goto(NHIS_EDI_MAIN, wait_until="domcontentloaded", timeout=60000)
        log("  retrieveMain 리셋(재로드) — 로그인 사업장 복귀")
    except Exception as e:
        log(f"  WARN: retrieveMain 리셋(goto) 실패 - {e}")


async def run_single_firm_workflow(page, context, firm_name,
                                    year: int | None = None,
                                    month: int | None = None,
                                    *, close_popups_fn=None):
    """수임처 1개에 대한 전체 워크플로우 수행

    플로우:
    1. 받은문서 → 웹EDI 탭 열기
    2. 전체 라디오 + 서식명 선택
    3. 첫 문서 더블클릭 → 인쇄 → PDF 다운로드
    4. 미리보기 + 웹EDI 탭 닫기
    5. 로그인 사업장 돌아가기
    """
    save_dir = make_save_dir(_SAVE_SITE, firm_name, year=year, month=month,
                             subdir=_SAVE_SUBDIR)

    log("  메인페이지 안정화 대기...")
    for i in range(PAGE_STABLE_TIMEOUT_S):
        try:
            ready = await page.evaluate("""() => {
                return document.readyState === 'complete'
                    || document.readyState === 'interactive';
            }""")
            if ready:
                break
        except Exception:
            pass
        await asyncio.sleep(1)

    # Step 1: 받은문서 열기
    log("  [1/5] 받은문서 열기...")
    edi_page = await open_received_docs(page, context)
    if not edi_page:
        return False

    # Step 2: 전체 라디오 + 서식명 선택
    log("  [2/5] 전체 라디오 + 서식명 선택...")
    ok = await select_doc_type(edi_page)
    if not ok:
        await _close_edi_tabs(context)
        return False

    # Step 3: PDF 다운로드
    log("  [3/5] PDF 다운로드...")
    pdf_path = await download_first_doc_pdf(edi_page, context, save_dir, firm_name,
                                             year=year, month=month)

    # Step 4: 탭 정리
    log("  [4/5] 탭 정리...")
    await _close_edi_tabs(context)

    # Step 5: 로그인 사업장 돌아가기
    log("  [5/5] 로그인 사업장 복귀...")
    await page.evaluate("""() => {
        var img = document.querySelector('img[src*="we_btn_relogin"]');
        if (img) img.click();
    }""")
    await human_delay(3)

    # 모달 닫기
    if close_popups_fn:
        await close_popups_fn(context)

    if pdf_path:
        log(f"  완료! 저장: {pdf_path}")
        return True
    else:
        log("  PDF 다운로드 실패")
        return False


async def _close_edi_tabs(context):
    """웹EDI, 미리보기 등 메인이 아닌 탭 모두 닫기"""
    main_page = None
    for pg in context.pages:
        if "retrieveMain" in pg.url:
            main_page = pg
            break

    for pg in context.pages[:]:
        if pg != main_page:
            try:
                await pg.close()
            except Exception:
                pass

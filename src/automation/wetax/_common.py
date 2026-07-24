"""위택스 공통 유틸 — 메인/서브 팝업 감지·닫기 등."""

from __future__ import annotations

import asyncio
from typing import Callable


def log(msg: str) -> None:
    print(msg, flush=True)


def mask_phone(phone: str) -> str:
    """로그·에러 메시지용 휴대전화 마스킹 (중간 숫자 숨김).

    예) 010-1234-5678 → 010-****-5678, 01012345678 → 010****5678
    숫자가 7자리 미만이면 `*` 만 반환 (원문 비노출).
    """
    s = (phone or "").strip()
    if not s:
        return ""
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) < 7:
        return "*" * max(len(digits), 4) if digits else "****"
    head, tail = digits[:3], digits[-4:]
    if "-" in s:
        return f"{head}-****-{tail}"
    return f"{head}****{tail}"


# Playwright locator 후보 — 개수·id 가 실행마다 달라도 클래스/패턴으로 잡는다.
# (라이브 확인 2026-07: div.main-popup-event + button.close-btn, fnCloseBtn → .hide())
_CLOSE_BTN_SELECTORS = (
    "div.main-popup-event button.close-btn",
    "div[id^='pop_'] button.close-btn",
    ".layer_popup button.close-btn",
    ".layer_pop button.close-btn",
    ".popup_wrap button.close-btn",
    "[role='dialog'] button.close-btn",
    "[aria-modal='true'] button.close-btn",
    # 텍스트 '닫기' 전용(짧은 버튼) — 컨테이너 전체 텍스트 매칭 회피 위해 close-btn 우선
    "div.main-popup-event button:has-text('닫기')",
    "div[id^='pop_'] button:has-text('닫기')",
)

# DOM 폴백: 여전히 보이는 메인 팝업을 jQuery .hide() / style 로 숨김
# (fnCloseBtn 과 동일: $('#pop_'+popupId).hide())
_HIDE_REMAINING_JS = r"""
() => {
  const hid = [];
  const hideEl = (el, label) => {
    try {
      if (window.jQuery) {
        window.jQuery(el).hide();
      } else {
        el.style.setProperty('display', 'none', 'important');
      }
      hid.push(label);
    } catch (e) {
      try {
        el.style.setProperty('display', 'none', 'important');
        hid.push(label + ':css');
      } catch (e2) {}
    }
  };
  document.querySelectorAll('div.main-popup-event, div[id^="pop_"]').forEach((el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (s.display === 'none' || s.visibility === 'hidden') return;
    if (r.width < 10 || r.height < 10) return;
    hideEl(el, el.id || (el.className || '').toString().slice(0, 40) || 'anon');
  });
  // dimed 오버레이 잔재
  document.querySelectorAll('.dimed, .dimmed, .modal-backdrop, .ui-widget-overlay').forEach((el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none') return;
    hideEl(el, 'dim:' + (el.className || '').toString().slice(0, 30));
  });
  return hid;
}
"""

_COUNT_VISIBLE_JS = r"""
() => {
  const vis = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0)
      return false;
    const r = el.getBoundingClientRect();
    return r.width > 30 && r.height > 30
      && r.bottom > 0 && r.right > 0
      && r.top < (window.innerHeight || 9999)
      && r.left < (window.innerWidth || 9999);
  };
  return [...document.querySelectorAll(
    'div.main-popup-event, div[id^="pop_"], .layer_popup, [role="dialog"]'
  )].filter(vis).map((el) => el.id || (el.className || '').toString().slice(0, 40));
}
"""


async def _click_close_buttons(page, logger: Callable[[str], None]) -> int:
    """보이는 close 버튼을 Playwright 로 실제 클릭 (jQuery 핸들러 트리거)."""
    clicks = 0
    seen_handles: set[int] = set()

    for sel in _CLOSE_BTN_SELECTORS:
        try:
            loc = page.locator(sel)
            n = await loc.count()
        except Exception:
            continue
        for i in range(n):
            btn = loc.nth(i)
            try:
                if not await btn.is_visible(timeout=300):
                    continue
            except Exception:
                continue
            # 동일 노드 중복 클릭 방지 (여러 selector 가 겹칠 수 있음)
            try:
                box = await btn.bounding_box()
                key = hash((sel, i, round(box["x"]) if box else 0, round(box["y"]) if box else 0))
                if key in seen_handles:
                    continue
                seen_handles.add(key)
            except Exception:
                pass
            try:
                await btn.click(timeout=2500, force=True)
                clicks += 1
                logger(f"  [WETAX pop] click {sel!r} #{i}")
                await asyncio.sleep(0.25)
            except Exception as e:
                logger(f"  [WETAX pop] click fail {sel!r} #{i}: {e}")
    return clicks


async def dismiss_popups(
    page,
    *,
    max_rounds: int = 6,
    pause_sec: float = 0.4,
    logger: Callable[[str], None] | None = None,
) -> int:
    """보이는 위택스 팝업을 감지해 모두 닫는다.

    - 개수가 랜덤이어도 `main-popup-event` / `pop_*` / `close-btn` 패턴으로 처리.
    - Playwright real click 우선 (위택스 fnCloseBtn = jQuery 바인딩, DOM .click() 불충분).
    - 클릭 후에도 남으면 style.display=none 폴백.
    - 여러 라운드 반복으로 지연 로딩 팝업 대응.

    Returns:
        닫기 클릭(또는 hide) 총 횟수.
    """
    _log = logger or log
    total = 0

    for round_i in range(1, max_rounds + 1):
        try:
            visible = await page.evaluate(_COUNT_VISIBLE_JS)
        except Exception:
            visible = []

        if not visible and round_i > 1:
            break

        if visible:
            _log(f"  [WETAX pop] round={round_i} visible={visible}")

        clicks = await _click_close_buttons(page, _log)
        total += clicks

        # 프레임 내부 팝업 (있다면)
        for fr in page.frames:
            if fr is page.main_frame:
                continue
            try:
                # frame 에 locator 는 page.frame_locator 가 더 안전하지만
                # close-btn 이 메인에 있는 경우가 대부분. JS hide 만 보조.
                hid = await fr.evaluate(_HIDE_REMAINING_JS)
                if hid:
                    _log(f"  [WETAX pop] frame hide {hid}")
                    total += len(hid)
            except Exception:
                pass

        await asyncio.sleep(pause_sec)

        try:
            still = await page.evaluate(_COUNT_VISIBLE_JS)
        except Exception:
            still = []

        if still:
            # jQuery .hide() 상당 폴백
            try:
                hid = await page.evaluate(_HIDE_REMAINING_JS)
                if hid:
                    _log(f"  [WETAX pop] fallback hide {hid}")
                    total += len(hid)
            except Exception:
                pass
            await asyncio.sleep(0.2)
            try:
                still = await page.evaluate(_COUNT_VISIBLE_JS)
            except Exception:
                still = []

        if not still:
            if total:
                _log(f"  [WETAX pop] 모두 닫힘 (actions={total})")
            else:
                _log("  [WETAX pop] 열린 팝업 없음")
            return total

        if clicks == 0 and round_i >= 2:
            # 더 이상 클릭할 버튼 없음 — hide 폴백만 시도했으므로 종료
            break

    try:
        left = await page.evaluate(_COUNT_VISIBLE_JS)
    except Exception:
        left = []
    if left:
        _log(f"  [WETAX pop] 잔여 팝업: {left}")
    else:
        _log(f"  [WETAX pop] 완료 actions={total}")
    return total


async def dismiss_popups_on_context(
    context,
    *,
    max_rounds: int = 6,
    logger: Callable[[str], None] | None = None,
) -> int:
    """컨텍스트의 모든 페이지에서 팝업 닫기."""
    total = 0
    for pg in list(context.pages):
        try:
            total += await dismiss_popups(pg, max_rounds=max_rounds, logger=logger)
        except Exception as e:
            (logger or log)(f"  [WETAX pop] page skip: {e}")
    return total

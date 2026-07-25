"""위택스 로그인 세션 판정 — runner / 라이브 스크립트 공통."""

from __future__ import annotations

from typing import Callable


_LOGGED_IN_JS = """() => {
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
    if (txt === '로그아웃') return true;
    if (txt === '로그인연장' || txt.includes('로그인연장')) return true;
  }
  return false;
}"""


async def is_logged_in(page) -> bool:
    """단일 페이지 로그인 여부 (wetax.go.kr + 로그아웃/로그인연장)."""
    try:
        url = page.url or ""
        if "wetax.go.kr" not in url:
            return False
        if "logout.do" in url:
            return False
        return bool(await page.evaluate(_LOGGED_IN_JS))
    except Exception:
        return False


async def any_page_logged_in(context, *, prefer_set_page: Callable | None = None) -> bool:
    """context 의 wetax 탭 중 하나라도 로그인이면 True.

    prefer_set_page: 로그인 확인된 page 를 받을 콜백(예: runner 가 self._page 설정).
    """
    if context is None:
        return False
    try:
        pages = list(context.pages)
    except Exception:
        return False
    for pg in pages:
        try:
            if await is_logged_in(pg):
                if prefer_set_page is not None:
                    prefer_set_page(pg)
                return True
        except Exception:
            continue
    return False

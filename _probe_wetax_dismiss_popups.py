"""열린 CDP 위택스 세션에서 팝업 즉시 닫기.

  python _probe_wetax_dismiss_popups.py
"""
from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.automation.wetax._constants import WETAX_HOST
from src.automation.wetax._common import dismiss_popups_on_context, log


async def main() -> int:
    from playwright.async_api import async_playwright
    from src.utils.chrome_cdp import CDP_URL, check_cdp_available

    if not check_cdp_available():
        log("[FAIL] CDP 없음 — Chrome 을 먼저 띄우세요.")
        return 1

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        log(f"[ok] pages={len(context.pages)}")
        for i, pg in enumerate(context.pages):
            log(f"  [{i}] {pg.url}")

        n = await dismiss_popups_on_context(context)
        log(f"[done] dismissed_clicks={n}")

        # 잔여 팝업 재확인
        for pg in context.pages:
            if WETAX_HOST not in (pg.url or ""):
                continue
            left = await pg.evaluate("""() => {
              const vis = el => {
                if (!el) return false;
                const s = getComputedStyle(el);
                if (s.display==='none'||s.visibility==='hidden') return false;
                const r = el.getBoundingClientRect();
                return r.width>40 && r.height>40 && r.top < innerHeight && r.left < innerWidth && r.bottom > 0;
              };
              return [...document.querySelectorAll('div.main-popup-event, div[id^=\"pop_\"]')]
                .filter(vis)
                .map(el => ({id: el.id, cls: (el.className||'').toString().slice(0,40)}));
            }""")
            log(f"  remaining main-popup on {pg.url[:50]}: {left}")

        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

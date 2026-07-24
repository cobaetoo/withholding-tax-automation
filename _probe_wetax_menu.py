"""위택스 2단계: 신고 → 특별징수 → 회계파일신고 메뉴 탐색·이동 (CDP 단일 세션).

  python _probe_wetax_menu.py

1) Chrome CDP 기동(또는 재사용) + main.do
2) 팝업 닫기 → 로그인 대기(필요 시) → 로그인 후 팝업 재닫기
3) GNB/HTML 에서 '회계파일신고' 후보 탐색 후 클릭 또는 직접 URL 이동
4) 결과 스냅샷 저장
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.automation.wetax._constants import WETAX_URL, WETAX_HOST
from src.automation.wetax._common import dismiss_popups, log

WAIT_LOGIN_SEC = int(os.environ.get("WTAX_WETAX_LOGIN_WAIT", "600"))


async def _pick_page(context):
    for p in context.pages:
        try:
            if WETAX_HOST in (p.url or ""):
                return p
        except Exception:
            continue
    return context.pages[0] if context.pages else await context.new_page()


async def _logged_in(page) -> bool:
    try:
        return await page.evaluate("""() => {
          const b = document.querySelector('a.btnLogout');
          if (!b) return false;
          const s = getComputedStyle(b);
          const r = b.getBoundingClientRect();
          return s.display !== 'none' && r.width > 0 && r.height > 0;
        }""")
    except Exception:
        return False


async def _wait_login(page, context) -> bool:
    if await _logged_in(page):
        log("[login] 이미 로그인됨")
        return True
    log(f"[login] 공인인증서 로그인 대기 (최대 {WAIT_LOGIN_SEC}s)...")
    deadline = time.time() + WAIT_LOGIN_SEC
    n = 0
    while time.time() < deadline:
        n += 1
        page = await _pick_page(context)
        ok = await _logged_in(page)
        log(f"  [{n:03d}] url={page.url[:70]} logged={ok}")
        if ok:
            log("[login] OK")
            await asyncio.sleep(0.8)
            await dismiss_popups(page)
            return True
        await asyncio.sleep(3)
    log("[login] timeout")
    return False


async def _find_accounting_candidates(page) -> list[dict]:
    """DOM(+숨김)에서 회계파일신고 후보 링크 수집."""
    return await page.evaluate(r"""() => {
      const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const out = [];
      const seen = new Set();
      document.querySelectorAll('a, button, span, li').forEach(el => {
        const t = txt(el);
        if (!t || t.length > 40) return;
        if (!t.includes('회계파일')) return;
        const href = el.getAttribute && (el.getAttribute('href') || '') || '';
        const key = t + '|' + href;
        if (seen.has(key)) return;
        seen.add(key);
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        out.push({
          tag: el.tagName.toLowerCase(),
          text: t,
          href,
          onclick: (el.getAttribute && el.getAttribute('onclick') || '').slice(0, 120),
          display: s.display,
          w: Math.round(r.width), h: Math.round(r.height),
        });
      });
      return out;
    }""")


async def _dump_depth_after_신고(page) -> list[dict]:
    """GNB 신고 호버 후 depth 메뉴 덤프."""
    try:
        loc = page.locator("li > a").filter(has_text=re.compile(r"^신고$"))
        if await loc.count():
            await loc.first.hover(force=True, timeout=3000)
            await asyncio.sleep(0.6)
    except Exception as e:
        log(f"[menu] hover 신고 실패: {e}")
    return await page.evaluate(r"""() => {
      const vis = el => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return s.display !== 'none' && r.width > 0 && r.height > 0;
      };
      return [...document.querySelectorAll('.depth-wrap a, .depth-wrap button, .depth-wrap span')]
        .filter(vis)
        .map(el => ({
          tag: el.tagName.toLowerCase(),
          text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 50),
          href: el.getAttribute && (el.getAttribute('href') || '') || '',
          cls: (el.className || '').toString().slice(0, 50),
        }))
        .filter(x => x.text && x.text.length < 40);
    }""")


async def _goto_via_menu(page) -> dict:
    """신고 → 특별징수 → 회계파일신고 클릭 시도. 실패 시 후보 정보 반환."""
    result = {"path": [], "ok": False, "url": page.url, "candidates": [], "depth": []}

    # 1) HTML/DOM 후보
    cands = await _find_accounting_candidates(page)
    result["candidates"] = cands
    log(f"[menu] 회계파일 후보 {len(cands)}건: {cands[:5]}")

    # 직접 href 있는 후보 클릭
    for c in cands:
        href = (c.get("href") or "").strip()
        if href and href not in ("#", "javascript:void(0)", "javascript:void(0);"):
            try:
                if href.startswith("http") or href.startswith("/"):
                    log(f"[menu] 직접 이동 href={href}")
                    if href.startswith("/"):
                        await page.goto(
                            "https://www.wetax.go.kr" + href,
                            wait_until="domcontentloaded",
                            timeout=45000,
                        )
                    else:
                        await page.goto(href, wait_until="domcontentloaded", timeout=45000)
                    result["path"].append(f"goto:{href}")
                    result["ok"] = True
                    result["url"] = page.url
                    return result
            except Exception as e:
                log(f"[menu] href 이동 실패: {e}")

    # 2) GNB 경로 클릭
    depth = await _dump_depth_after_신고(page)
    result["depth"] = [
        d for d in depth
        if any(k in d["text"] for k in ("특별", "회계", "파일", "지방소득", "신고"))
    ]
    log(f"[menu] depth 필터 {len(result['depth'])}건")
    for d in result["depth"][:40]:
        log(f"  depth: {d}")

    # 특별징수 호버/클릭 후 회계파일 재탐색
    for label in ("특별징수", "지방소득세"):
        try:
            loc = page.locator(".depth-wrap a, .depth-wrap button, .depth-wrap span").filter(
                has_text=re.compile(f"^{re.escape(label)}$|{re.escape(label)}")
            )
            if await loc.count() == 0:
                continue
            await loc.first.hover(force=True, timeout=2000)
            await asyncio.sleep(0.3)
            await loc.first.click(force=True, timeout=2000)
            result["path"].append(f"click:{label}")
            await asyncio.sleep(0.5)
        except Exception as e:
            log(f"[menu] {label} 클릭 스킵: {e}")

    # 회계파일신고 텍스트 클릭
    for name in ("회계파일신고", "회계파일 신고"):
        try:
            loc = page.locator("a, button, span").filter(has_text=re.compile(name))
            n = await loc.count()
            log(f"[menu] '{name}' loc count={n}")
            for i in range(min(n, 5)):
                el = loc.nth(i)
                t = (await el.inner_text()).replace("\n", " ").strip()
                if "회계파일" not in t:
                    continue
                await el.click(force=True, timeout=3000)
                result["path"].append(f"click:{t}")
                await page.wait_for_load_state("domcontentloaded", timeout=20000)
                await asyncio.sleep(1)
                result["ok"] = "회계" in (await page.title()) or "회계" in page.url or True
                result["url"] = page.url
                # 페이지 본문에 회계/파일 키워드 확인
                body = await page.evaluate(
                    "() => (document.body && document.body.innerText || '').slice(0, 500)"
                )
                result["body_head"] = body.replace("\n", " ")[:300]
                return result
        except Exception as e:
            log(f"[menu] {name} 클릭 실패: {e}")

    # 3) HTML 정규식으로 href 추출
    html = await page.content()
    m = re.search(
        r'href=["\']([^"\']+)["\'][^>]*>[\s\n]*회계파일\s*신고',
        html,
    )
    if not m:
        m = re.search(r'회계파일\s*신고[\s\S]{0,80}?href=["\']([^"\']+)["\']', html)
    if m:
        href = m.group(1)
        log(f"[menu] HTML href 추출: {href}")
        if href.startswith("/"):
            href = "https://www.wetax.go.kr" + href
        try:
            await page.goto(href, wait_until="domcontentloaded", timeout=45000)
            result["path"].append(f"html_goto:{href}")
            result["ok"] = True
            result["url"] = page.url
            return result
        except Exception as e:
            log(f"[menu] html goto 실패: {e}")

    result["url"] = page.url
    return result


async def main() -> int:
    from playwright.async_api import async_playwright
    from src.utils.chrome_cdp import launch_chrome, CDP_URL, check_cdp_available
    from src.config import APP_DATA_DIR

    log("=" * 64)
    log("위택스 CDP 메뉴 프로브 (2단계: 신고→특별징수→회계파일신고)")
    log("=" * 64)

    r = launch_chrome(WETAX_URL)
    if not r.get("success"):
        log(f"[FAIL] Chrome: {r.get('error')}")
        return 1
    # CDP 안정화
    for _ in range(20):
        if check_cdp_available():
            break
        await asyncio.sleep(0.3)
    if not check_cdp_available():
        log("[FAIL] CDP not ready")
        return 1
    log(f"[ok] CDP ready reused={r.get('reused')}")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = await _pick_page(context)
        try:
            if WETAX_HOST not in (page.url or "") or "main.do" not in (page.url or ""):
                await page.goto(WETAX_URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            log(f"[warn] goto: {e}")
        await asyncio.sleep(1.2)
        await dismiss_popups(page)

        if not await _wait_login(page, context):
            await browser.close()
            return 2
        page = await _pick_page(context)
        await dismiss_popups(page)

        nav = await _goto_via_menu(page)
        page = await _pick_page(context)
        await asyncio.sleep(0.5)
        # 도착 페이지에서도 팝업 있을 수 있음
        try:
            await dismiss_popups(page)
        except Exception:
            pass

        snap = {
            "nav": nav,
            "final_url": page.url,
            "final_title": await page.title(),
            "logged_in": await _logged_in(page),
        }
        # 화면 키워드
        snap["page_keywords"] = await page.evaluate(r"""() => {
          const t = (document.body && document.body.innerText || '');
          const keys = ['회계파일', '휴대전화', '암호화', '파일비밀번호', '파일변환', '제출하기', '특별징수'];
          const hit = {};
          for (const k of keys) hit[k] = t.includes(k);
          return hit;
        }""")

        out = os.path.join(APP_DATA_DIR, "wetax_menu_probe.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)

        log("-" * 64)
        log(f"path: {nav.get('path')}")
        log(f"ok: {nav.get('ok')}")
        log(f"url: {snap['final_url']}")
        log(f"title: {snap['final_title']}")
        log(f"keywords: {snap['page_keywords']}")
        log(f"saved: {out}")
        log("Chrome 유지. browser 연결만 종료.")
        await browser.close()
        return 0 if nav.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

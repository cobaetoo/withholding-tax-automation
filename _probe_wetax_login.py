"""위택스 1단계: CDP 전용 로그인 프로브 (GUI 없음)

사용법:
  python _probe_wetax_login.py

동작:
  1) Chrome 을 CDP(9223)로 기동 → https://www.wetax.go.kr/main.do
  2) 사용자가 전자세금용 공인인증서로 수동 로그인
  3) 로그인 완료 감지('로그아웃' 등) 또는 최대 대기 후 DOM 스냅샷 덤프
  4) 결과: 콘솔 + wetax_login_probe.json

읽기 위주. 로그인 UI 클릭은 하지 않음.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time

if sys.platform == "win32":
    # detach() 금지 — 세션 로그 리다이렉트/파이프를 끊을 수 있음. reconfigure 만 사용.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.automation.wetax._constants import WETAX_URL, WETAX_HOST

# 최대 로그인 대기(초). 인증서 UI 시간 여유.
WAIT_LOGIN_SEC = int(os.environ.get("WTAX_WETAX_LOGIN_WAIT", "600"))
POLL_SEC = 3

_SNAPSHOT_JS = r"""
() => {
  const vis = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const txtOf = (el) => (el.innerText || el.value || el.title || el.getAttribute('aria-label') || '')
    .replace(/\s+/g, ' ').trim().slice(0, 80);

  const out = {
    url: location.href,
    title: document.title,
    has_logout: false,
    has_login: false,
    logout_samples: [],
    login_samples: [],
    header_links: [],
    keyword_hits: [],
  };

  const all = document.querySelectorAll('a, button, input, span, li, div, p');
  // 1순위: a.btnLogout (라이브 확정 시그널)
  const btnLogout = document.querySelector('a.btnLogout');
  if (btnLogout && vis(btnLogout)) {
    out.has_logout = true;
    out.logout_samples.push({
      tag: 'a', id: btnLogout.id || '', cls: 'btnLogout',
      text: txtOf(btnLogout) || '로그아웃',
    });
  }

  for (const el of all) {
    if (!vis(el)) continue;
    const t = txtOf(el);
    if (!t || t.length > 40) continue;
    if (t === '로그아웃' || (t.includes('로그아웃') && t.length <= 12)) {
      out.has_logout = true;
      if (out.logout_samples.length < 5) {
        out.logout_samples.push({
          tag: el.tagName.toLowerCase(),
          id: el.id || '',
          cls: (el.className || '').toString().slice(0, 80),
          text: t,
        });
      }
    }
    if (t === '로그인' || (t.includes('로그인') && !t.includes('로그아웃'))) {
      out.has_login = true;
      if (out.login_samples.length < 5) {
        out.login_samples.push({
          tag: el.tagName.toLowerCase(),
          id: el.id || '',
          cls: (el.className || '').toString().slice(0, 80),
          text: t,
        });
      }
    }
  }

  // 헤더/내비 후보 링크
  document.querySelectorAll('header a, nav a, .gnb a, #gnb a, .header a, a').forEach(a => {
    if (!vis(a)) return;
    const t = txtOf(a);
    if (!t || t.length > 30) return;
    if (out.header_links.length >= 40) return;
    out.header_links.push({
      text: t,
      href: (a.getAttribute('href') || '').slice(0, 120),
      id: a.id || '',
    });
  });

  // 워크플로우 키워드
  const KW = ['신고', '특별징수', '회계파일', '공인인증', '인증서', '로그인', '로그아웃', '회원'];
  const seen = new Set();
  for (const el of all) {
    if (!vis(el)) continue;
    const t = txtOf(el);
    if (!t || t.length > 40) continue;
    if (!KW.some(k => t.includes(k))) continue;
    const key = el.tagName + '|' + t;
    if (seen.has(key)) continue;
    seen.add(key);
    if (out.keyword_hits.length >= 50) break;
    out.keyword_hits.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || '',
      cls: (el.className || '').toString().slice(0, 60),
      text: t,
    });
  }
  return out;
}
"""


async def _pick_wetax_page(context):
    for p in context.pages:
        try:
            if WETAX_HOST in (p.url or ""):
                return p
        except Exception:
            continue
    return context.pages[0] if context.pages else await context.new_page()


async def _snapshot(page):
    try:
        return await asyncio.wait_for(page.evaluate(_SNAPSHOT_JS), timeout=8)
    except Exception as e:
        return {"url": getattr(page, "url", "?"), "error": str(e)}


async def main():
    from playwright.async_api import async_playwright
    from src.utils.chrome_cdp import launch_chrome, CDP_URL
    from src.config import APP_DATA_DIR
    from src.utils.stealth import stealth_all_pages

    print("=" * 64, flush=True)
    print("위택스 CDP 로그인 프로브 (1단계)", flush=True)
    print("=" * 64, flush=True)

    result = launch_chrome(WETAX_URL)
    if not result.get("success"):
        print(f"[FAIL] Chrome 실행 실패: {result.get('error')}", flush=True)
        return 1
    print(
        f"[ok] Chrome CDP ready  reused={result.get('reused', False)}  "
        f"pid={result.get('pid')}",
        flush=True,
    )

    async with async_playwright() as p:
        print(f"[cdp] connect_over_cdp {CDP_URL} ...", flush=True)
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        try:
            await stealth_all_pages(context)
        except Exception as e:
            print(f"[warn] stealth 스킵: {e}", flush=True)
        page = await _pick_wetax_page(context)
        print(f"[ok] connected pages={len(context.pages)}", flush=True)

        # 위택스 메인 보장
        try:
            if WETAX_HOST not in (page.url or ""):
                print(f"[nav] 현재 URL={page.url} → {WETAX_URL}")
                await page.goto(WETAX_URL, wait_until="domcontentloaded", timeout=45000)
            else:
                # 이미 wetax 이면 main.do 로 한 번 맞춤
                if "main.do" not in (page.url or ""):
                    await page.goto(WETAX_URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"[warn] goto 지연/실패(계속 대기): {e}")

        print(f"[page] {page.url}", flush=True)

        # 로그인 대기 직전: 메인 이벤트 팝업 등 닫기
        from src.automation.wetax._common import dismiss_popups
        print("[pop] 로그인 대기 직전 팝업 닫기...", flush=True)
        await asyncio.sleep(1.0)  # 팝업 렌더 여유
        await dismiss_popups(page)

        print()
        print("▶ 브라우저에서 전자세금용 공인인증서로 로그인해 주세요.")
        print(f"  (최대 {WAIT_LOGIN_SEC}초 대기, {POLL_SEC}초 간격 폴링)")
        print()

        logged_in = False
        last = None
        deadline = time.time() + WAIT_LOGIN_SEC
        n = 0
        while time.time() < deadline:
            n += 1
            # 탭이 바뀌었을 수 있음(팝업/리다이렉트)
            page = await _pick_wetax_page(context)
            last = await _snapshot(page)
            url = last.get("url", page.url)
            has_out = last.get("has_logout")
            has_in = last.get("has_login")
            print(
                f"  [{n:03d}] url={url[:70]}  logout={has_out}  login={has_in}"
                + (f"  err={last.get('error')}" if last.get("error") else "")
            )
            if has_out:
                logged_in = True
                print("\n[ok] 로그인 감지: 화면에 '로그아웃' 확인")
                # 로그인 후 main.do 재진입 시 팝업이 다시 뜸 → 한 번 더 닫기
                print("[pop] 로그인 후 팝업 닫기...", flush=True)
                await asyncio.sleep(0.8)
                page = await _pick_wetax_page(context)
                await dismiss_popups(page)
                break
            await asyncio.sleep(POLL_SEC)

        if not logged_in:
            print("\n[timeout] 로그인 미감지 — 현재 DOM 기준으로 스냅샷 저장합니다.")
            print("  (로그인 후에도 logout=False 이면 판정 기준을 바꿔야 합니다)")

        # 최종 스냅샷(프레임 포함 요약)
        page = await _pick_wetax_page(context)
        final = await _snapshot(page)
        frames_info = []
        for fr in page.frames:
            try:
                frames_info.append({"url": fr.url, "name": fr.name})
            except Exception:
                pass

        payload = {
            "logged_in_detected": logged_in,
            "final": final,
            "frames": frames_info,
            "wait_sec": WAIT_LOGIN_SEC,
            "poll_sec": POLL_SEC,
        }
        out_path = os.path.join(APP_DATA_DIR, "wetax_login_probe.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print()
        print("-" * 64)
        print(f"최종 URL : {final.get('url')}")
        print(f"title    : {final.get('title')}")
        print(f"logout   : {final.get('has_logout')}  samples={final.get('logout_samples')}")
        print(f"login    : {final.get('has_login')}  samples={final.get('login_samples')}")
        print(f"keyword  : {len(final.get('keyword_hits') or [])} hits")
        for h in (final.get("keyword_hits") or [])[:20]:
            print(f"   <{h['tag']} id={h['id']!r}> {h['text']}")
        print(f"header_links (최대 15):")
        for a in (final.get("header_links") or [])[:15]:
            print(f"   {a['text']!r}  href={a['href']!r}")
        print(f"\n저장: {out_path}")
        print("-" * 64)
        print("Chrome/CDP 는 열린 채로 둡니다. 다음 단계 프로브에 재사용하세요.")
        # browser 연결만 끊고 Chrome 프로세스는 유지
        await browser.close()

    return 0 if logged_in else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

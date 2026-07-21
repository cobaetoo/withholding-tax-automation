"""지방소득세 특별징수 메뉴 코드 라이브 프로브 (Part B 발견 도구, 읽기 전용)

사용법:
  1) Chrome 을 CDP 모드(포트 9223)로 실행하고 WEHAGO 공동인증서 로그인
  2) 테스트 수임처의 SmartA 급여 페이지(급여자료입력 등)에 진입
     — 좌측 메뉴 트리가 렌더된 상태여야 함(원천세 메뉴가 보이는 화면)
  3) 새 터미널에서:  python _probe_jitax_menu.py

동작: 현재 열린 WEHAGO 탭(및 iframe)에서 좌측 메뉴 링크(a.text_link)의 id/텍스트를
모두 덤프하고, '지방소득세특별징수납부서' / '지방소득세특별징수전자신고' 후보를
자동으로 찾아 그 id(= goto_menu_page 에 넣을 메뉴 코드)를 출력한다. 클릭/네비게이션
없음(읽기 전용). 결과는 콘솔 + APP_DATA_DIR/jitax_menu_probe.txt 로 저장.
"""
import asyncio
import io
import json
import os
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding="utf-8")

# 클릭으로 찾을 대상 메뉴명(부분일치). 공백 변형 대비해 정규화 비교.
TARGETS = ["지방소득세특별징수납부서", "지방소득세특별징수전자신고"]

# 좌측 메뉴/후보 요소를 프레임 단위로 덤프하는 JS.
_DUMP_JS = r"""
() => {
  const norm = s => (s || "").replace(/\s+/g, "").trim();
  const out = { url: location.href, text_links: [], keyword_hits: [] };

  // 1) 사이드바 메뉴 앵커: a.text_link (click_menu 가 a#<CODE>.text_link 로 선택)
  document.querySelectorAll("a.text_link, a[id].text_link, a[class*='text_link']").forEach(a => {
    const id = a.id || "";
    const txt = norm(a.textContent);
    if (id || txt) out.text_links.push({ id, text: txt, visible: a.offsetWidth > 0 });
  });

  // 2) 키워드 포함 요소(메뉴가 text_link 가 아닐 경우 대비): 지방/특별징수/납부서/전자신고
  const KW = ["지방소득세", "특별징수", "지방세"];
  const seen = new Set();
  document.querySelectorAll("a, button, li, span, div").forEach(el => {
    const txt = norm(el.textContent);
    if (!txt || txt.length > 40) return;          // 컨테이너(긴 텍스트) 제외
    if (!KW.some(k => txt.includes(k))) return;
    const key = el.tagName + "|" + (el.id || "") + "|" + txt;
    if (seen.has(key)) return; seen.add(key);
    out.keyword_hits.push({
      tag: el.tagName.toLowerCase(), id: el.id || "",
      cls: (el.className || "").toString().slice(0, 60),
      text: txt, visible: el.offsetWidth > 0,
    });
  });
  return out;
};
"""


async def _dump_frame(frame, label):
    try:
        return await frame.evaluate(_DUMP_JS)
    except Exception as e:
        return {"url": getattr(frame, "url", "?"), "error": str(e),
                "text_links": [], "keyword_hits": []}


def _match_targets(all_text_links):
    """text_links 에서 TARGETS 와 일치하는 항목의 id 를 반환."""
    norm = lambda s: "".join((s or "").split())
    result = {}
    for tgt in TARGETS:
        hit = next((tl for tl in all_text_links if norm(tl.get("text")) == norm(tgt)), None)
        if not hit:  # 부분일치 폴백
            hit = next((tl for tl in all_text_links if norm(tgt) in norm(tl.get("text"))), None)
        result[tgt] = hit
    return result


async def main():
    from playwright.async_api import async_playwright
    from src.utils.chrome_cdp import launch_chrome, connect_page
    from src.config import APP_DATA_DIR

    launch_chrome()  # CDP 살아있으면 재사용(로그인 세션 보존)
    async with async_playwright() as p:
        browser, context, page = await connect_page(p)
        print(f"[probe] 연결됨: {page.url}\n")

        frames = [(page.main_frame, "main")] + [
            (f, f.url) for f in page.frames if f is not page.main_frame
        ]
        dumps = []
        all_text_links = []
        for fr, label in frames:
            d = await _dump_frame(fr, label)
            d["_frame"] = label
            dumps.append(d)
            all_text_links.extend(d.get("text_links", []))

        # ── 후보 매칭 ──
        matched = _match_targets(all_text_links)
        print("=" * 68)
        print("지방소득세 메뉴 코드 후보 (a.text_link id = goto_menu_page 메뉴 코드)")
        print("=" * 68)
        for tgt, hit in matched.items():
            if hit and hit.get("id"):
                print(f"  ✅ {tgt}\n       menu_code = {hit['id']!r}  (visible={hit['visible']})")
            elif hit:
                print(f"  ⚠️  {tgt}\n       텍스트는 찾았으나 id 없음: {hit}")
            else:
                print(f"  ❌ {tgt} — text_link 미발견 (아래 keyword_hits 확인)")
        print()

        # ── 전체 text_link 덤프(원천세 코드가 보이면 형식 확인용) ──
        print("-" * 68)
        print(f"전체 a.text_link ({len(all_text_links)}개) — id 있는 것만:")
        for tl in all_text_links:
            if tl.get("id"):
                print(f"   {tl['id']:<12} {tl['text'][:36]}  (vis={tl['visible']})")

        # ── 키워드 히트(지방소득세/특별징수) ──
        kw = [h for d in dumps for h in d.get("keyword_hits", [])]
        print("-" * 68)
        print(f"키워드 히트 ({len(kw)}개):")
        for h in kw:
            print(f"   <{h['tag']} id={h['id']!r}> {h['text'][:40]}  (vis={h['visible']}) cls={h['cls']}")

        # ── 파일 저장 ──
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        out_path = os.path.join(APP_DATA_DIR, "jitax_menu_probe.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"matched": matched, "dumps": dumps},
                               ensure_ascii=False, indent=2))
        print(f"\n[probe] 상세 저장 → {out_path}")
        print("\n다음: 위 menu_code 를 run_jitax_payment.py / run_jitax_efile.py 의 "
              "JITAX_*_MENU_CODE 에 채운 뒤, __main__ 블록으로 네비게이션 스모크 진행.")


if __name__ == "__main__":
    asyncio.run(main())

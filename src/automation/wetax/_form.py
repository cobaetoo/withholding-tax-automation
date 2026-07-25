"""위택스 회계파일신고 폼 입력 — 휴대전화·파일·비밀번호 등."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Callable

from src.automation.wetax._common import log, mask_phone
from src.automation.wetax._constants import (
    ACCOUNTING_CONVERT_RESULT_PATH,
    ACCOUNTING_FILE_REPORT_PATH,
    ACCOUNTING_SUBMIT_RESULT_PATH,
    BTN_CONVERT,
    BTN_SUBMIT,
    FIELD_MOBILE,
    FIELD_FILE_PW,
    FIELD_FILE_INPUT,
    JITAX_EFILE_EXTS,
    JITAX_EFILE_SITE,
    LABEL_CONVERT,
    LABEL_SUBMIT,
)
from src.automation.wetax._dialogs import accept_native_dialogs
from src.utils.save_path import make_save_dir


async def fill_mobile_phone(
    page,
    phone: str,
    *,
    logger: Callable[[str], None] | None = None,
) -> bool:
    """휴대전화번호 입력 — #dclrRlpMblTelno (xpath //*[@id='dclrRlpMblTelno']).

    Args:
        page: Playwright page (회계파일신고 화면)
        phone: GUI 에서 받은 번호. 예) 010-1234-5678
    """
    _log = logger or log
    phone = (phone or "").strip()
    if not phone:
        _log("  [WETAX form] 휴대전화 비어 있음")
        return False

    loc = page.locator(f"#{FIELD_MOBILE}")
    try:
        await loc.wait_for(state="visible", timeout=10000)
    except Exception as e:
        _log(f"  [WETAX form] #{FIELD_MOBILE} 미표시: {e}")
        return False

    try:
        await loc.scroll_into_view_if_needed(timeout=3000)
        await loc.click(timeout=3000)
        await loc.fill("")
        await loc.fill(phone)
        # input/change 이벤트 보장 (일부 검증 스크립트)
        await loc.evaluate(
            """(el, v) => {
              el.value = v;
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            phone,
        )
        await asyncio.sleep(0.2)
        actual = await loc.input_value()
        # 하이픈 유무 차이 허용 — 숫자만 비교
        digits = lambda s: "".join(c for c in s if c.isdigit())
        if digits(actual) != digits(phone) and actual.strip() != phone:
            _log(
                f"  [WETAX form] 휴대전화 불일치 "
                f"expect={mask_phone(phone)!r} got={mask_phone(actual)!r}"
            )
            return False
        _log(f"  [WETAX form] 휴대전화 입력 완료: {mask_phone(actual)}")
        return True
    except Exception as e:
        _log(f"  [WETAX form] 휴대전화 입력 실패: {e}")
        return False


async def enter_file_password(
    page,
    password: str,
    *,
    logger: Callable[[str], None] | None = None,
) -> bool:
    """전자신고 파일 비밀번호 입력 — #filePw (홈택스 스타일 native setter 주입).

    GUI 툴바 '비밀번호' 필드(needs_password, 홈택스 원천세와 동일 UI 패턴)에서
    받은 값을 회계파일신고 화면의 파일비밀번호 칸에 넣는다.

    홈택스 enter_password 와 같이 HTMLInputElement.prototype value setter +
    input/change/keyup 이벤트로 주입해 프레임워크 바인딩을 탄다.
    (위택스는 팝업이 아니라 본문 password input.)
    """
    _log = logger or log
    password = password or ""
    if not password:
        _log("  [WETAX form] 파일비밀번호 비어 있음")
        return False

    loc = page.locator(f"#{FIELD_FILE_PW}")
    try:
        await loc.wait_for(state="visible", timeout=10000)
    except Exception as e:
        _log(f"  [WETAX form] #{FIELD_FILE_PW} 미표시: {e}")
        return False

    try:
        await loc.scroll_into_view_if_needed(timeout=3000)
        await loc.click(timeout=3000)
        # 홈택스 패턴: native setter + 이벤트 (type=password 에서 fill 만으로 부족한 경우 대비)
        set_len = await page.evaluate(
            """({ sel, pwd }) => {
              const inp = document.querySelector(sel);
              if (!inp) return -1;
              const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
              setter.call(inp, pwd);
              inp.dispatchEvent(new Event('input', { bubbles: true }));
              inp.dispatchEvent(new Event('change', { bubbles: true }));
              inp.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
              return (inp.value || '').length;
            }""",
            {"sel": f"#{FIELD_FILE_PW}", "pwd": password},
        )
        if set_len != len(password):
            # 폴백: Playwright fill
            await loc.fill("")
            await loc.fill(password)
            actual = await loc.input_value()
            if len(actual) != len(password):
                _log(
                    f"  [WETAX form] 파일비밀번호 주입 실패 "
                    f"(기대 len={len(password)}, 실제 {set_len}/{len(actual)})"
                )
                return False
        await asyncio.sleep(0.2)
        # 값은 로그에 찍지 않음 (보안) — 길이만
        _log(f"  [WETAX form] 파일비밀번호 입력 완료 (len={len(password)})")
        return True
    except Exception as e:
        _log(f"  [WETAX form] 파일비밀번호 입력 실패: {e}")
        return False


def find_jitax_encrypted_file(
    client_name: str,
    year: int | None = None,
    month: int | None = None,
) -> str | None:
    """Phase 11 컨벤션 폴더에서 전자신고 파일 최신 1개 경로 반환.

    경로: {바탕화면}/지방소득세전자신고_{YYYYMM}/{수임처}/
    허용 확장자: `.1`, `.2` (대소문자 무시). 그 외 파일은 스킵.
    허용 파일이 없으면 None (임의 파일 폴백 없음).
    """
    save_dir = make_save_dir(JITAX_EFILE_SITE, client_name, year=year, month=month)
    if not os.path.isdir(save_dir):
        return None
    allowed = {ext.lower() for ext in JITAX_EFILE_EXTS}
    files: list[str] = []
    for name in os.listdir(save_dir):
        if name.startswith("."):
            continue
        path = os.path.join(save_dir, name)
        if not os.path.isfile(path):
            continue
        _, ext = os.path.splitext(name)
        if ext.lower() not in allowed:
            continue
        files.append(path)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


async def select_encrypted_file(
    page,
    file_path: str,
    *,
    logger: Callable[[str], None] | None = None,
) -> bool:
    """암호화 전자신고 파일 선택 — #file_upload_0_ (input type=file).

    네이티브 파일 다이얼로그 대신 set_input_files 로 주입.
    """
    _log = logger or log
    if not file_path or not os.path.isfile(file_path):
        _log(f"  [WETAX form] 파일 없음: {file_path!r}")
        return False

    _log(f"  [WETAX form] 파일 선택: {os.path.basename(file_path)}")
    sel = f"#{FIELD_FILE_INPUT}"
    # 메인 문서 + 프레임 순회 (홈택스와 유사)
    for attempt in range(15):
        try:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.set_input_files(file_path)
                try:
                    await page.evaluate(
                        """(id) => {
                          const fi = document.getElementById(id);
                          if (fi) {
                            fi.dispatchEvent(new Event('input', { bubbles: true }));
                            fi.dispatchEvent(new Event('change', { bubbles: true }));
                          }
                        }""",
                        FIELD_FILE_INPUT,
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.8)
                _log("  [WETAX form] 파일 설정 완료")
                return True
        except Exception as e:
            _log(f"  [WETAX form] 파일 input 시도 실패: {e}")

        for frame in list(page.frames):
            try:
                floc = frame.locator('input[type="file"]')
                if await floc.count() > 0:
                    await floc.first.set_input_files(file_path)
                    try:
                        await frame.evaluate("""() => {
                          const fi = document.querySelector('input[type="file"]');
                          if (fi) {
                            fi.dispatchEvent(new Event('input', { bubbles: true }));
                            fi.dispatchEvent(new Event('change', { bubbles: true }));
                          }
                        }""")
                    except Exception:
                        pass
                    await asyncio.sleep(0.8)
                    _log("  [WETAX form] 파일 설정 완료 (frame)")
                    return True
            except Exception:
                continue
        await asyncio.sleep(1.0)

    _log("  [WETAX form] 파일 input 을 찾지 못함")
    return False


async def click_convert_file(
    page,
    *,
    logger: Callable[[str], None] | None = None,
    timeout_s: float = 60.0,
    result_out: dict | None = None,
) -> bool:
    """파일변환하기 클릭 — M31 `#btn_next` → 서식검증 화면(M32).

    라이브 확인 (2026-07-24):
      1) confirm: "업로드 하신 회계 파일의 신고정보를 검증하시겠습니까?"
      2) 수락 후 URL `B070101M32.do` (정상/오류 내역 표)
      3) 동일 id `#btn_next` 가 M32 에서 "제출하기" 로 바뀜

    Playwright 의 dialog accept 가 CDP 에서 레이스 나기 쉬워
    `accept_native_dialogs` 로 임시 수락 후 DOM click (finally 복원).
    변환 자체 성공 ≠ 신고 정상(오류 1건이어도 True — 제출 단계에서 판단).

    Args:
        result_out: 제공 시 성공 시 `{ok, err, url}` 로 채움 (W4-lite).
    """
    _log = logger or log
    sel = f"#{BTN_CONVERT}"

    async def _fill_result(summary: dict | None = None) -> None:
        if result_out is None:
            return
        if summary is None:
            try:
                summary = await get_convert_result_summary(page)
            except Exception:
                summary = {"ok": None, "err": None, "url": ""}
        result_out.clear()
        result_out.update(summary)

    # 이미 M32 면 이전 수임처 검증 잔존 가능 → M31 재진입 후 변환 (생략 금지)
    try:
        url0 = page.url or ""
        if ACCOUNTING_CONVERT_RESULT_PATH in url0:
            _log("  [WETAX form] 이미 서식검증 화면(M32) — M31 재진입 후 변환")
            from src.automation.wetax._navigation import ensure_upload_form
            back = await ensure_upload_form(page, logger=_log)
            if not back:
                _log("  [WETAX form] M32→M31 재진입 실패 — 변환 중단")
                return False
    except Exception as e:
        _log(f"  [WETAX form] M32 선처리 실패: {e}")
        return False

    loc = page.locator(sel)
    try:
        await loc.first.wait_for(state="visible", timeout=15000)
    except Exception as e:
        _log(f"  [WETAX form] 파일변환하기({sel}) 미표시: {e}")
        return False

    # W2: M31 URL + 변환 라벨 필수. 실패 시 클릭 금지 (hard-fail).
    try:
        url = page.url or ""
        label = (await loc.first.inner_text() or "").replace("\n", " ").strip()
        on_m31 = ACCOUNTING_FILE_REPORT_PATH in url
        looks_convert = LABEL_CONVERT in label or "변환" in label
        looks_submit = (
            LABEL_SUBMIT in label
            or ("제출" in label and LABEL_CONVERT not in label and "변환" not in label)
        )
        if looks_submit and not looks_convert:
            _log(
                f"  [WETAX form] 제출 버튼으로 보임 — 변환 거부 "
                f"(url={url!r} label={label!r})"
            )
            return False
        if not looks_convert:
            _log(
                f"  [WETAX form] 변환 라벨 아님 — 변환 거부 "
                f"(url={url!r} label={label!r})"
            )
            return False
        if not on_m31:
            _log(
                f"  [WETAX form] M31 아님 — 변환 거부 (url={url!r})"
            )
            return False
    except Exception as e:
        _log(f"  [WETAX form] 변환 버튼 라벨 확인 실패 — 중단: {e}")
        return False

    try:
        await loc.first.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass

    _log("  [WETAX form] [step] 파일변환하기 클릭")
    clicked = False
    # 클릭 구간에만 confirm 오버라이드 → finally 복원 후 M32 대기
    async with accept_native_dialogs(
        page,
        accept=True,
        message_substr="검증",
        on_mismatch="reject",
        logger=_log,
    ):
        try:
            await loc.first.click(timeout=8000, force=True)
            clicked = True
        except Exception as e:
            _log(f"  [WETAX form] locator 클릭 실패, DOM click 폴백: {e}")
            try:
                await page.evaluate(
                    """(id) => {
                      const b = document.getElementById(id);
                      if (!b) return false;
                      b.scrollIntoView({block: 'center'});
                      b.click();
                      return true;
                    }""",
                    BTN_CONVERT,
                )
                clicked = True
            except Exception as e2:
                _log(f"  [WETAX form] 파일변환하기 클릭 실패: {e2}")
                return False

        try:
            msgs = await page.evaluate("() => window.__wetax_confirm_msgs || []")
            if msgs:
                _log(f"  [WETAX form] confirm/alert: {msgs[0][:80]}")
        except Exception:
            pass

    if not clicked:
        return False

    # M32 도착 대기 (confirm 은 이미 복원된 상태)
    deadline = time.monotonic() + timeout_s
    last_url = ""
    while time.monotonic() < deadline:
        try:
            url = page.url or ""
            last_url = url
            if ACCOUNTING_CONVERT_RESULT_PATH in url:
                summary = await _wait_convert_summary(page, logger=_log)
                _log(
                    f"  [WETAX form] [step] 파일변환 완료 → M32 "
                    f"정상={summary.get('ok')} 오류={summary.get('err')}"
                )
                await _fill_result(summary)
                return True
            has_pw = await page.locator(f"#{FIELD_FILE_PW}").count()
            btn_text = ""
            try:
                if await page.locator(sel).count():
                    btn_text = (await page.locator(sel).first.inner_text() or "")
            except Exception:
                pass
            if has_pw == 0 and ("제출" in btn_text):
                # 폼 전환 직후 표가 아직 안 그려질 수 있음 → 요약 폴링
                summary = await _wait_convert_summary(page, logger=_log)
                _log(
                    f"  [WETAX form] [step] 파일변환 완료 (폼 전환) "
                    f"정상={summary.get('ok')} 오류={summary.get('err')}"
                )
                await _fill_result(summary)
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)

    _log(f"  [WETAX form] 파일변환 후 화면 전환 타임아웃 url={last_url!r}")
    return False


async def get_convert_result_summary(page) -> dict:
    """M32 본문에서 정상/오류 건수·URL 추출 (로그·step_data 용).

    정책: err>0 이어도 호출부에서 실패로 보지 않음 (W4-lite, 정책 미정).
    UI 변형: "정상 신고 내역 1건" / "정상신고내역1건" 모두 허용.
    """
    try:
        data = await page.evaluate(
            """() => {
              const t = (document.body && document.body.innerText) || '';
              const ok = (t.match(/정상\\s*신고\\s*내역\\s*(\\d+)\\s*건/) || [])[1];
              const err = (t.match(/오류\\s*신고\\s*내역\\s*(\\d+)\\s*건/) || [])[1];
              return {
                ok: ok != null ? parseInt(ok, 10) : null,
                err: err != null ? parseInt(err, 10) : null,
                url: location.href || '',
              };
            }"""
        )
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    try:
        url = page.url or ""
    except Exception:
        url = ""
    return {"ok": None, "err": None, "url": url}


async def _wait_convert_summary(
    page,
    *,
    logger: Callable[[str], None] | None = None,
    timeout_s: float = 15.0,
) -> dict:
    """M32 도착 직후 표 렌더 대기 — 정상/오류 숫자가 잡힐 때까지 폴링.

    화면 전환 직후 body 에 아직 '정상 신고 내역 N건' 이 없으면 ok=None/0 이
    나와 제출 게이트가 오거부할 수 있다.
    """
    _log = logger or log
    deadline = time.monotonic() + timeout_s
    last: dict = {"ok": None, "err": None, "url": ""}
    while time.monotonic() < deadline:
        try:
            last = await get_convert_result_summary(page)
        except Exception:
            last = {"ok": None, "err": None, "url": ""}
        ok_n = last.get("ok")
        err_n = last.get("err")
        # 정상 건수 확정(≥0 파싱됨) 이거나 오류 섹션이 보이면 종료
        if ok_n is not None and int(ok_n) >= 1:
            return last
        if err_n is not None:
            return last
        # ok==0 이 확정적으로 파싱됐고 잠깐 더 기다려도 동일하면 유지
        if ok_n is not None and int(ok_n) == 0:
            await asyncio.sleep(0.8)
            try:
                again = await get_convert_result_summary(page)
            except Exception:
                again = last
            if again.get("ok") is not None:
                return again
        await asyncio.sleep(0.4)
    _log(
        f"  [WETAX form] 서식검증 요약 폴링 타임아웃 "
        f"정상={last.get('ok')} 오류={last.get('err')}"
    )
    return last


async def _submit_success_signal(page) -> dict | None:
    """제출 후 성공 시그널 — **strict**: M33 제출결과 화면만 인정.

    라이브(2026-07-25) 확정:
      - URL `B070101M33.do` / path 에 M33
      - (보조) 동일 결과 화면 본문 「일괄신고」+「제출처리」

    제거된 느슨한 휴리스틱 (오탐 방지):
      left_m32, m31+filePw, 광범위 키워드, step3 class 추정
    """
    try:
        data = await page.evaluate(
            """() => {
              const url = location.href || '';
              const t = ((document.body && document.body.innerText) || '')
                .replace(/\\s+/g, ' ').trim();
              const batchMsg = t.includes('일괄신고') && t.includes('제출처리');
              return { url, batchMsg, bodyHead: t.slice(0, 160) };
            }"""
        )
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    url = data.get("url") or ""
    # 1순위: M33 URL (라이브 확정)
    if ACCOUNTING_SUBMIT_RESULT_PATH in url or "/B070101M33" in url or "M33.do" in url:
        return {
            "reason": "m33_url",
            "url": url,
            "hit": "batch" if data.get("batchMsg") else None,
        }
    # 2순위: 결과 본문 패턴이 있고 업로드/서식검증 URL 이 아닐 때만
    # (경로 변형 대비 — M31/M32 에서는 인정하지 않음)
    if data.get("batchMsg"):
        if ACCOUNTING_FILE_REPORT_PATH in url or ACCOUNTING_CONVERT_RESULT_PATH in url:
            return None
        if "wetax.go.kr" in url:
            return {
                "reason": "batch_result_body",
                "url": url,
                "hit": "일괄신고 제출처리",
            }
    return None


async def click_submit_report(
    page,
    *,
    logger: Callable[[str], None] | None = None,
    timeout_s: float = 90.0,
    result_out: dict | None = None,
    require_ok: bool = True,
) -> bool:
    """M32 제출하기 클릭 — `#btn_next` + 제출 라벨.

    라이브 전제 (2026-07-25 드류):
      - M32 하단 파란 버튼 라벨 「제출하기」(id 는 변환과 동일 btn_next)
      - confirm/alert 가능 → accept_native_dialogs 로 임시 수락 후 **복원**
      - 정상 신고 ≥1 · 오류 0(또는 오류 섹션 없음) 일 때만 진행 (require_ok)

    Args:
        require_ok: True 면 정상 0건/오류>0 이면 클릭 거부
        result_out: 성공 시 메타 기록
    """
    _log = logger or log
    sel = f"#{BTN_SUBMIT}"

    # 게이트: 서식검증 요약 (표 렌더 폴링 포함)
    try:
        summary = await _wait_convert_summary(page, logger=_log, timeout_s=15.0)
    except Exception:
        summary = {"ok": None, "err": None, "url": ""}
    ok_n = summary.get("ok")
    err_n = summary.get("err")
    _log(
        f"  [WETAX form] 제출 전 요약 정상={ok_n} 오류={err_n} "
        f"url={summary.get('url')}"
    )
    if require_ok:
        if err_n is not None and int(err_n) > 0:
            _log(
                f"  [WETAX form] 오류 {err_n}건 — 제출 거부 "
                f"(오류 파일 제출 자동화 금지)"
            )
            return False
        if ok_n is None or int(ok_n) < 1:
            _log(
                f"  [WETAX form] 정상 건수 없음(ok={ok_n}) — 제출 거부"
            )
            return False

    loc = page.locator(sel)
    try:
        await loc.first.wait_for(state="visible", timeout=15000)
    except Exception as e:
        _log(f"  [WETAX form] 제출하기({sel}) 미표시: {e}")
        return False

    # 라벨·URL 가드 hard-fail: M32 + 제출 라벨 필수
    try:
        url = page.url or ""
        label = (await loc.first.inner_text() or "").replace("\n", " ").strip()
        on_m32 = ACCOUNTING_CONVERT_RESULT_PATH in url
        looks_submit = (
            LABEL_SUBMIT in label
            or ("제출" in label and "변환" not in label and LABEL_CONVERT not in label)
        )
        looks_convert = LABEL_CONVERT in label or "변환" in label
        if looks_convert and not looks_submit:
            _log(
                f"  [WETAX form] 변환 버튼으로 보임 — 제출 거부 "
                f"(url={url!r} label={label!r})"
            )
            return False
        if not looks_submit:
            _log(
                f"  [WETAX form] 제출 라벨 아님 — 제출 거부 "
                f"(url={url!r} label={label!r})"
            )
            return False
        if not on_m32:
            _log(
                f"  [WETAX form] M32 아님 — 제출 거부 (url={url!r})"
            )
            return False
    except Exception as e:
        _log(f"  [WETAX form] 제출 라벨 확인 실패 — 중단: {e}")
        return False

    try:
        await loc.first.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass

    _log("  [WETAX form] [step] 제출하기 클릭")
    clicked = False
    # 라이브 confirm: "제출 하시겠습니까?" — 그 외 confirm 은 거부(오제출 방지)
    async with accept_native_dialogs(
        page,
        accept=True,
        message_substr="제출",
        on_mismatch="reject",
        logger=_log,
    ):
        try:
            await loc.first.click(timeout=8000, force=True)
            clicked = True
        except Exception as e:
            _log(f"  [WETAX form] 제출 locator 클릭 실패, DOM 폴백: {e}")
            try:
                await page.evaluate(
                    """(id) => {
                      const b = document.getElementById(id);
                      if (!b) return false;
                      b.scrollIntoView({block: 'center'});
                      b.click();
                      return true;
                    }""",
                    BTN_SUBMIT,
                )
                clicked = True
            except Exception as e2:
                _log(f"  [WETAX form] 제출하기 클릭 실패: {e2}")
                return False

        try:
            msgs = await page.evaluate("() => window.__wetax_confirm_msgs || []")
            if msgs:
                _log(f"  [WETAX form] [step] submit confirm: {msgs[0][:100]}")
                if result_out is not None:
                    result_out.setdefault("confirm_msgs", list(msgs))
        except Exception:
            pass

    if not clicked:
        return False

    # 성공 시그널 대기 (네비게이션으로 dialog 복원 실패는 정상) — M33 strict
    deadline = time.monotonic() + timeout_s
    last_url = ""
    while time.monotonic() < deadline:
        try:
            last_url = page.url or ""
            sig = await _submit_success_signal(page)
            if sig:
                _log(
                    f"  [WETAX form] [step] 제출 성공 "
                    f"reason={sig.get('reason')} url={sig.get('url')}"
                )
                if result_out is not None:
                    result_out.clear()
                    result_out.update(
                        {
                            "ok": ok_n,
                            "err": err_n,
                            **sig,
                        }
                    )
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)

    _log(f"  [WETAX form] 제출 후 성공 시그널 타임아웃 url={last_url!r}")
    if result_out is not None:
        try:
            snip = await page.evaluate(
                """() => ((document.body && document.body.innerText) || '')
                  .replace(/\\s+/g, ' ').trim().slice(0, 300)"""
            )
        except Exception:
            snip = ""
        result_out.clear()
        result_out.update(
            {
                "ok": ok_n,
                "err": err_n,
                "url": last_url,
                "timeout": True,
                "body_snip": snip,
            }
        )
    return False

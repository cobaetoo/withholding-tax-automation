"""위택스 회계파일신고 폼 입력 — 휴대전화·파일·비밀번호 등."""

from __future__ import annotations

import asyncio
from typing import Callable

from src.automation.wetax._common import log
from src.automation.wetax._constants import FIELD_MOBILE, FIELD_FILE_PW


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
            _log(f"  [WETAX form] 휴대전화 불일치 expect={phone!r} got={actual!r}")
            return False
        _log(f"  [WETAX form] 휴대전화 입력 완료: {actual}")
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

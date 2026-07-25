"""위택스 네이티브 confirm/alert 임시 오버라이드 (항상 복원)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Literal

from src.automation.wetax._common import log

OnMismatch = Literal["orig", "reject", "accept"]


@asynccontextmanager
async def accept_native_dialogs(
    page,
    *,
    accept: bool = True,
    message_substr: str | None = None,
    on_mismatch: OnMismatch = "orig",
    logger: Callable[[str], None] | None = None,
) -> AsyncIterator[None]:
    """window.confirm / alert 을 잠시 가로채고, 블록 종료 시 반드시 복원한다.

    CDP + Playwright 에서 네이티브 dialog accept 레이스가 잦아
    DOM click 전에 confirm 을 선제 수락할 때 사용한다.
    복원하지 않으면 이후 확인창이 전부 자동 수락되어 오제출 위험이 있다.

    Args:
        accept: confirm 반환값 (True=확인, False=취소) — substr 일치 시
        message_substr: 지정 시 해당 부분문자열이 있을 때만 accept 적용.
            None 이면 모든 confirm 에 accept 적용.
        on_mismatch: substr 불일치 시 동작
            - orig: 원본 confirm 위임 (블로킹 가능 — 기본, 하위호환)
            - reject: False(취소) 반환 — 제출 경로 권장
            - accept: True 반환
    """
    _log = logger or log
    mismatch = on_mismatch if on_mismatch in ("orig", "reject", "accept") else "orig"
    try:
        await page.evaluate(
            """({ accept, substr, mismatch }) => {
              if (!window.__wetax_dialog_orig) {
                window.__wetax_dialog_orig = {
                  confirm: window.confirm,
                  alert: window.alert,
                };
              }
              window.__wetax_confirm_msgs = [];
              const origConfirm = window.__wetax_dialog_orig.confirm;
              window.confirm = (msg) => {
                const s = String(msg || '');
                window.__wetax_confirm_msgs.push(s);
                if (substr && s.indexOf(substr) < 0) {
                  if (mismatch === 'reject') return false;
                  if (mismatch === 'accept') return true;
                  return origConfirm(msg);
                }
                return !!accept;
              };
              window.alert = (msg) => {
                window.__wetax_confirm_msgs.push('ALERT:' + String(msg || ''));
              };
              window.__wetax_dialog_orig._active = true;
            }""",
            {
                "accept": accept,
                "substr": message_substr or "",
                "mismatch": mismatch,
            },
        )
    except Exception as e:
        _log(f"  [WETAX dlg] confirm 오버라이드 실패: {e}")
        yield
        return

    try:
        yield
    finally:
        try:
            await page.evaluate(
                """() => {
                  const o = window.__wetax_dialog_orig;
                  if (o) {
                    if (typeof o.confirm === 'function') window.confirm = o.confirm;
                    if (typeof o.alert === 'function') window.alert = o.alert;
                    o._active = false;
                  }
                }"""
            )
        except Exception as e:
            _log(f"  [WETAX dlg] confirm 복원 실패: {e}")


async def pop_confirm_messages(page) -> list[str]:
    """오버라이드 중 수집한 confirm/alert 메시지 반환 후 비움."""
    try:
        return await page.evaluate(
            """() => {
              const m = window.__wetax_confirm_msgs || [];
              window.__wetax_confirm_msgs = [];
              return m;
            }"""
        )
    except Exception:
        return []


async def is_dialog_override_active(page) -> bool:
    """테스트/진단용 — 오버라이드가 아직 활성인지."""
    try:
        return bool(
            await page.evaluate(
                """() => !!(window.__wetax_dialog_orig && window.__wetax_dialog_orig._active)"""
            )
        )
    except Exception:
        return False

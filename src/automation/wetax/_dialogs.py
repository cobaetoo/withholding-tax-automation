"""위택스 네이티브 confirm/alert 임시 오버라이드 (항상 복원)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

from src.automation.wetax._common import log


@asynccontextmanager
async def accept_native_dialogs(
    page,
    *,
    accept: bool = True,
    message_substr: str | None = None,
    logger: Callable[[str], None] | None = None,
) -> AsyncIterator[None]:
    """window.confirm / alert 을 잠시 가로채고, 블록 종료 시 반드시 복원한다.

    CDP + Playwright 에서 네이티브 dialog accept 레이스가 잦아
    DOM click 전에 confirm 을 선제 수락할 때 사용한다.
    복원하지 않으면 이후 확인창이 전부 자동 수락되어 오제출 위험이 있다.

    Args:
        accept: confirm 반환값 (True=확인, False=취소)
        message_substr: 지정 시 해당 부분문자열이 있을 때만 accept 값 반환,
            없으면 반대값(취소 쪽) 반환. None 이면 항상 accept.
    """
    _log = logger or log
    # 원본 함수 참조를 페이지에 백업 후 오버라이드
    try:
        await page.evaluate(
            """({ accept, substr }) => {
              if (!window.__wetax_dialog_orig) {
                window.__wetax_dialog_orig = {
                  confirm: window.confirm,
                  alert: window.alert,
                };
              }
              window.__wetax_confirm_msgs = [];
              const origConfirm = window.__wetax_dialog_orig.confirm;
              const origAlert = window.__wetax_dialog_orig.alert;
              window.confirm = (msg) => {
                const s = String(msg || '');
                window.__wetax_confirm_msgs.push(s);
                // message_substr 가 있고 불일치면 원본 confirm 에 위임
                if (substr && s.indexOf(substr) < 0) {
                  return origConfirm(msg);
                }
                return !!accept;
              };
              window.alert = (msg) => {
                window.__wetax_confirm_msgs.push('ALERT:' + String(msg || ''));
              };
              // keep refs for restore
              window.__wetax_dialog_orig._active = true;
            }""",
            {"accept": accept, "substr": message_substr or ""},
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

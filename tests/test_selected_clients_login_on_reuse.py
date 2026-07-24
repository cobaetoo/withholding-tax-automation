"""선택건 실행: 재사용 세션에서도 로그인 실패 시 즉시 중단하는지 보강.

기본 회귀(재사용 시 _wait_for_login 호출)는
`test_selected_run_login_always.py` 를 본다.
여기는 로그인 실패 early-return 경로를 고정한다.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock


def test_selected_run_login_failure_when_reused_skips_workflow():
    """reused=True + 로그인 실패 → reconnect/workflow 미호출, failed emit."""
    from src.ui.workers.automation_runner import AutomationRunner

    runner = AutomationRunner.__new__(AutomationRunner)
    runner._stop_event = MagicMock()
    runner._stop_event.is_set.return_value = False
    runner._page = MagicMock()
    runner._context = MagicMock()
    runner.log_message = MagicMock()
    runner.phase_changed = MagicMock()
    runner.error_occurred = MagicMock()
    runner.batch_progress = MagicMock()

    runner._try_reuse_browser = AsyncMock(return_value=True)
    runner._ensure_browser = AsyncMock(return_value=True)
    runner._wait_for_login = AsyncMock(return_value=False)
    runner._reconnect_page = AsyncMock()

    cmd = {
        "type": "run_selected_clients",
        "phase_id": 13,
        "client_infos": [
            {"name": "테스트", "management_number": "", "business_number": ""},
        ],
        "year": 2026,
        "month": 7,
    }

    # wetax phase 13 등록 (import side-effect)
    import src.workflows.wetax_local_tax  # noqa: F401

    asyncio.run(runner._handle_run_selected_clients(cmd))

    runner._try_reuse_browser.assert_awaited_once_with("wetax")
    runner._ensure_browser.assert_not_awaited()
    runner._wait_for_login.assert_awaited_once_with("wetax")
    runner._reconnect_page.assert_not_awaited()
    runner.phase_changed.emit.assert_any_call(13, "failed")
    runner.error_occurred.emit.assert_called_once_with("로그인 실패 또는 시간 초과")

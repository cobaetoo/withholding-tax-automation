"""선택건 실행: 브라우저 재사용 시에도 _wait_for_login 이 항상 호출되는지."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import src.workflows.wetax_local_tax  # noqa: F401


def test_selected_run_calls_wait_for_login_when_reused():
    """reused=True 여도 로그인 대기를 건너뛰지 않는다 (전체실행과 정렬)."""
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
    runner._wait_for_login = AsyncMock(return_value=True)
    runner._reconnect_page = AsyncMock()
    runner._is_page_alive = AsyncMock(return_value=True)

    # 워크플로가 돌면 미구현 단계에서 False — 로그인 호출 여부만 검증
    mock_wf = MagicMock()
    mock_wf.run_single = AsyncMock(return_value=False)

    cmd = {
        "type": "run_selected_clients",
        "phase_id": 13,
        "client_infos": [
            {"name": "테스트", "management_number": "", "business_number": ""},
        ],
        "year": 2026,
        "month": 7,
        "password": "pw",
        "phone": "010-1234-5678",
        "dry_run": True,
    }

    with patch(
        "src.workflows.registry.get_workflow", return_value=mock_wf
    ), patch(
        "src.utils.human.human_break", new_callable=AsyncMock, return_value=0
    ):
        asyncio.run(runner._handle_run_selected_clients(cmd))

    runner._try_reuse_browser.assert_awaited_once_with("wetax")
    runner._ensure_browser.assert_not_awaited()  # 재사용이므로 ensure 불필요
    runner._wait_for_login.assert_awaited_once_with("wetax")
    runner._reconnect_page.assert_awaited_once_with("wetax")


def test_selected_run_wait_for_login_after_ensure_when_not_reused():
    """재사용 실패 시 ensure 후 로그인 대기."""
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

    runner._try_reuse_browser = AsyncMock(return_value=False)
    runner._ensure_browser = AsyncMock(return_value=True)
    runner._wait_for_login = AsyncMock(return_value=True)
    runner._reconnect_page = AsyncMock()
    runner._is_page_alive = AsyncMock(return_value=True)

    mock_wf = MagicMock()
    mock_wf.run_single = AsyncMock(return_value=False)

    cmd = {
        "type": "run_selected_clients",
        "phase_id": 13,
        "client_infos": [{"name": "테스트", "management_number": "", "business_number": ""}],
        "year": 2026,
        "month": 7,
        "password": "pw",
        "phone": "010-1234-5678",
    }

    with patch(
        "src.workflows.registry.get_workflow", return_value=mock_wf
    ), patch(
        "src.utils.human.human_break", new_callable=AsyncMock, return_value=0
    ):
        asyncio.run(runner._handle_run_selected_clients(cmd))

    runner._ensure_browser.assert_awaited_once_with("wetax")
    runner._wait_for_login.assert_awaited_once_with("wetax")

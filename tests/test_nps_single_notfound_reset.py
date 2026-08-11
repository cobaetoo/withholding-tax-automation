"""단독 국민연금 EDI의 사업장 미발견 뒤 페이지 리셋 회귀 테스트."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.automation.nps import _common as nps_common
from src.workflows.nps_edi import NpsEdiWorkflow


class _State:
    """워크플로우의 사업장 전환 단계만 검증하는 최소 상태 관리자."""

    def __init__(self):
        self.failed: list[tuple[int, str, str]] = []

    def should_skip_step(self, _job_id, _step_name):
        return False

    def before_step(self, *_args, **_kwargs):
        pass

    def after_step(self, *_args, **_kwargs):
        pass

    def fail_step(self, job_id, step_name, message):
        self.failed.append((job_id, step_name, message))


def _run_not_found(reset_workplace_page):
    """사업장 전환 실패 상태에서 단독 워크플로우를 실행한다."""
    page = MagicMock(name="nps_page")
    state = _State()
    workflow = NpsEdiWorkflow()
    with patch.object(nps_common, "switch_workplace", new=AsyncMock(return_value=False)), patch.object(
        nps_common, "reset_workplace_page", new=reset_workplace_page
    ):
        result = asyncio.run(
            workflow.run_single(
                page, MagicMock(), "미발견 수임처", job_id=17,
                state=state, management_number="99999999999",
            )
        )
    return result, page, state


def test_single_nps_not_found_resets_page_before_returning_failure():
    """미발견 건은 실패 처리하되 NPS 모달/alert을 리셋해 다음 건을 준비한다."""
    reset = AsyncMock()

    result, page, state = _run_not_found(reset)

    assert result is False
    assert state.failed == [(17, "switch_workplace", "'미발견 수임처' 전환 실패")]
    reset.assert_awaited_once_with(page)


def test_single_nps_not_found_keeps_failure_when_reset_fails():
    """리셋 실패는 미발견 결과를 예외로 바꾸거나 배치 진행을 막지 않는다."""
    reset = AsyncMock(side_effect=RuntimeError("temporary reload failure"))

    result, _page, state = _run_not_found(reset)

    assert result is False
    assert state.failed == [(17, "switch_workplace", "'미발견 수임처' 전환 실패")]
    assert reset.await_count == 1


def test_selected_runner_continues_to_next_client_after_workflow_failure():
    """선택건 실행은 첫 수임처 실패 뒤에도 다음 수임처 워크플로우를 호출한다."""
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

    workflow = MagicMock()
    workflow.run_single = AsyncMock(side_effect=[False, True])
    cmd = {
        "type": "run_selected_clients",
        "phase_id": 4,
        "client_infos": [
            {"name": "미발견 수임처", "management_number": "99999999999"},
            {"name": "정상 수임처", "management_number": "11111111111"},
        ],
        "year": 2026,
        "month": 8,
    }

    phase = {"portal": "nps_edi", "display_name": "국민연금 EDI"}
    with patch("src.workflows.registry.get_phase_info", return_value=phase), patch(
        "src.workflows.registry.get_workflow", return_value=workflow
    ):
        asyncio.run(runner._handle_run_selected_clients(cmd))

    assert workflow.run_single.await_count == 2
    assert [call.args[2] for call in workflow.run_single.await_args_list] == [
        "미발견 수임처", "정상 수임처",
    ]
    runner.phase_changed.emit.assert_any_call(4, "completed")

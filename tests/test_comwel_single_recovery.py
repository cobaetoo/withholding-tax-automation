"""단독 고용보험 EDI의 사업장조회 팝업 미오픈 복구 회귀 테스트."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.automation.comwel import _common as comwel_common
from src.automation.comwel import _download as comwel_download
from src.utils import human
from src.workflows.comwel_edi import ComwelEdiWorkflow


class _State:
    """워크플로우 제어 흐름을 검증하는 최소 상태 관리자."""

    def __init__(self):
        self.before: list[tuple[int, str, int]] = []
        self.after: list[tuple[int, str]] = []
        self.failed: list[tuple[int, str, str]] = []

    def should_skip_step(self, _job_id, _step_name):
        return False

    def before_step(self, job_id, step_name, step_index=0, **_kwargs):
        self.before.append((job_id, step_name, step_index))

    def after_step(self, job_id, step_name, **_kwargs):
        self.after.append((job_id, step_name))

    def fail_step(self, job_id, step_name, message):
        self.failed.append((job_id, step_name, message))


async def _no_delay(*_args, **_kwargs):
    return None


def _run_workflow(*, switch_results, reset_result=True, navigate_results=None):
    """전환 결과를 주입해 단독 COMWEL 워크플로우를 실행한다."""
    page = MagicMock(name="comwel_page")
    context = MagicMock(name="comwel_context")
    state = _State()
    workflow = ComwelEdiWorkflow()

    navigate = (
        AsyncMock(side_effect=navigate_results)
        if navigate_results is not None
        else AsyncMock(return_value=True)
    )
    set_period = AsyncMock(return_value=True)
    switch = AsyncMock(side_effect=switch_results)
    reset = AsyncMock(return_value=reset_result)
    search = AsyncMock(return_value=True)
    dismiss = AsyncMock()
    download = AsyncMock(return_value={"path": "saved.pdf", "skipped": False})

    with patch.object(comwel_common, "navigate_to_premium_20209", new=navigate), patch.object(
        comwel_common, "set_period", new=set_period
    ), patch.object(comwel_common, "switch_workplace", new=switch), patch.object(
        comwel_common, "reset_workplace_page", new=reset
    ), patch.object(comwel_common, "search_main", new=search), patch.object(
        comwel_common, "dismiss_dialogs", new=dismiss
    ), patch.object(comwel_download, "download_support_info_printout", new=download), patch.object(
        human, "human_delay", new=_no_delay
    ), patch("src.utils.log.log"):
        result = asyncio.run(
            workflow.run_single(
                page, context, "테스트 수임처", job_id=31, state=state,
                management_number="27885011950", year=2026, month=8,
            )
        )

    return {
        "result": result,
        "page": page,
        "state": state,
        "navigate": navigate,
        "set_period": set_period,
        "switch": switch,
        "reset": reset,
        "search": search,
        "dismiss": dismiss,
        "download": download,
    }


def test_single_comwel_retries_once_after_workplace_popup_failure():
    """첫 팝업 미오픈은 메인→20209 복구 뒤 같은 사업장을 한 번 재시도한다."""
    result = _run_workflow(switch_results=[False, True])

    assert result["result"] is True
    assert result["switch"].await_count == 2
    assert result["reset"].await_count == 1
    # 최초 진입 + 복구 후 재진입, 최초 연월 설정 + 복구 후 재설정.
    assert result["navigate"].await_count == 2
    assert result["set_period"].await_count == 2
    assert result["state"].failed == []
    assert (31, "switch_workplace") in result["state"].after
    result["search"].assert_awaited_once_with(result["page"])
    result["download"].assert_awaited_once()


def test_single_comwel_resets_after_final_workplace_failure():
    """재시도도 실패하면 실패를 기록하되 다음 선택건을 위해 다시 리셋한다."""
    result = _run_workflow(switch_results=[False, False])

    assert result["result"] is False
    assert result["switch"].await_count == 2
    # 복구 전 1회 + 최종 실패 후 다음 선택건 준비 1회.
    assert result["reset"].await_count == 2
    assert result["state"].failed == [
        (31, "switch_workplace", "'테스트 수임처' 전환 실패"),
    ]
    result["search"].assert_not_awaited()
    result["download"].assert_not_awaited()


def test_single_comwel_contains_recovery_navigation_error():
    """복구 중 재진입 오류도 원래 전환 실패로 처리하고 다음 실행을 준비한다."""
    result = _run_workflow(
        switch_results=[False],
        navigate_results=[True, RuntimeError("temporary navigation failure")],
    )

    assert result["result"] is False
    result["switch"].assert_awaited_once()
    assert result["reset"].await_count == 2
    assert result["state"].failed == [
        (31, "switch_workplace", "'테스트 수임처' 전환 실패"),
    ]


def test_single_comwel_success_does_not_reset_or_retry():
    """정상 사업장 전환 경로에는 복구 동작을 추가하지 않는다."""
    result = _run_workflow(switch_results=[True])

    assert result["result"] is True
    result["switch"].assert_awaited_once()
    result["reset"].assert_not_awaited()
    result["navigate"].assert_awaited_once()
    result["set_period"].assert_awaited_once()
    assert result["state"].failed == []

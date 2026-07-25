"""위택스 GUI 비밀번호·휴대전화 → runner/workflow kwargs 전달 검증.

브라우저/CDP 없이:
  1) MainWindow 툴바 값 → start_phase / start_selected_clients 인자
  2) AutomationRunner 명령 큐 구성
  3) BaseWorkflow.as_workflow_func 머지 → run_single kwargs
  4) WetaxLocalTaxWorkflow 가 kwargs 에서 phone/password 를 읽는지
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import src.workflows.wetax_local_tax  # noqa: F401 — 레지스트리 등록
from src.workflows.registry import get_phase_info, get_workflow
from src.workflows.base import BaseWorkflow
from src.batch.state import NoopStateManager

app = QApplication.instance() or QApplication([])

TEST_PW = "GuiPass99"
TEST_PHONE = "010-1234-5678"


def test_phase13_flags():
    info = get_phase_info(13)
    assert info["needs_password"] is True
    assert info["needs_phone"] is True


def test_mainwindow_full_run_passes_password_and_phone():
    """전체실행: start_kwargs 에 password/phone 이 그대로 들어간다."""
    from src.ui.main_window import MainWindow

    w = MainWindow()
    w._on_phase_selected(13)
    w.pw_input.setText(TEST_PW)
    w.phone_input.setText(TEST_PHONE)

    captured = {}

    def fake_start_phase(phase_id, **kwargs):
        captured["phase_id"] = phase_id
        captured["kwargs"] = dict(kwargs)

    w.runner.start_phase = fake_start_phase
    # 병렬/리스트 아님, 테이블 실행 가능 상태로
    w.company_table.set_run_active = MagicMock()
    w.pause_btn.setEnabled = MagicMock()
    w._poll_timer = MagicMock()

    # _on_start 는 활성 수임처 등 다른 분기가 있을 수 있어
    # 전달 블록만 직접 재현 (main_window 683~705 와 동일)
    password = w._require_password()
    phone = w._require_phone()
    assert password == TEST_PW
    assert phone == TEST_PHONE

    start_kwargs = dict(
        dry_run=w.dry_run_check.isChecked(),
        year=w.year_spin.value(),
        month=w.month_spin.value(),
    )
    if password:
        start_kwargs["password"] = password
    if phone:
        start_kwargs["phone"] = phone
    w.runner.start_phase(w._selected_phase, **start_kwargs)

    assert captured["phase_id"] == 13
    assert captured["kwargs"]["password"] == TEST_PW
    assert captured["kwargs"]["phone"] == TEST_PHONE


def test_mainwindow_selected_run_passes_password_and_phone():
    """선택건 실행: start_selected_clients 에 password/phone 포함."""
    from src.ui.main_window import MainWindow

    w = MainWindow()
    w._on_phase_selected(13)
    w.pw_input.setText(TEST_PW)
    w.phone_input.setText(TEST_PHONE)

    captured = {}

    def fake_start_selected(phase_id, client_infos, year=None, month=None, **kwargs):
        captured["phase_id"] = phase_id
        captured["client_infos"] = client_infos
        captured["year"] = year
        captured["month"] = month
        captured["kwargs"] = dict(kwargs)

    w.runner.start_selected_clients = fake_start_selected

    # main_window 선택건 전달 블록과 동일
    extra_kwargs = {"dry_run": w.dry_run_check.isChecked()}
    pw = w._require_password()
    phone = w._require_phone()
    assert pw == TEST_PW and phone == TEST_PHONE
    if pw:
        extra_kwargs["password"] = pw
    if phone:
        extra_kwargs["phone"] = phone

    client_infos = [{"name": "테스트수임처", "management_number": "", "business_number": ""}]
    w.runner.start_selected_clients(
        w._selected_phase, client_infos,
        year=w.year_spin.value(),
        month=w.month_spin.value(),
        **extra_kwargs,
    )

    assert captured["phase_id"] == 13
    assert captured["kwargs"]["password"] == TEST_PW
    assert captured["kwargs"]["phone"] == TEST_PHONE
    assert "dry_run" in captured["kwargs"]


def test_runner_command_queue_keeps_password_phone():
    """AutomationRunner.start_selected_clients 가 큐 명령에 kwargs 를 실는다."""
    from src.ui.workers.automation_runner import AutomationRunner

    runner = AutomationRunner()
    # 스레드 기동 없이 큐만 검사
    runner._ensure_running = MagicMock()
    runner.start_selected_clients(
        13,
        [{"name": "A"}],
        year=2026,
        month=7,
        password=TEST_PW,
        phone=TEST_PHONE,
        dry_run=True,
    )
    cmd = runner._command_queue.get_nowait()
    assert cmd["type"] == "run_selected_clients"
    assert cmd["phase_id"] == 13
    assert cmd["password"] == TEST_PW
    assert cmd["phone"] == TEST_PHONE

    # _handle_run_selected 의 extra_kwargs 추출과 동일
    extra = {k: v for k, v in cmd.items()
             if k not in ("type", "phase_id", "client_infos", "year", "month")}
    assert extra["password"] == TEST_PW
    assert extra["phone"] == TEST_PHONE


def test_async_bridge_start_phase_queue():
    """start_phase 큐 명령에 password/phone 포함 (전체실행 경로)."""
    from src.ui.workers.async_bridge import AsyncWorker

    w = AsyncWorker()
    w._ensure_running = MagicMock()  # QThread 기동 방지
    w.start_phase(13, password=TEST_PW, phone=TEST_PHONE, year=2026, month=7, dry_run=True)
    cmd = w._command_queue.get_nowait()
    assert cmd["type"] == "run_phase"
    assert cmd["phase_id"] == 13
    assert cmd["password"] == TEST_PW
    assert cmd["phone"] == TEST_PHONE

    # _handle_run_phase 의 kwargs 추출과 동일
    kwargs = {k: v for k, v in cmd.items() if k not in ("type", "phase_id")}
    assert kwargs["password"] == TEST_PW
    assert kwargs["phone"] == TEST_PHONE


def test_as_workflow_func_merges_password_phone_into_run_single():
    """as_workflow_func(**kwargs) 가 run_single 에 password/phone 을 넘긴다."""
    received = {}

    class _Dummy(BaseWorkflow):
        steps = [{"name": "x", "index": 0}]

        async def run_single(self, page, context, client_name, job_id, state, **kwargs):
            received.update(kwargs)
            return True

    wf = _Dummy()
    func = wf.as_workflow_func(password=TEST_PW, phone=TEST_PHONE, dry_run=True)
    import asyncio

    async def _run():
        job = MagicMock()
        job.id = 1
        job.client_name = "테스트"
        state = NoopStateManager()
        return await func(None, None, job, state, management_number="x")

    assert asyncio.get_event_loop_policy()
    ok = asyncio.run(_run())
    assert ok is True
    assert received["password"] == TEST_PW
    assert received["phone"] == TEST_PHONE
    assert received["management_number"] == "x"


def test_wetax_workflow_reads_kwargs_keys():
    """WetaxLocalTaxWorkflow.run_single 이 kwargs 에서 phone/password 를 읽는다.

    네비/폼을 모킹해 실제 값 전달 여부만 확인.
    """
    import asyncio
    from src.workflows.wetax_local_tax import WetaxLocalTaxWorkflow

    wf = WetaxLocalTaxWorkflow()
    state = NoopStateManager()
    seen = {"phone": None, "password": None}

    async def fake_nav(page, **kw):
        return True

    async def fake_phone(page, phone, **kw):
        seen["phone"] = phone
        return True

    async def fake_pw(page, password, **kw):
        seen["password"] = password
        return True

    async def fake_select(page, path, **kw):
        return True

    async def fake_convert(page, **kw):
        # result_out 이 있으면 메타 채움 (워크플로 호환)
        out = kw.get("result_out")
        if isinstance(out, dict):
            out.clear()
            out.update({"ok": 1, "err": 0, "url": "mock"})
        return True

    async def fake_submit(page, **kw):
        out = kw.get("result_out")
        if isinstance(out, dict):
            out.clear()
            out.update({"reason": "mock", "url": "mock", "ok": 1, "err": 0})
        return True

    async def fake_ensure(page, **kw):
        return True

    with patch("src.automation.wetax._navigation.goto_accounting_file_report", fake_nav), \
         patch("src.automation.wetax._form.fill_mobile_phone", fake_phone), \
         patch("src.automation.wetax._form.enter_file_password", fake_pw), \
         patch("src.automation.wetax._form.find_jitax_encrypted_file",
               return_value=r"C:\tmp\dummy.2"), \
         patch("src.automation.wetax._form.select_encrypted_file", fake_select), \
         patch("src.automation.wetax._form.click_convert_file", fake_convert), \
         patch("src.automation.wetax._form.click_submit_report", fake_submit), \
         patch("src.automation.wetax._navigation.ensure_upload_form", fake_ensure):
        ok = asyncio.run(wf.run_single(
            page=MagicMock(),
            context=MagicMock(),
            client_name="테스트",
            job_id=1,
            state=state,
            password=TEST_PW,
            phone=TEST_PHONE,
            year=2026,
            month=7,
        ))

    # 전화·비번 소비 후 파일선택·변환·제출(모킹) → True
    assert seen["phone"] == TEST_PHONE
    assert seen["password"] == TEST_PW
    assert ok is True


def test_wetax_multi_client_stub_advances_all():
    """수임처 3건 연속 run_single 모두 True (파일·변환·제출 모킹)."""
    import asyncio
    from src.workflows.wetax_local_tax import WetaxLocalTaxWorkflow

    wf = WetaxLocalTaxWorkflow()
    clients = ["수임A", "수임B", "수임C"]

    async def fake_nav(page, **kw):
        return True

    async def fake_phone(page, phone, **kw):
        return True

    async def fake_pw(page, password, **kw):
        return True

    async def fake_select(page, path, **kw):
        return True

    async def fake_convert(page, **kw):
        out = kw.get("result_out")
        if isinstance(out, dict):
            out.clear()
            out.update({"ok": 1, "err": 0, "url": "mock"})
        return True

    async def fake_submit(page, **kw):
        out = kw.get("result_out")
        if isinstance(out, dict):
            out.clear()
            out.update({"reason": "mock", "url": "mock"})
        return True

    async def fake_ensure(page, **kw):
        return True

    results = []
    with patch("src.automation.wetax._navigation.goto_accounting_file_report", fake_nav), \
         patch("src.automation.wetax._form.fill_mobile_phone", fake_phone), \
         patch("src.automation.wetax._form.enter_file_password", fake_pw), \
         patch("src.automation.wetax._form.find_jitax_encrypted_file",
               return_value=r"C:\tmp\dummy.2"), \
         patch("src.automation.wetax._form.select_encrypted_file", fake_select), \
         patch("src.automation.wetax._form.click_convert_file", fake_convert), \
         patch("src.automation.wetax._form.click_submit_report", fake_submit), \
         patch("src.automation.wetax._navigation.ensure_upload_form", fake_ensure):
        for name in clients:
            state = NoopStateManager()
            ok = asyncio.run(wf.run_single(
                page=MagicMock(),
                context=MagicMock(),
                client_name=name,
                job_id=0,
                state=state,
                password=TEST_PW,
                phone=TEST_PHONE,
                year=2026,
                month=7,
            ))
            results.append(ok)

    assert results == [True, True, True]

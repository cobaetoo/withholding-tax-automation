"""병렬 NHIS 배치의 상태 초기화·안전한 실패 처리 회귀 테스트."""
import asyncio

from src.automation.nhis import nhis_edi_auto_cdp as nhis


class _Page:
    async def bring_to_front(self):
        return None


async def _no_delay(*_args, **_kwargs):
    return None


def _wire_common(monkeypatch, page, events, *, switched=True, workflow_ok=True):
    """실제 포털 없이 한 수임처 배치에 필요한 비동기 의존성을 연결한다."""
    popup = object()

    async def close_popups(_context):
        events.append("close_popups")
        return page

    async def reset_main_page(received_page):
        events.append(("reset", received_page))

    async def open_firm_selector(received_page, _context):
        events.append(("open", received_page))
        return popup

    async def select_firm(_popup, name, management_number=""):
        events.append(("select", name, management_number))
        return True

    async def close_firm_popup(_context, _popup):
        events.append("close_popup")

    async def wait_firm_switched(_page, _name, timeout_s=0):
        events.append(("wait_switch", timeout_s))
        return (switched, "대상수임처" if switched else "기본사업장")

    async def workflow(received_page, _context, name, **_kwargs):
        events.append(("workflow", received_page, name))
        return workflow_ok

    monkeypatch.setattr(nhis, "close_popups", close_popups)
    monkeypatch.setattr(nhis, "reset_main_page", reset_main_page)
    monkeypatch.setattr(nhis, "open_firm_selector", open_firm_selector)
    monkeypatch.setattr(nhis, "select_firm", select_firm)
    monkeypatch.setattr(nhis, "close_firm_popup", close_firm_popup)
    monkeypatch.setattr(nhis, "_wait_firm_switched", wait_firm_switched)
    monkeypatch.setattr(nhis, "run_single_firm_workflow", workflow)
    monkeypatch.setattr(nhis, "human_delay", _no_delay)
    monkeypatch.setattr(nhis.asyncio, "sleep", _no_delay)
    monkeypatch.setattr(nhis, "_trace", lambda _msg: None)


def test_parallel_batch_resets_main_page_before_each_firm(monkeypatch):
    page = _Page()
    events, summaries = [], []
    _wire_common(monkeypatch, page, events)
    monkeypatch.setattr(
        nhis, "_emit_summary",
        lambda total, completed, skipped: summaries.append((total, completed, skipped)),
    )

    ok = asyncio.run(nhis.run_auto_batch(
        page, object(), firms=["대상수임처"], mgmts=["123"], year=2026, month=8,
    ))

    assert ok is True
    assert ("reset", page) in events
    assert ("workflow", page, "대상수임처") in events
    assert summaries == [(1, 1, [])]


def test_parallel_batch_stops_firm_when_switch_cannot_be_verified(monkeypatch):
    """기본 사업장 PDF를 받지 않도록 첫 전환 검증 불일치에서 즉시 차단한다."""
    page = _Page()
    events, summaries = [], []
    _wire_common(monkeypatch, page, events, switched=False)
    monkeypatch.setattr(
        nhis, "_emit_summary",
        lambda total, completed, skipped: summaries.append((total, completed, skipped)),
    )

    ok = asyncio.run(nhis.run_auto_batch(
        page, object(), firms=["대상수임처"], mgmts=["123"], year=2026, month=8,
    ))

    assert ok is False
    assert ("reset", page) in events
    assert ("wait_switch", 12) in events
    assert not any(event[0] == "workflow" for event in events if isinstance(event, tuple))
    assert summaries == [(
        1, 0,
        [{
            "name": "대상수임처",
            "reason": "전환실패",
            "detail": "페이지='기본사업장' / 기대='대상수임처'",
        }],
    )]


def test_parallel_batch_returns_false_when_pdf_workflow_fails(monkeypatch):
    page = _Page()
    events, summaries = [], []
    _wire_common(monkeypatch, page, events, workflow_ok=False)
    monkeypatch.setattr(
        nhis, "_emit_summary",
        lambda total, completed, skipped: summaries.append((total, completed, skipped)),
    )

    ok = asyncio.run(nhis.run_auto_batch(
        page, object(), firms=["대상수임처"], year=2026, month=8,
    ))

    assert ok is False
    assert summaries == [(
        1, 0,
        [{"name": "대상수임처", "reason": "오류", "detail": "워크플로우 실패"}],
    )]

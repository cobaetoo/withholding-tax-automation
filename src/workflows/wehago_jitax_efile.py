"""Phase 11: WEHAGO 지방소득세특별징수전자신고 어댑터 (원천전자신고 SWER0101 의 지방세 카운터파트)

플로우 (원천전자신고와 동일 골격):
  0. WEHAGO 메인 복귀
  1. 수임처 급여 페이지 진입 (사업자번호 우선 → 이름 fallback)
  2. 지방소득세 특별징수 전자신고 파일 제작 (run_jitax_efile)

★전제조건: 지방소득세특별징수납부서(SWTA0112)를 먼저 마감해야 전자신고 데이터가
  생성됨. 원천세의 '원천이행상황 마감 → 원천전자신고 제작' 과 동일한 순서 의존성.
구현·라이브 검증 완료(2026-07-21). needs_password=True (전자신고 파일 비밀번호 필요).
"""
from src.utils.human import human_delay
from src.utils.save_path import make_save_dir
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=11,
    portal="wehago",
    display_name="지방소득세특별징수전자신고",
    enabled=True,
    needs_password=True,   # 지방세 전자신고 파일 비밀번호 필요 (라이브 확인 2026-07-21)
)
class WehagoJitaxEfileWorkflow(BaseWorkflow):
    steps = [
        {"name": "navigate_to_wehago_main", "index": 0},
        {"name": "goto_salary_page",        "index": 1},
        {"name": "run_jitax_efile",         "index": 2},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.wehago._common import (
            ensure_wehago_main, goto_salary_page_with_fallback, log,
        )
        from src.automation.wehago.run_jitax_efile import run_jitax_efile

        password = kwargs.get("password", "")
        nts_folder = kwargs.get("nts_folder", "지방소득세전자신고")
        year = kwargs.get("year")
        month = kwargs.get("month")
        business_number = kwargs.get("business_number", "")
        save_dir = make_save_dir("지방소득세전자신고", client_name, year=year, month=month)

        if not password:
            log("  전자신고 비밀번호가 없습니다")
            return False

        # ── Step 0: WEHAGO 메인 복귀 ──────────────────────────────────
        if not state.should_skip_step(job_id, "navigate_to_wehago_main"):
            state.before_step(job_id, "navigate_to_wehago_main", 0)
            await ensure_wehago_main(page)
            state.after_step(job_id, "navigate_to_wehago_main")

        # ── Step 1: 수임처 급여 페이지 진입 ───────────────────────────
        if not state.should_skip_step(job_id, "goto_salary_page"):
            state.before_step(job_id, "goto_salary_page", 1)
            goto_ok = await goto_salary_page_with_fallback(
                page, client_name, management_number,
                business_number=business_number,
            )
            if not goto_ok:
                state.fail_step(job_id, "goto_salary_page", "급여 페이지 이동 실패")
                return False
            await human_delay(2)
            state.after_step(job_id, "goto_salary_page")

        # ── Step 2: 지방소득세 전자신고 파일 제작 ─────────────────────
        if not state.should_skip_step(job_id, "run_jitax_efile"):
            state.before_step(job_id, "run_jitax_efile", 2)
            try:
                await run_jitax_efile(
                    page, password, nts_folder,
                    year=year, month=month, save_dir=save_dir,
                )
                state.after_step(job_id, "run_jitax_efile")
            except Exception as e:
                state.fail_step(job_id, "run_jitax_efile", str(e))
                return False

        return True

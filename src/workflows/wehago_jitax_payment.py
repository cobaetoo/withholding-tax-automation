"""Phase 10: WEHAGO 지방소득세특별징수납부서 어댑터 (원천세 SWTA0101 의 지방세 카운터파트)

플로우 (원천이행상황신고서와 동일 골격):
  0. WEHAGO 메인 복귀
  1. 수임처 급여 페이지 진입 (사업자번호 우선 → 이름 fallback)
  2. 지방소득세 특별징수 납부서 처리 (run_jitax_payment)

★스캐폴드: run_jitax_payment 는 라이브 발견 전까지 네비게이션+기간설정까지만 수행하고
  액션은 NotImplementedError. 아래 반기 스킵/역충전 로직은 SWTA 미러이며 지방세 주기
  radio 유무는 LIVE-VERIFY.
"""
from datetime import datetime

from src.utils.human import human_delay
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=10,
    portal="wehago",
    display_name="지방소득세특별징수납부서",
    enabled=True,
)
class WehagoJitaxPaymentWorkflow(BaseWorkflow):
    steps = [
        {"name": "navigate_to_wehago_main", "index": 0},
        {"name": "goto_salary_page",        "index": 1},
        {"name": "run_jitax_payment",       "index": 2},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.wehago._common import (
            ensure_wehago_main, goto_salary_page_with_fallback, log,
        )
        from src.automation.wehago.run_jitax_payment import run_jitax_payment

        year = kwargs.get("year")
        month = kwargs.get("month")
        business_number = kwargs.get("business_number", "")
        report_cycle = kwargs.get("report_cycle", "")   # DB 신고주기 (매월/반기/빈)
        client_id = kwargs.get("client_id")              # 역충전(backfill)용

        # ── 반기 월 필터링(6·12월만) — SWTA 미러 ────────────────────────
        # LIVE-VERIFY: 지방소득세도 원천세와 동일한 매월/반기 신고주기인지 라이브 확인.
        if report_cycle == "반기":
            _target_m = month if month else datetime.now().month
            if _target_m not in (6, 12):
                log(f"  [JITAX_PAY] 반기 수임처 비신고월({_target_m}월) — 스킵 (반기는 6·12월만)")
                return True

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

        # ── Step 2: 지방소득세 납부서 처리 ────────────────────────────
        if not state.should_skip_step(job_id, "run_jitax_payment"):
            state.before_step(job_id, "run_jitax_payment", 2)
            try:
                used_cycle = await run_jitax_payment(
                    page, year=year, month=month,
                    report_cycle=report_cycle, client_id=client_id,
                )
                state.after_step(job_id, "run_jitax_payment")
                # 역충전: DB report_cycle 이 비어있었고 라디오(ground truth)에서 주기를
                # 얻었으면 DB 에 기록(1번 메뉴 DB 와 동일 clients 테이블). SWTA 미러.
                # LIVE-VERIFY: 지방세에 주기 radio 가 없으면 이 경로는 타지 않음.
                if (not report_cycle) and used_cycle in ("매월", "반기") and client_id:
                    self._backfill_report_cycle(client_id, used_cycle)
            except Exception as e:
                state.fail_step(job_id, "run_jitax_payment", str(e))
                return False

        return True

    @staticmethod
    def _backfill_report_cycle(client_id: int, cycle: str) -> None:
        """DB report_cycle 이 비어있을 때 위하고 라디오(ground truth) 값을 역충전.

        SWTA(wehago_swta.py) 와 동일 clients 테이블·동일 로직. 새로가져오기 시
        스크랩값으로 덮어씀.
        """
        from src.config import DB_PATH
        from src.batch.db import BatchDB, ClientRepository
        from src.automation.wehago._common import log
        try:
            with BatchDB(DB_PATH) as db:
                ClientRepository(db).update_report_cycle(client_id, cycle)
            log(f"  [JITAX_PAY] 신고주기 역충전 DB 기록: client_id={client_id} → {cycle}")
        except Exception as e:
            log(f"  [JITAX_PAY] 신고주기 역충전 실패: {e}")

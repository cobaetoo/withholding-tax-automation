"""Phase 13: 위택스 지방세 신고 어댑터 (특별징수세액 · 회계파일신고)

WEHAGO Phase 11(지방소득세특별징수전자신고) 전자신고파일을 위택스에 업로드.

워크플로우 (GUIDE.md / USER_GUIDE.md / src/automation/wetax/PROGRESS.md):
  1. 전자세금용 공인인증서 로그인 (Human-in-the-loop, runner 담당)
  2. 메뉴: 신고 → 특별징수 → 회계파일신고
  3. 휴대전화번호 입력
  4. 파일비밀번호 (GUI 툴바 — 홈택스 원천세와 동일 needs_password UI)
  5. 암호화 파일선택 (전자신고파일)
  6. [파일변환하기]
  7. [제출하기]

portal='wetax'. phase_id 는 사이드바 정렬·표시용.
"""

from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=13,
    portal="wetax",
    display_name="위택스 지방세 신고",
    enabled=True,
    # 파일비밀번호 + 휴대전화 — GUI 툴바 (홈택스와 동일 비밀번호 필드 스타일)
    needs_password=True,
    needs_phone=True,
)
class WetaxLocalTaxWorkflow(BaseWorkflow):
    steps = [
        {"name": "connect_wetax", "index": 0},
        {"name": "goto_accounting_file_report", "index": 1},
        {"name": "fill_phone", "index": 2},
        {"name": "enter_file_password", "index": 3},  # 파일선택보다 먼저
        {"name": "select_encrypted_file", "index": 4},
        {"name": "click_convert_file", "index": 5},
        {"name": "click_submit", "index": 6},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, **kwargs,
    ) -> bool:
        """위택스 특별징수 회계파일신고.

        1번(로그인은 AutomationRunner._wait_for_login_wetax 에서 선행).
        2~7번은 순차 구현. 미구현 단계는 명확히 실패 처리.
        """
        # ── 0. 위택스 연결 확인 (로그인은 runner 가 이미 대기 완료·팝업 닫기) ──
        if not state.should_skip_step(job_id, "connect_wetax"):
            state.before_step(job_id, "connect_wetax", 0)
            # AutomationRunner 가 PORTAL_URLS['wetax'](main.do) 로 전환·로그인 대기 완료
            state.after_step(job_id, "connect_wetax")

        # ── 1. 메뉴: 신고 → 특별징수 → 회계파일신고 ──
        if not state.should_skip_step(job_id, "goto_accounting_file_report"):
            state.before_step(job_id, "goto_accounting_file_report", 1)
            from src.automation.wetax._navigation import goto_accounting_file_report
            ok = await goto_accounting_file_report(page)
            if not ok:
                state.fail_step(
                    job_id, "goto_accounting_file_report",
                    "회계파일신고 화면 이동 실패",
                )
                return False
            state.after_step(job_id, "goto_accounting_file_report")

        # ── 2. 휴대전화번호 ──
        if not state.should_skip_step(job_id, "fill_phone"):
            state.before_step(job_id, "fill_phone", 2)
            from src.automation.wetax._form import fill_mobile_phone
            phone = (kwargs.get("phone") or "").strip()
            if not phone:
                state.fail_step(
                    job_id, "fill_phone",
                    "휴대전화번호가 없습니다. GUI 툴바 '휴대전화' 입력란을 확인하세요.",
                )
                return False
            ok = await fill_mobile_phone(page, phone)
            if not ok:
                state.fail_step(job_id, "fill_phone", f"휴대전화 입력 실패: {phone}")
                return False
            state.after_step(job_id, "fill_phone", {"phone": phone})

        # ── 3. 파일비밀번호 (파일선택보다 먼저) ──
        if not state.should_skip_step(job_id, "enter_file_password"):
            state.before_step(job_id, "enter_file_password", 3)
            from src.automation.wetax._form import enter_file_password
            password = kwargs.get("password") or ""
            if not password:
                state.fail_step(
                    job_id, "enter_file_password",
                    "파일비밀번호가 없습니다. GUI 툴바 '비밀번호' 입력란을 확인하세요.",
                )
                return False
            ok = await enter_file_password(page, password)
            if not ok:
                state.fail_step(job_id, "enter_file_password", "파일비밀번호 입력 실패")
                return False
            state.after_step(job_id, "enter_file_password")

        # ── 5~7. 파일선택·변환·제출 — 업로드 파일 준비 후 구현 ──
        # 현재 스냅샷: 로그인~파일비밀번호까지 완료. 아래는 의도적 중단점.
        remaining = [
            ("select_encrypted_file", 4, "암호화 파일선택"),
            ("click_convert_file", 5, "파일변환하기"),
            ("click_submit", 6, "제출하기"),
        ]
        for name, index, label in remaining:
            if state.should_skip_step(job_id, name):
                continue
            state.before_step(job_id, name, index)
            state.fail_step(
                job_id, name,
                f"위택스 '{label}' 단계는 아직 구현되지 않았습니다 "
                f"(전자신고파일 준비 후 반영 예정). 상세: src/automation/wetax/PROGRESS.md",
            )
            return False

        return True

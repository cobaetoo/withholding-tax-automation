"""Phase 13: 위택스 지방세 신고 어댑터 (특별징수세액 · 회계파일신고)

WEHAGO Phase 11(지방소득세특별징수전자신고) 전자신고파일을 위택스에 업로드.

단건(run_single) 파이프라인:
  1. 로그인 완료 가정 (runner _wait_for_login_wetax)
  2. 회계파일신고 화면 (이미 있으면 no-op)
  3. 휴대전화 (GUI phone → #dclrRlpMblTelno)
  4. 파일비밀번호 (GUI password → #filePw)
  5. 암호화 파일선택 (수임처별) — STUB (파일 준비 후 구현)
  6. 파일변환하기 (#btn_next) — STUB
  7. 제출하기 — STUB (실제 제출 시 페이지 리프레시 가정)

다수임처(선택건/전체) 루프:
  로그인 1회 후 수임처마다 run_single 호출.
  실제 제출·리프레시 전에도 스텁이 True 를 반환하므로 다음 수임처로 진행.
  파일 준비 후 5~7 만 실구현하면
  「전화·비번 재입력 → 파일 교체 → 변환 → 제출 → 리프레시」 모델이 된다.

portal='wetax'. phase_id 는 사이드바 정렬·표시용.
"""

from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


# 파일 업로드·변환·제출 실구현 전까지 True.
# 선택건/전체 다수임처 루프가 전화·비번까지 돌고 다음 수임처로 넘어가도록 함.
_STUB_FILE_PIPELINE = True


@register(
    phase_id=13,
    portal="wetax",
    display_name="위택스 지방세 신고",
    enabled=True,
    needs_password=True,
    needs_phone=True,
)
class WetaxLocalTaxWorkflow(BaseWorkflow):
    steps = [
        {"name": "connect_wetax", "index": 0},
        {"name": "goto_accounting_file_report", "index": 1},
        {"name": "fill_phone", "index": 2},
        {"name": "enter_file_password", "index": 3},
        {"name": "select_encrypted_file", "index": 4},
        {"name": "click_convert_file", "index": 5},
        {"name": "click_submit", "index": 6},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, **kwargs,
    ) -> bool:
        """위택스 특별징수 회계파일신고 — 수임처 1건.

        선택건/전체 루프가 수임처마다 호출. 전화·비번 후 파일 파이프라인은
        스텁 성공 → True 반환 → 다음 수임처.
        """
        from src.automation.wetax._common import log

        # ── 0. 연결 (로그인 완료 가정) ──
        if not state.should_skip_step(job_id, "connect_wetax"):
            state.before_step(job_id, "connect_wetax", 0)
            state.after_step(job_id, "connect_wetax")

        # ── 1. 회계파일신고 화면 ──
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

        # ── 2. 휴대전화 (수임처마다 동일 GUI 값 재입력 — 리프레시 대비) ──
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

        # ── 3. 파일비밀번호 (동일 GUI 값 재입력) ──
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

        # ── 4~6. 파일선택 · 변환 · 제출 (스텁 — 파일 준비 후 실구현) ──
        # 스텁이 True 를 반환해야 선택건/전체 루프가 다음 수임처로 넘어간다.
        if not state.should_skip_step(job_id, "select_encrypted_file"):
            state.before_step(job_id, "select_encrypted_file", 4)
            if _STUB_FILE_PIPELINE:
                log(
                    f"  [WETAX stub] [{client_name}] 암호화 파일선택 생략 "
                    f"(파일 준비 후 구현) — 다음 단계로 진행"
                )
                state.after_step(
                    job_id, "select_encrypted_file",
                    {"stub": True, "client": client_name},
                )
            else:
                state.fail_step(
                    job_id, "select_encrypted_file",
                    "암호화 파일선택 미구현",
                )
                return False

        if not state.should_skip_step(job_id, "click_convert_file"):
            state.before_step(job_id, "click_convert_file", 5)
            if _STUB_FILE_PIPELINE:
                log(
                    f"  [WETAX stub] [{client_name}] 파일변환하기(#btn_next) 생략 "
                    f"— 다음 단계로 진행"
                )
                state.after_step(job_id, "click_convert_file", {"stub": True})
            else:
                state.fail_step(job_id, "click_convert_file", "파일변환하기 미구현")
                return False

        if not state.should_skip_step(job_id, "click_submit"):
            state.before_step(job_id, "click_submit", 6)
            if _STUB_FILE_PIPELINE:
                log(
                    f"  [WETAX stub] [{client_name}] 제출하기 생략 "
                    f"(실제출·리프레시 가정) — 수임처 완료, 다음 수임처로"
                )
                state.after_step(job_id, "click_submit", {"stub": True})
            else:
                state.fail_step(job_id, "click_submit", "제출하기 미구현")
                return False

        return True

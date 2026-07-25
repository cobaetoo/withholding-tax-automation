"""Phase 13: 위택스 지방세 신고 어댑터 (특별징수세액 · 회계파일신고)

WEHAGO Phase 11(지방소득세특별징수전자신고) 전자신고파일을 위택스에 업로드.

단건(run_single) 파이프라인:
  1. 로그인 완료 가정 (runner _wait_for_login_wetax)
  2. 회계파일신고 화면 (이미 있으면 no-op)
  3. 휴대전화 (GUI phone → #dclrRlpMblTelno)
  4. 파일비밀번호 (GUI password → #filePw)
  5. 암호화 파일선택 (수임처별) — 구현
     경로: 지방소득세전자신고_{YYYYMM}/{수임처}/ 최신 .1/.2 파일
  6. 파일변환하기 (#btn_next) — 구현 (confirm 수락·복원 → M32)
  7. 제출하기 (#btn_next 제출 라벨) — 실구현
     정상≥1·오류0 게이트, 성공 후 ensure_upload_form(M31)

portal='wetax'. phase_id 는 사이드바 정렬·표시용.
"""

import os

from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


# True 면 제출 클릭 생략. 운영/라이브 기본 False.
# WETAX_STUB_SUBMIT=1 이면 스텁 (다건 루프 검증·중복 제출 방지).
# stay_on_m32=True 이고 스텁일 때만 M32 유지(검증용).
_STUB_SUBMIT = os.environ.get("WETAX_STUB_SUBMIT", "").strip().lower() in (
    "1", "true", "yes", "on",
)


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

        선택건/전체 루프가 수임처마다 호출. 변환·제출 실구현.
        kwargs:
          stay_on_m32: True 면 제출 후(또는 스텁 시) M31 복귀 생략
        """
        from src.automation.wetax._common import log, mask_phone

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
                state.fail_step(
                    job_id, "fill_phone",
                    f"휴대전화 입력 실패: {mask_phone(phone)}",
                )
                return False
            state.after_step(
                job_id, "fill_phone",
                {"phone": mask_phone(phone)},
            )

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

        # ── 4. 암호화 파일선택 (Phase 11 컨벤션 폴더) ──
        if not state.should_skip_step(job_id, "select_encrypted_file"):
            state.before_step(job_id, "select_encrypted_file", 4)
            from src.automation.wetax._form import (
                find_jitax_encrypted_file,
                select_encrypted_file,
            )
            year = kwargs.get("year")
            month = kwargs.get("month")
            file_path = find_jitax_encrypted_file(client_name, year=year, month=month)
            if not file_path:
                state.fail_step(
                    job_id, "select_encrypted_file",
                    f"전자신고 파일 없음: 지방소득세전자신고_{year or '?'}{int(month or 0):02d}/"
                    f"{client_name.replace(' ', '_')}/ 를 확인하세요.",
                )
                return False
            ok = await select_encrypted_file(page, file_path)
            if not ok:
                state.fail_step(
                    job_id, "select_encrypted_file",
                    f"파일 선택 실패: {file_path}",
                )
                return False
            state.after_step(
                job_id, "select_encrypted_file",
                {"file": os.path.basename(file_path)},
            )

        # ── 5. 파일변환하기 (실구현) ──
        if not state.should_skip_step(job_id, "click_convert_file"):
            state.before_step(job_id, "click_convert_file", 5)
            from src.automation.wetax._form import click_convert_file
            convert_meta: dict = {}
            ok = await click_convert_file(page, result_out=convert_meta)
            if not ok:
                state.fail_step(
                    job_id, "click_convert_file",
                    "파일변환하기 실패 (확인창·화면 전환 타임아웃)",
                )
                return False
            # 오류 N건이어도 변환 단계는 성공 — step_data 에 요약만 기록
            # (제출 단계에서 오류>0 이면 거부)
            state.after_step(job_id, "click_convert_file", convert_meta or None)

        # ── 6. 제출하기 ──
        # stay_on_m32: 제출 후 M31 복귀 생략 (결과 화면 확인용)
        stay_on_m32 = bool(kwargs.get("stay_on_m32"))
        if not state.should_skip_step(job_id, "click_submit"):
            state.before_step(job_id, "click_submit", 6)
            if _STUB_SUBMIT:
                if stay_on_m32:
                    try:
                        url_now = page.url or ""
                    except Exception:
                        url_now = "?"
                    log(
                        f"  [WETAX stub] [{client_name}] 제출하기 생략 "
                        f"— stay_on_m32 (M31 복귀 안 함) url={url_now}"
                    )
                    try:
                        from src.automation.wetax._form import (
                            get_convert_result_summary,
                        )
                        summary = await get_convert_result_summary(page)
                        log(
                            f"  [WETAX stub] 서식검증 요약 "
                            f"정상={summary.get('ok')} 오류={summary.get('err')} "
                            f"url={summary.get('url')}"
                        )
                    except Exception as e:
                        log(f"  [WETAX stub] 서식검증 요약 실패: {e}")
                        summary = {}
                    state.after_step(
                        job_id, "click_submit",
                        {
                            "stub": True,
                            "ensured_m31": False,
                            "stay_on_m32": True,
                            **(summary if isinstance(summary, dict) else {}),
                        },
                    )
                else:
                    log(
                        f"  [WETAX stub] [{client_name}] 제출하기 생략 "
                        f"— M31 복귀 후 다음 수임처"
                    )
                    from src.automation.wetax._navigation import ensure_upload_form
                    try:
                        back = await ensure_upload_form(page)
                        if not back:
                            log(
                                f"  [WETAX stub] [{client_name}] "
                                f"ensure_upload_form 실패(다음 수임처 goto 가 재시도)"
                            )
                    except Exception as e:
                        log(f"  [WETAX stub] ensure_upload_form 예외: {e}")
                    state.after_step(
                        job_id, "click_submit",
                        {"stub": True, "ensured_m31": True},
                    )
            else:
                from src.automation.wetax._form import click_submit_report
                submit_meta: dict = {}
                ok = await click_submit_report(
                    page, result_out=submit_meta, require_ok=True,
                )
                if not ok:
                    state.fail_step(
                        job_id, "click_submit",
                        "제출하기 실패 (게이트 거부·확인창·성공 시그널 타임아웃)",
                    )
                    return False
                log(
                    f"  [WETAX] [{client_name}] 제출 완료 "
                    f"reason={submit_meta.get('reason')} url={submit_meta.get('url')}"
                )
                ensured = False
                if not stay_on_m32:
                    from src.automation.wetax._navigation import ensure_upload_form
                    try:
                        ensured = bool(await ensure_upload_form(page))
                        if not ensured:
                            log(
                                f"  [WETAX] [{client_name}] "
                                f"제출 후 ensure_upload_form 실패"
                            )
                    except Exception as e:
                        log(f"  [WETAX] ensure_upload_form 예외: {e}")
                state.after_step(
                    job_id, "click_submit",
                    {
                        "stub": False,
                        "ensured_m31": ensured,
                        "stay_on_m32": stay_on_m32,
                        **submit_meta,
                    },
                )

        return True

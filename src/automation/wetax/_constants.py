"""위택스 포털 상수."""

WETAX_URL = "https://www.wetax.go.kr/main.do"
WETAX_HOST = "wetax.go.kr"

# Phase 11 전자신고파일 저장 최상위 (make_save_dir site_name 과 동일)
JITAX_EFILE_SITE = "지방소득세전자신고"

# 특별징수 회계파일신고 (라이브 확인 2026-07-24)
# GNB: 신고 → 특별징수 → 회계파일신고
# 화면 제목: "특별징수 회계파일신고"
ACCOUNTING_FILE_REPORT_PATH = "/etr/lit/b0701/B070101M31.do"
ACCOUNTING_FILE_REPORT_URL = f"https://www.wetax.go.kr{ACCOUNTING_FILE_REPORT_PATH}"
# 파일변환 후 서식검증·제출 화면 (라이브 2026-07-24)
ACCOUNTING_CONVERT_RESULT_PATH = "/etr/lit/b0701/B070101M32.do"

# 신고서 업로드 화면 필드 (B070101M31) — 라이브 덤프
FIELD_PHONE = "dclrRlpTelno"           # 전화번호 (유선, 기입력될 수 있음)
FIELD_MOBILE = "dclrRlpMblTelno"       # 휴대전화번호 ★ 담당자 입력
FIELD_FILE_INPUT = "file_upload_0_"    # 암호화 파일 <input type=file>
FIELD_FILE_PW = "filePw"               # 파일비밀번호
BTN_CONVERT = "btn_next"               # 파일변환하기 (M31 하단). M32 에서는 같은 id 가 제출하기
# 제출 후 페이지 리프레시 → 수임처마다 전화·비번 재입력 + 파일만 교체 (PROGRESS 다수임처 루프)

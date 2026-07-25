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
# 제출결과확인 후보 경로 (라이브 제출 시 확정·보정)
ACCOUNTING_SUBMIT_RESULT_PATH = "/etr/lit/b0701/B070101M33.do"

# 신고서 업로드 화면 필드 (B070101M31) — 라이브 덤프
FIELD_PHONE = "dclrRlpTelno"           # 전화번호 (유선, 기입력될 수 있음)
FIELD_MOBILE = "dclrRlpMblTelno"       # 휴대전화번호 ★ 담당자 입력
FIELD_FILE_INPUT = "file_upload_0_"    # 암호화 파일 <input type=file>
FIELD_FILE_PW = "filePw"               # 파일비밀번호
# M31 하단 "파일변환하기" / M32 하단 "제출하기" — **동일 id** (`#btn_next`).
# 클릭 전에 URL(M31) 또는 버튼 라벨로 구분해야 함 (W2).
BTN_CONVERT = "btn_next"               # 파일변환하기 (M31). M32 동일 id 는 제출하기
BTN_SUBMIT = "btn_next"                # 제출하기 (M32) — BTN_CONVERT 와 id 동일 (별칭)
LABEL_CONVERT = "파일변환"             # 버튼 텍스트 부분일치
LABEL_SUBMIT = "제출하기"              # 제출 라벨 (부분일치 "제출" 도 사용)
# Phase 11 전자신고 허용 확장자 (find_jitax_encrypted_file)
JITAX_EFILE_EXTS = (".1", ".2")
# 제출 후 페이지 리프레시 → 수임처마다 전화·비번 재입력 + 파일만 교체 (PROGRESS 다수임처 루프)

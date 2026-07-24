# 위택스(Wetax) 자동화 진행 상황

## 범위 (현재 스냅샷)

**Phase 13 — 위택스 지방세 신고 (특별징수 · 회계파일신고)**  
업로드용 전자신고파일은 별도 준비 중 → **파일선택·변환·제출은 미구현(의도적 중단점)**.

### 구현 완료 (✅)
| # | 단계 | 코드 |
|---|------|------|
| 0 | 메인 이벤트 팝업 닫기 (로그인 전·후) | `dismiss_popups` / runner 로그인 대기 직전·직후 |
| 1 | 전자세금용 공인인증서 로그인 대기 | `_wait_for_login_wetax` / `_wetax_logged_in` |
| 2 | 메뉴 → 회계파일신고 화면 | `goto_accounting_file_report` → `B070101M31.do` |
| 3 | 휴대전화번호 입력 | GUI `needs_phone` → `fill_mobile_phone` (`#dclrRlpMblTelno`) |
| 4 | 파일비밀번호 입력 | GUI `needs_password` → `enter_file_password` (`#filePw`) |

### 미구현 (⏸ 파일 준비 후)
| # | 단계 | 예상 셀렉터 / 비고 |
|---|------|-------------------|
| 5 | 암호화 파일선택 | `#file_upload_0_` (`input[type=file]`) — Phase 11 결과물 |
| 6 | 파일변환하기 | `#btn_next` |
| 7 | 제출하기 | **2 서식검증 및 제출** 탭 이후 (+ dry-run 예정) |

---

## 파일 위치
- `src/workflows/wetax_local_tax.py` — Phase 13 어댑터·레지스트리
- `src/automation/wetax/_common.py` — 팝업 닫기
- `src/automation/wetax/_navigation.py` — 회계파일신고 이동
- `src/automation/wetax/_form.py` — 휴대전화·파일비밀번호
- `src/automation/wetax/_constants.py` — URL·필드 id
- GUI: 사이드바 **▼ 위택스** > **위택스 지방세 신고**
- 프로브(개발용): `_probe_wetax_login.py`, `_probe_wetax_dismiss_popups.py`, `_probe_wetax_menu.py`

## 기술 스택
- Playwright + CDP (포트 9223)
- 포털: `https://www.wetax.go.kr/main.do`
- Human-in-the-loop 공인인증서 로그인

## 전제조건
1. Phase 11(지방소득세특별징수전자신고)로 전자신고파일 선제작 — **파일선택 단계 재개 시 필요**
2. 전자신고파일 비밀번호 (GUI 툴바 **비밀번호**, 홈택스와 동일 스타일)
3. 담당자 휴대전화번호 (GUI 툴바 **휴대전화**)

## 상세 메모

### 팝업
- `div.main-popup-event#pop_*` + `button.close-btn` (개수·id 가변)
- Playwright real click 우선; jQuery `fnCloseBtn` / `.hide()` 폴백
- 로그인 전·후 각 1회 호출 (`login.do` 복귀 시 팝업 재생성)

### 로그인 판정
1. `a.btnLogout` 가시
2. **로그인연장** 텍스트/버튼 (하위 화면에서 logout 비가시 대비)
3. 텍스트 `로그아웃`

### 회계파일신고
- URL: `https://www.wetax.go.kr/etr/lit/b0701/B070101M31.do`
- 탭: `1 신고서업로드` → `2 서식검증 및 제출` → `3 제출결과확인`

### GUI kwargs 전달
- `password`, `phone` → 전체실행/선택건 모두 runner 큐 → `run_single`  
- 회귀: `tests/test_wetax_gui_kwargs_passthrough.py`, `tests/test_wetax_toolbar_fields.py`

### Chrome CDP 수명 (Windows)
- 에이전트 Job Object 종료 시 자식 Chrome이 같이 죽지 않도록  
  `launch_chrome` 에 **CREATE_BREAKAWAY_FROM_JOB** 등 분리 플래그 적용 (`src/utils/chrome_cdp.py`)

## 변경 이력
- 2026-07-24: 메뉴·portal 등록, 팝업·로그인·이동·전화·파일비번·GUI 툴바까지 구현.  
  파일선택 이후는 업로드 파일 준비 후 진행 (이 문서 기준 스냅샷).

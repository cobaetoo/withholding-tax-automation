# 위택스(Wetax) 자동화 진행 상황

## 범위 (현재 스냅샷)

**Phase 13 — 위택스 지방세 신고 (특별징수 · 회계파일신고)**  
파일선택·변환까지 실구현. **제출만 스텁** (`_STUB_SUBMIT = True`).

### 구현 완료 (✅)
| # | 단계 | 코드 |
|---|------|------|
| 0 | 메인 이벤트 팝업 닫기 (로그인 전·후) | `dismiss_popups` / runner 로그인 대기 직전·직후 |
| 1 | 전자세금용 공인인증서 로그인 대기 | `_wait_for_login_wetax` / `_wetax_logged_in` |
| 2 | 메뉴 → 회계파일신고 화면 | `goto_accounting_file_report` → `B070101M31.do` |
| 3 | 휴대전화번호 입력 | GUI `needs_phone` → `fill_mobile_phone` (`#dclrRlpMblTelno`) |
| 4 | 파일비밀번호 입력 | GUI `needs_password` → `enter_file_password` (`#filePw`) |
| 5 | 암호화 파일선택 | `find_jitax_encrypted_file` (`.1`/`.2` only) + `select_encrypted_file` |
| 6 | 파일변환하기 | `click_convert_file` — confirm 임시수락·복원, 라벨 가드 → M32 |

### 안전 헬퍼 (제출 전 리팩터)
| 모듈 | 역할 |
|------|------|
| `_dialogs.accept_native_dialogs` | confirm/alert 가로채기 + **finally 복원** |
| `LABEL_CONVERT` / `LABEL_SUBMIT` | M31/M32 동일 `#btn_next` 구분 |
| `mask_phone` | 로그·step_data 휴대전화 마스킹 |
| `get_convert_result_summary` / `result_out` | 정상·오류 건수 메타 (err>0 이어도 변환 성공) |
| `ensure_upload_form` | M31 업로드 화면 보장 (스텁 후·다음 수임처) |

### 남은 스텁
| # | 단계 | 예상 셀렉터 / 비고 | 현재 |
|---|------|-------------------|------|
| 7 | 제출하기 | M32 `#btn_next`(제출하기) — 제출 후 리프레시 가정 | **STUB** + `ensure_upload_form` |

`_STUB_SUBMIT = True` (`wetax_local_tax.py`).  
변환 성공 후 정상 0건·오류 N건이어도 변환 단계는 성공으로 본다(검증 오류는 파일 재생성 영역).

### 다수임처 루프 설계 (선택건·전체실행 공통 목표) — ★ 확정

```text
[세션] 로그인 1회 + (필요 시) 회계파일신고 화면 진입 1회
for 각 수임처:
  1. 동일 휴대전화 재입력   (#dclrRlpMblTelno)  ← GUI phone, 수임처 공통
  2. 동일 파일비밀번호 재입력 (#filePw)         ← GUI password, 수임처 공통
  3. 해당 수임처 암호화 파일만 교체 업로드      (#file_upload_0_, .1/.2)
  4. 파일변환하기 클릭                          (#btn_next + 변환 라벨)
  5. 제출하기 — 현재 STUB → ensure_upload_form(M31)
  (라이브 시) 제출 → 리프레시 → 폼 빈 상태 확인
  → 다음 수임처로
```

| 항목 | 정책 |
|------|------|
| 로그인 | runner 단 1회 (선택건/전체 공통) |
| 메뉴 이동 | 첫 수임처 또는 `ensure_upload_form` / M32 이탈 시 |
| 전화·파일비번 | **수임처마다 다시 넣음** (동일 GUI 값, 로그 마스킹) |
| 파일 | **수임처마다 다른 `.1`/`.2`** 만 교체 |
| 변환·제출 | 변환 실구현 / 제출 스텁 → M31 복귀 |

**현재 코드:** 수임처마다 `run_single` → 전화·비번 → 파일선택 → **파일변환(M32)** → 제출 스텁 → `True`.  
다음 수임처 시 `goto` 가 M32 를 업로드 화면으로 보지 않고 **M31 재진입**.

---

## 파일 위치
- `src/workflows/wetax_local_tax.py` — Phase 13 어댑터·레지스트리
- `src/automation/wetax/_common.py` — 팝업 닫기·`mask_phone`
- `src/automation/wetax/_navigation.py` — 회계파일신고 이동·`ensure_upload_form`
- `src/automation/wetax/_form.py` — 휴대전화·파일비밀번호·변환
- `src/automation/wetax/_dialogs.py` — confirm/alert 임시 수락·복원
- `src/automation/wetax/_constants.py` — URL·필드 id·라벨
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

### 전체실행 vs 선택건 로그인 대기
- **전체실행** (`_handle_run_phase`): 브라우저 재사용 여부와 무관하게 **항상** `_wait_for_login("wetax")`
- **선택건** (`_handle_run_selected_clients`): 동일하게 **항상** `_wait_for_login` (재사용 시에도).
  이전에는 `reused=True` 이면 로그인·팝업 닫기를 건너뛰어 위택스 세션 만료/팝업 잔존 리스크가 있었음.
  회귀: `tests/test_selected_run_login_always.py`

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
- 2026-07-24: 안전 리팩터 — confirm/alert 임시 수락 후 복원(`_dialogs.accept_native_dialogs`),
  `#btn_next` 변환/제출 이중 의미 가드(LABEL_CONVERT/SUBMIT), efile 확장자 `.1`/`.2` 만 허용,
  휴대전화 마스킹, 변환 결과 메타(`get_convert_result_summary`)·`ensure_upload_form`(스텁 후 M31 복귀).
- 2026-07-24: 파일변환하기 실구현 (`click_convert_file` — confirm 오버라이드 + M32 대기). 제출만 스텁.
- 2026-07-24: 선택건 다수임처 라이브 확인 — 파일 스텁으로 전화·비번 루프 후 다음 수임처 진행 OK.
- 2026-07-24: 선택건 재사용 시 로그인 대기 정렬 + 라이트 테마(QSS/팔레트) 강화.
- 2026-07-24: 파일변환·제출 스텁 성공 — 선택건/전체가 전화·비번 후 다음 수임처로 진행.
- 2026-07-24: 다수임처 루프 설계 확정 — 제출→리프레시 후 동일 전화·비번 재입력 + 수임처별 파일만 교체.
- 2026-07-24: 선택건 실행에서도 세션 재사용 시 로그인 대기 항상 수행 (전체실행과 동일).  
  회귀: `tests/test_selected_run_login_always.py`
- 2026-07-24: 메뉴·portal 등록, 팝업·로그인·이동·전화·파일비번·GUI 툴바까지 구현.  
  파일선택 이후는 업로드 파일 준비 후 진행 (이 문서 기준 스냅샷).

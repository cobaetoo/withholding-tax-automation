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

### 파일 파이프라인 (⏸ 실구현 대기 · 현재 스텁)
| # | 단계 | 예상 셀렉터 / 비고 | 현재 |
|---|------|-------------------|------|
| 5 | 암호화 파일선택 | `#file_upload_0_` — Phase 11 결과물 | **STUB** 성공 → 다음 수임처 진행 |
| 6 | 파일변환하기 | `#btn_next` | **STUB** 성공 |
| 7 | 제출하기 | 제출 후 페이지 리프레시 가정 | **STUB** 성공 |

`_STUB_FILE_PIPELINE = True` (`wetax_local_tax.py`).  
파일 준비되면 스텁 블록만 실구현으로 교체. 스텁 동안 선택건/전체는  
**전화·비번까지 수임처마다 반복 후 다음 수임처로 넘어감** (변환·제출 버튼은 누르지 않음).

### 다수임처 루프 설계 (선택건·전체실행 공통 목표) — ★ 확정

제출 후 화면이 **리프레시**되어 업로드 폼이 초기화된다는 전제:

```text
[세션] 로그인 1회 + (필요 시) 회계파일신고 화면 진입 1회
for 각 수임처:
  1. 동일 휴대전화 재입력   (#dclrRlpMblTelno)  ← GUI phone, 수임처 공통
  2. 동일 파일비밀번호 재입력 (#filePw)         ← GUI password, 수임처 공통
  3. 해당 수임처 암호화 파일만 교체 업로드      (#file_upload_0_)
  4. 파일변환하기 클릭                          (#btn_next)
  5. 제출하기 클릭
  6. 제출 후 페이지 리프레시 대기 → 폼 빈 상태 확인
  → 다음 수임처로 (1~6 반복; 로그인/메뉴 재진입 불필요)
```

| 항목 | 정책 |
|------|------|
| 로그인 | runner 단 1회 (선택건/전체 공통) |
| 메뉴 이동 | 첫 수임처 또는 회계파일신고 URL 이탈 시에만 |
| 전화·파일비번 | **제출 리프레시마다 다시 넣음** (동일 GUI 값) |
| 파일 | **수임처마다 다른 파일**만 교체 |
| 변환·제출 | 수임처마다 `#btn_next` → 제출하기 |

**현재 코드:** 수임처마다 `run_single` → 전화·비번 재입력 → 파일 3단계 **스텁 성공** → `True`  
→ 선택건/전체 루프가 **다음 수임처로 진행**. (이미 회계파일신고면 `goto` no-op)  
실제출·리프레시는 스텁 구간이라 화면은 안 바뀜; 전화·비번 재입력 루프만 검증 가능.

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
- 2026-07-24: 선택건 다수임처 라이브 확인 — 파일 스텁으로 전화·비번 루프 후 다음 수임처 진행 OK.
- 2026-07-24: 선택건 재사용 시 로그인 대기 정렬 + 라이트 테마(QSS/팔레트) 강화.
- 2026-07-24: 파일변환·제출 스텁 성공 — 선택건/전체가 전화·비번 후 다음 수임처로 진행.
- 2026-07-24: 다수임처 루프 설계 확정 — 제출→리프레시 후 동일 전화·비번 재입력 + 수임처별 파일만 교체.
- 2026-07-24: 선택건 실행에서도 세션 재사용 시 로그인 대기 항상 수행 (전체실행과 동일).  
  회귀: `tests/test_selected_run_login_always.py`
- 2026-07-24: 메뉴·portal 등록, 팝업·로그인·이동·전화·파일비번·GUI 툴바까지 구현.  
  파일선택 이후는 업로드 파일 준비 후 진행 (이 문서 기준 스냅샷).

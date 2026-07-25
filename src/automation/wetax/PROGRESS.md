# 위택스(Wetax) 자동화 진행 상황

> **문서 역할:** Phase 13 구현 상태 · 라이브 검증 · 핸드오프의 단일 소스.  
> 사용자 안내는 `USER_GUIDE.md` §14, 개발 요약은 `GUIDE.md` Phase 13 과 맞춘다.

## ▶ 현재 상태 (2026-07-25)

| 항목 | 내용 |
|------|------|
| **상태** | **변환 + 제출 실구현** · 다건 루프 라이브 PASS |
| **기본 제출** | `_STUB_SUBMIT=False` (운영). `WETAX_STUB_SUBMIT=1` 시 스텁 |
| **게이트** | 정상 ≥1 · 오류>0 이면 제출 거부 (`require_ok=True`) |
| **제출 성공 시그널** | M33 `B070101M33.do` · confirm `제출 하시겠습니까?` |
| **단건 라이브** | 주식회사 드류 `20260725A103900.1` → M32 정상1 → 제출 → M33 |
| **다건 라이브** | 드류 파일 복사 2건 연속 실제출 PASS (전화·비번 재입력 → 변환 → 제출 → M31) |

### 남은 일 (선택)
| 순 | 작업 | 메모 |
|----|------|------|
| 1 | 오류 N건 정책 (PO) | 현재: 제출 거부. 스킵/경고 후 다음 미결정 |
| 2 | 1건 실패 시 계속 vs 중단 | 선택건 runner 는 브라우저 생존 시 다음 건 계속 |
| 3 | 일괄신고목록·접수번호 파싱 | M33 안내: 일괄신고목록에서 확인 |
| 4 | (선택) 중간 단계 가시성 강화 | confirm 자동수락으로 UI 가 빠르게 지나감 |

### 개발·라이브 스크립트
| 스크립트 | 용도 |
|----------|------|
| `scripts/run_wetax_live.py` | 단건 라이브 (`--stay-m32` = 결과 화면 유지) |
| `scripts/run_wetax_multi_live.py` | 다건 라이브 (`--real-submit`, `--pause` 눈확인용 기본 0) |
| `scripts/e2e_wetax_w10_live.py` | `ensure_upload_form` E2E |
| `scripts/e2e_wetax_refactor.py` | 안전 헬퍼 로컬/라이트 E2E |

### 한 줄 참고
```
위택스 Phase 13: 제출 click_submit_report 실구현 완료.
다건 = 전화·비번 재입력 → 파일 → 변환 → 제출(M33) → ensure_upload_form(M31).
스텁이 필요하면 WETAX_STUB_SUBMIT=1.
```

---

## 범위 (현재 스냅샷)

**Phase 13 — 위택스 지방세 신고 (특별징수 · 회계파일신고)**  
파일선택·변환·**제출 실구현**. 운영 기본 제출 ON.

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
| 7 | 제출하기 | `click_submit_report` — 게이트·라벨 가드·confirm → M33 |

### 안전 헬퍼
| 모듈 | 역할 |
|------|------|
| `_dialogs.accept_native_dialogs` | confirm/alert 가로채기 + **finally 복원** |
| `LABEL_CONVERT` / `LABEL_SUBMIT` | M31/M32 **동일 id `#btn_next`** 구분 |
| `mask_phone` | 로그·step_data 휴대전화 마스킹 |
| `get_convert_result_summary` / `_wait_convert_summary` | 정상·오류 건수 (표 렌더 폴링) |
| `ensure_upload_form` | 제출 후 M31 업로드 화면 (다음 수임처) |
| `stay_on_m32` kwargs | 단건 검증 시 결과 화면 유지 (M31 복귀 생략) |

**제출 게이트:** 오류>0 또는 정상<1 이면 제출 거부.  
**변환 단계:** 오류 N건이어도 변환 자체는 성공으로 기록(step_data 메타).

### 다수임처 루프 — ★ 확정·라이브 검증

```text
[세션] 로그인 1회
for 각 수임처:
  1. 동일 휴대전화 재입력   (#dclrRlpMblTelno)
  2. 동일 파일비밀번호 재입력 (#filePw)
  3. 해당 수임처 암호화 파일 업로드  (#file_upload_0_, .1/.2)
  4. 파일변환하기 (#btn_next + 변환 라벨) → M32
  5. 제출하기 (#btn_next + 제출 라벨) → M33
  6. ensure_upload_form → M31 (빈 업로드 폼)
  → 다음 수임처
```

| 항목 | 정책 |
|------|------|
| 로그인 | runner 단 1회 (선택건/전체 공통, 재사용 시에도 대기) |
| 전화·파일비번 | **수임처마다 다시 넣음** (동일 GUI 값) |
| 파일 | **수임처마다 다른 `.1`/`.2`** |
| 변환·제출 | 실구현. 제출 후 M31 복귀 |
| CDP 창 | `chrome-cdp-link` 프로필 — **일반 Chrome 과 별개** |

**라이브 (2026-07-25):** 드류 efile 2건 연속 실제출 2회 루프 PASS.

---

## 파일 위치
- `src/workflows/wetax_local_tax.py` — Phase 13 어댑터·`_STUB_SUBMIT`·`run_single`
- `src/automation/wetax/_common.py` — 팝업 닫기·`mask_phone`
- `src/automation/wetax/_navigation.py` — 회계파일신고 이동·`ensure_upload_form`
- `src/automation/wetax/_form.py` — 전화·비번·파일·변환·**제출**
- `src/automation/wetax/_dialogs.py` — confirm/alert 임시 수락·복원
- `src/automation/wetax/_constants.py` — M31/M32/M33 · `#btn_next` · 라벨
- GUI: 사이드바 **▼ 위택스** > **위택스 지방세 신고**
- 라이브: `scripts/run_wetax_live.py`, `scripts/run_wetax_multi_live.py`
- 단위 테스트: `tests/test_wetax_*.py` (dialogs, file_find, submit_guard, kwargs, toolbar, login)

## 기술 스택
- Playwright + CDP (포트 **9223**)
- 포털: `https://www.wetax.go.kr/main.do`
- Human-in-the-loop 공인인증서 로그인 (전자세금용)

## 전제조건
1. Phase 11 전자신고파일 (`지방소득세전자신고_{YYYYMM}/{수임처}/` · `.1`/`.2`)
2. 파일 비밀번호 (GUI 툴바 **비밀번호**)
3. 담당자 휴대전화 (GUI 툴바 **휴대전화**)

## 상세 메모

### 팝업
- `div.main-popup-event#pop_*` + `button.close-btn`
- 로그인 전·후 각 1회 (`login.do` 복귀 시 팝업 재생성)

### 로그인 판정
1. `a.btnLogout` 가시
2. **로그인연장** 텍스트/버튼
3. 텍스트 `로그아웃`

### 화면 경로
| 코드 | 경로 | 단계 |
|------|------|------|
| M31 | `B070101M31.do` | 1 신고서업로드 |
| M32 | `B070101M32.do` | 2 서식검증 및 제출 |
| M33 | `B070101M33.do` | 3 제출결과확인 (일괄신고 제출처리중) |

M31·M32 하단 버튼 **동일 id `#btn_next`** — 라벨으로만 변환/제출 구분.

### GUI kwargs
- `password`, `phone` → 전체/선택건 runner → `run_single`
- 회귀: `tests/test_wetax_gui_kwargs_passthrough.py`, `test_wetax_toolbar_fields.py`

### 안전 리팩터 (2026-07-25, 기능 유지)
| 항목 | 내용 |
|------|------|
| 성공 시그널 | **M33 URL strict** — left_m32 / m31+filePw / 광범위 키워드 제거 |
| 라벨 가드 | convert/submit 라벨 확인 실패 시 **hard-fail** (클릭 안 함) |
| confirm | 제출 `message_substr=제출` + `on_mismatch=reject` |
| M32 early | 변환 생략 금지 → **M31 재진입 후 변환** |
| ensure 실패 | 제출 후 M31 복귀 실패 시 **job fail** (1회 재시도) |
| stub API | `resolve_stub_submit` / `kwargs stub_submit` (모듈 패치 불필요) |
| 로그인 | `_session.is_logged_in` 단일화 (runner·live·multi) |
| 로그 | `[step]` 경계 로그 표준화 |

### 변경 이력 (요약)
- 2026-07-25: 안전 리팩터 PR1–6 (시그널·가드·ensure·stub kwargs·session·로그)
- 2026-07-25: 제출 실구현 · 다건 실제출 라이브 PASS · live/multi 스크립트
- 2026-07-24: 변환 실구현 · 안전 리팩터 · 제출 스텁 핸드오프

# 기술 부채 레지스터 (Tech Debt Register)

> **목적:** 원천징수세 자동화 프로젝트의 기술 부채·결함·로드맵을 **단일 진실표**로 통합 관리.
> 산재해 있던 부채 관련 내용(핸드오프·도메인 PROGRESS·GUIDE 임베디드 리스크)을 한곳에서 우선순위화한다.
>
> **기준 시점:** 2026-07-25 · **버전:** `1.1.3` (`src/version.py`) · **HEAD:** `6484692`
> **관점:** GUI 프로그램(`gui_main.py` → `MainWindow` → Workers → Workflows → Automation → Utils → Chrome CDP) 기준.
> 코드를 수정하기 전, 본 문서의 해당 항목과 [§1 산재 문서 관계]를 함께 읽을 것.
>
> **세션 마무리(2026-07-25):** 옵션 A(TD-05·17·02·10) 완료·push. **Wave 3(옵션 B)는 보류**
> (실행 경로 변경·골든 미캡처·파급 전 Phase — 위험 높음). 다음 구조 작업은
> 골든 기준선 후 TD-04/13 또는 Wave 4 저위험부터.
>
> **⚠ 이 문서는 코드 상태를 스냅샷한 것이다.** 줄번호는 리팩토링으로 밀린다.
> 항목을 착수하기 전 §9 변경 이력의 마지막 검증일과 현재 HEAD 를 대조하고,
> 줄번호가 아니라 **함수명으로 먼저 찾을 것**.

---

## 0. 범례

| 기호 | 의미 |
|---|---|
| **우선순위** | 🔴 HIGH(즉시/사용자 영향) · 🟡 MED(구조·정확성) · 🟢 LOW(정리) |
| **상태** | ⬜ 미해결 · 🟦 부분해결 · ✅ 해결(커밋) |
| **검증** | 🔍 코드 직접 확인 · 👁 관찰·문서 인용 · ⚠ 라이브 미검증 |
| **출처** | 사용자표(사용자 정리) · 분석(아키텍처 파악) · 둘 다 |
| **카테고리** | 런타임결함 · 구조 · 데이터결함 · correctness · 빌드 · 문서 · 레거시 · 로깅 |

> **범례 변경(2026-07-20):** 이전 판은 `✅` 를 "코드 직접 확인"(검증됨) 의미로 썼는데
> "해결됨"으로 오독되기 쉬웠다. **상태**와 **검증**을 별도 컬럼으로 분리했다.

---

## 1. 기존 산재 문서와의 관계 (중복 회피)

본 레지스터는 **단일 진실표**이나, 세부 실행계획·기술 배경은 다음 기존 문서가 원천이다. 본 문서는 우선순위·상태·위치만 추적하고 중복 기술을 피한다.

| 기존 문서 | 본 레지스터와의 관계 |
|---|---|
| `docs/refactoring-handoff.md` | **Wave 3**(engine↔runner)·**Wave 4**(메뉴정리). TD-02/05 데이터 결함은 2026-07-25 선조치됨 — Wave 3 본체는 여전히 **TD-04 / TD-13**. 골든 스냅샷 기법은 handoff가 원천. |
| `docs/parallel-automation-handoff.md` | 병렬 안정화·open items. 본 문서 **TD-07 / LV-4 / LV-5** 참조. |
| `src/automation/wehago/PROGRESS.md` | 도메인 진행 + `## 다음 단계 TODO`(대부분 MVP 시절, 상당수 완료). 미완료만 **LV-5**로 인용. |
| `src/automation/hometax/PROGRESS.md` | 제출 플로우 완료·라이브 검증(2026-07-17). **Phase 10 `enabled=True`**. 남은 TODO: 접수증 저장·신고내역 다운로드. ⚠ 포트 `9222` 오기 — TD-12. |
| `src/automation/wetax/PROGRESS.md` | Phase 13 제출·다건·안전 가드 **완료**(2026-07-25). 구조 부채 아님. 제품 잔여: 오류 N건 정책·일괄목록/접수번호. |
| `GUIDE.md` (§risk 계열) | 기술 문서 내 임베디드 리스크. 본 문서가 상위 레지스터. |

---

## 2. 단일 우선순위 매트릭스

| ID | Pri | 상태 | 카테고리 | 항목 | 위치 | 영향 | 검증 | 출처 |
|---|---|---|---|---|---|---|---|---|
| **TD-01** | 🔴 | ✅ | 빌드 | ~~installer_output/ 정합성 깨짐~~ → **해결**: 해시 계산 후 동일 파일을 ASCII명으로 복사하는 순서 보장 | `release.py:118-123,158-161` | — | 🔍 | 사용자 |
| **TD-02** | 🔴 | ✅ | 런타임결함 | ~~`_reset_batch` 전 wipe~~ → **해결**: running/paused→crashed, completed/archived만 삭제, crashed/created 유지 | `automation_runner._reset_batch` | 크래시 배치 prepare_batch 재사용 가능 | 🔍 | 분석 |
| **TD-03** | 🔴 | ⬜ | 구조 | `db.py` 1,210줄 — Repository 4개 CRUD 반복 + duration 계산 3곳 중복 + 카운터 동기화 2방식 혼재 | `src/batch/db.py:857,905,1107` | 유지보수성, 카운터 불일치 위험 | 🔍 | 둘 다 |
| **TD-04** | 🔴 | ⬜ | 구조 | `automation_runner.py` 1,239줄 — Playwright 생명주기 + 5포털 로그인 + 엔진 연동 + 브라우저 복구 혼재 | `src/ui/workers/automation_runner.py` | 책임 분리 필요 (Wave 3 영역) | 🔍 | 사용자 |
| **TD-05** | 🔴 | ✅ | 데이터결함 | ~~`DELETE FROM clients` WHERE 없음~~ → **해결**: `WHERE portal=?` + override 스냅샷도 portal 스코프 | `ClientRepository.replace_clients_preserving_mgmt` | 타 포털 수임처 보호 | 🔍 | 둘 다 |
| **TD-06** | 🟡 | ⬜ | 구조 | MainWindow **1,124줄** + UI↔DB 직결 (raw `sqlite3` + Repository **3종** 직접 호출) | `src/ui/main_window.py:422,522,525,797,810,825-830` | 계층 분리 약화 | 🔍 | 둘 다 |
| **TD-07** | 🟡 | ⬜ | 런타임 | 병렬(Phase 2)이 SQLite 영속상태 미사용 → 체크포인트·재시도 불가 | `src/ui/workers/parallel_cli_worker.py` + `src/automation/_parallel_report.py` | 크래시 시 result_summary 1회성만, 복구 불가 | 🔍 | 분석 |
| **TD-08** | 🟡 | ⬜ | correctness | `Portal` enum에 `COMWEL_EDI` 누락 — 다만 **현재 `Portal()` 호출부 0곳이라 잠재 위험** | `src/batch/models.py:18-33` | 향후 enum 사용 시 ValueError, `display_name` 미표시 | 🔍 | 분석 |
| **TD-09** | 🟡 | ⬜ | 구조 | `auth.py`가 `src.ui.resources.auth_config` 역참조 (utils→ui) | `src/utils/auth.py:18` | 계층 의존 방향 위반 (역방향 간선) | 🔍 | 분석 |
| **TD-10** | 🟡 | ✅ | correctness | ~~포털 필터 없음~~ → **해결**: `mark_crashed_as_recoverable(portal=)` + engine.initialize 전달 | `BatchRepository.mark_crashed_as_recoverable` | 타 포털 running 배치 보호 | 🔍 | 분석 |
| **TD-11** | 🟡 | ⬜ | 빌드 | Qt6 네이티브 DLL 잔존(Multimedia/Qml/Quick/Pdf) — Python 바인딩만 exclude | `build.py:31-50` | 번들 383MB (목표 315MB) | 🔍 | 사용자 |
| **TD-12** | 🟡 | ⬜ | 문서 | 문서 노후/중복 — PRD(MVP), `wehago_automation_guide.md`(폐기 대상), hometax PROGRESS 포트 오기, 사용자 가이드 3종 중복 | 다수 | 신규 작업자 혼란, 포트 오판 | 🔍 | 둘 다 |
| **TD-13** | 🟡 | ⬜ | 구조·문서 | `engine.run()` 프로덕션 데드코드(러너가 인라인 재구현) + `run_single` 시그니처 문서 오기 | `src/batch/engine.py` / `src/workflows/base.py:37-40` | Wave 3 통합 영역, 문서-코드 불일치 | 🔍 | 분석 |
| **TD-14** | 🟢 | ⬜ | 레거시 | `sys.path.insert(0, PROJECT_ROOT)` 남발 (**50+곳**, 패키지 코드 내부 포함) | `_*.py` · `src/automation/*/` · `tests/` | 패키지 정비 시 제거 가능 | 🔍 | 사용자 |
| **TD-15** | 🟢 | ⬜ | 로깅 | `print()` 기반 로깅 (`logging` 미사용) — `engine.py` 26곳 | `src/batch/engine.py` 등 | 파일 로깅/레벨 제어 불가 | 🔍 | 사용자 |
| **TD-16** | 🟢 | ⬜ | 데드코드 | `VerificationDialog` **완전 미사용** + 포털 호스트 dict 중복 (**위치는 runner**) | `src/ui/widgets/settings_dialog.py` · `src/ui/workers/automation_runner.py:746-752,832-838` | 정리 필요 | 🔍 | 사용자 |
| **TD-17** | 🟡 | 🟦 | 데이터결함 | 무스코프 clients DELETE 3경로 — **db+runner list 분기 해결**. main “모두 삭제”는 의도 UX 유지 | `main_window._on_delete_all_clients` | 사용자 확인 후 전체 삭제 (고지 있음) | 🔍 | 분석 |

> 참고(구조 일관성): TD-02·TD-04·TD-05·TD-13·TD-17 은 모두 **러너↔엔진↔DB 실행 경로**에 묶여 있어 Wave 3(`refactoring-handoff`)에서 함께 다루는 것이 효율적이다.

---

## 3. HIGH 상세

### TD-01 — installer_output/ 정합성 ✅ 해결 [빌드] 🔍
- **해결 근거(2026-07-20 v1.0.5 배포로 라이브 확인):** `release.py` 가 **해시를 먼저 계산하고 그 다음 복사**한다.
  - `release.py:34` `INSTALLER = installer_output/원천징수자동화_설치.exe`
  - `release.py:40` `ASSET_NAME = "whta_setup.exe"` (gh CLI/urllib 의 비ASCII 처리 문제 회피)
  - `release.py:118-123` — `size`/`sha256` 를 `INSTALLER` 기준으로 계산 → `version.json` 기록
  - `release.py:158-161` — `--publish` 시 `shutil.copyfile(INSTALLER, upload_file)` 로 **방금 해시한 그 파일**을 ASCII명으로 복사
  - 순서상 해시 대상과 업로드 대상이 동일 바이트임이 구조적으로 보장된다.
- **라이브 확인:** v1.0.5 배포에서 `whta_setup.exe` / `원천징수자동화_설치.exe` / `version.json` 세 곳의 sha256 `86d64528…` 및 size `166036289` 3중 일치 확인.
- **잔여(무해):** `installer_output/원천징수자동화_설치_v1.0.3_20260703.exe` 구파일이 남아 있으나 파이프라인이 참조하지 않음. 정리는 선택.

### TD-02 — `_reset_batch` 매 실행 portal 전체 wipe ✅ 해결 [런타임결함] 🔍
- **해결(2026-07-25):** `_reset_batch` 가 더 이상 portal 전체 DELETE 하지 않음.
  - `running`/`paused` → `mark_crashed_as_recoverable(portal)` 로 crashed 표시만.
  - `completed`/`archived` 배치(+jobs/steps)만 삭제 → 동일 연월 **재실행** 가능.
  - `crashed`/`created` 유지 → `prepare_batch` 복구·재사용 가능.
  - list phase: clients/배치 wipe **no-op** (TD-17).
- **잔여(Wave 3):** runner 인라인 잡 루프 vs `engine.run` 통합·partial step 리셋은 별도(TD-04/13).
- **검증:** `tests/test_batch_portal_scope.py`.

### TD-03 — db.py 1,210줄 과대 + 내부 중복 🔴 [구조] 🔍
- **현상:** `src/batch/db.py` 1,210줄. Repository 4개 — `ClientRepository:293` / `BatchRepository:484` / `JobRepository:691` / `StepRepository:1034`.
- **duration 중복 3곳(바이트 동일 블록):** `:857-863`(job 완료) · `:905-911`(job 갱신) · `:1107-1113`(step 완료)
  ```python
  t1 = _dt.strptime(now, "%Y-%m-%d %H:%M:%S")
  t2 = _dt.strptime(started, "%Y-%m-%d %H:%M:%S")
  duration = (t1 - t2).total_seconds()
  ```
- **카운터 동기화 2방식 혼재:** 증분식 `increment_counts()` `:578-592` + job 완료 경로의 **인라인 중복** `:880-885` ↔ 전량 재계산 `_recalculate_batch_counts()` `:995-1005`(재시도 리셋 경로 `:763` 에서 호출).
- **수정 방향:** `_compute_duration(start, end)` 헬퍼 추출, Repository mixin 또는 분할, 카운터를 한 방식으로 통일. **동작 보존 필수.**

### TD-04 — automation_runner.py 1,239줄 다중 책임 🔴 [구조] 🔍
- **현상:** 한 클래스에 혼재 — 브라우저 생명주기 `_ensure_browser:718`/`_disconnect_browser:485`, 5포털 로그인 대기 `_wait_for_login_nhis:929`/`_nps:977`/`_comwel:1017`/`_hometax:1080`/`_wehago:1139`, 배치 구동 `_handle_run_phase:136-341`, 브라우저 복구 `_handle_browser_disconnect:443-476`/`_try_reuse_browser:812-826`/`_reconnect_page:828-875`, 단발 phase `_handle_refresh_clients:343-441`.
- **수정 방향:** Wave 3 — 브라우저 세션 관리 / 로그인 대기 / 배치 구동 분리. TD-02·TD-13 과 동일 영역이므로 함께.

### TD-05 — `DELETE FROM clients` WHERE 없음 (전 포털 wipe) ✅ 해결 [데이터결함] 🔍
- **해결(2026-07-25):** `replace_clients_preserving_mgmt` 가
  - override 스냅샷: `WHERE management_number != '' AND portal = ?`
  - DELETE: `WHERE portal = ?`
- **검증:** `tests/test_refresh_preserve_mgmt.py::test_refresh_does_not_wipe_other_portal_clients`.

---

## 4. MED 상세

- **TD-06** `src/ui/main_window.py` **1,124줄**. Repository 직접 인스턴스화 `ClientRepository:422,797,810` / `StepRepository:522` / `JobRepository:525` + raw `sqlite3` 블록 `:825-830`. ViewModel/Service 계층 도입으로 UI↔DB 분리. 🔍
  > **정정(2026-07-20):** 이전 판의 "1,077줄 / Repository 4개"는 부정확. 실제 1,124줄이고 `BatchRepository` 는 여기서 쓰이지 않아 **3종**이다.
- **TD-07** 병렬(Phase 2)은 subprocess CLI + `__WTAX_RESULT__` result_summary 1회성 반환만. 두 파일 모두 `sqlite3`/`BatchDB`/Repository 참조 **0건** 확인 → 병렬 크래시 시 재개 불가(직렬 러너 경로와 비대칭). 🔍
  > **정정(2026-07-20):** 현재 병렬은 **3개 CLI**(NPS/NHIS/COMWEL, 포트 9223/9224/9225)다.
- **TD-08** `src/batch/models.py:18-33` `Portal` = WEHAGO/NHIS_EDI/NPS_EDI/HOMETAX. `COMWEL_EDI` 없음. 🔍
  > **정정(2026-07-20) — 두 가지:**
  > ① **"즉시 위험"이 아니다.** 리포 전체에 `Portal(...)` 생성자 호출부가 **0곳**이다(정의부 제외). 모든 포털 디스패치가 평문 문자열 키를 쓴다 → ValueError 는 **잠재 위험**이지 현재 발생하는 버그가 아니다.
  > ② **"1줄 수정"이 아니다.** enum 멤버 추가 + `display_name` 의 `names` dict 에 `"comwel_edi": "근로복지공단 EDI"` 추가로 **최소 2곳**. (`PORTAL_URLS` 는 `src/config.py:38` 에 이미 있음.)
  > `comwel_edi` 문자열 사용처: `src/config.py:38`, `src/workflows/comwel_edi.py:23`, `src/ui/workers/automation_runner.py:749,835,923,1068`, `build.py:176`.
- **TD-09** `src/utils/auth.py:18` → `from src.ui.resources.auth_config import (AUTH_GRACE_PERIOD_DAYS, BETA_EXPIRES, SUPABASE_ANON_KEY, SUPABASE_URL)`. utils 계층이 ui 계층을 역참조(순환 위험). 상수를 `src/config.py` 등 비-UI 위치로 이동. 🔍
- **TD-10** ✅ `mark_crashed_as_recoverable(portal=)` 추가, `engine.initialize` 가 자기 portal 만 전달. 🔍
- **TD-11** `_QT_EXCLUDE_MODULES`(`build.py:31-50`)가 `PySide6.*` **Python 바인딩만** exclude → 네이티브 DLL 잔존 확인: `dist/원천징수자동화/_internal/PySide6/` 에 `Qt6Multimedia.dll`, `Qt6Pdf.dll`, `Qt6Qml*.dll`, `Qt6Quick*.dll`(Quick3D 포함) 존재. 실측 **398,135,505 B (383MB)**, 목표 315MB. PyInstaller exclude 로는 불가 → **post-build DLL 제거 스크립트** 필요. 🔍
- **TD-12** 잔존 문서 정리. 🔍
  > **정정(2026-07-20):** 루트 `PROGRESS.md` 는 **더 이상 없다**(도메인별 중첩본만 존재). 포트 오기의 실제 위치는 `src/automation/hometax/PROGRESS.md:8`(`9222`)과 `wehago_automation_guide.md:197,205,214,1258`. 실제값은 `src/utils/chrome_cdp.py:16` `CDP_PORT=9223`.
  > **`GEMINI.md` 는 포트에 관해선 정확하다** — 상단에 자체 정확성 경고 배너가 있고 "CDP 포트: 9223(9222 사용 금지)"를 명시. 다만 NHIS 섹션 구식은 그대로(문서 자체가 인정).
  > 잔존: `PRD.md`(MVP), `wehago_automation_guide.md`(canvas 전제 — 폐기 대상), 사용자 가이드 3종 중복(`USER_GUIDE.md` / `docs/user-guide.md` / `docs/설치안내서.md`).
- **TD-13** `engine.run()` 프로덕션 데드코드 확인 — 호출부는 `tests/test_engine.py:35,49,64,88,97` **테스트 전용**. 러너 `_handle_run_phase` 가 동일 루프를 `src/ui/workers/automation_runner.py:241-316` 에 인라인 재구현(= `BatchEngine._run_job`/`run` `src/batch/engine.py:181-296` 중복). `tests/test_engine.py:3-4` 주석이 "Wave 3 에서 runner 가 engine.run() 을 호출하게 만들 때 동작 보존" 목적임을 명시 → **테스트는 보존 자산이니 삭제 금지.**
  시그니처 실제값 `src/workflows/base.py:37-40` = `(self, page, context, client_name: str, job_id: int, state: StateManager, **kwargs)`. 오기 위치: `src/batch/engine.py:28` 주석, `src/workflows/base.py:59` docstring(둘 다 `(page, context, job, state_manager)`). 🔍

---

## 5. LOW

- **TD-14** `sys.path.insert(0, PROJECT_ROOT)` **50+곳**. `debug/*.py`, 루트 `_*.py`, `main.py:22`, `release.py:29`, `gui_main.py:103,141`, `scripts/*.py`, `tests/conftest.py` 뿐 아니라 **패키지 코드 내부**(`src/automation/{comwel,hometax,nhis,nps}/*_common*.py`, `*_auto_cdp.py`)에도 존재. 패키지 구조 정비 시 제거. 🔍
- **TD-15** `src/batch/engine.py` 에 `print()` **26곳**, `import logging` 없음. 🔍
  > ⚠ **`src/utils/log.py`(56줄) 의 듀얼패스는 의도적 설계이며 정상 상태 확인됨.** callback 설정 시 `sys.__stdout__` 로만 미러하고 조기 return 하는 구조로, GUI 로그 2배 중복을 막는다. print→logging 마이그레이션 시 **이 파일은 건드리지 말 것**(회귀 이력 있음).
- **TD-16** `src/ui/widgets/settings_dialog.py`(65줄)의 `VerificationDialog` — 리포 전체에 인스턴스화·import **0건**(유일한 언급은 `src/ui/widgets/login_dialog.py:3` 의 주석). **완전 데드코드.** 🔍
  > **정정(2026-07-20):** 포털 호스트 dict 중복의 위치는 `settings_dialog.py` 가 아니라 `src/ui/workers/automation_runner.py:746-752` 와 `:832-838`(동일 블록 2벌).

---

## 6. 신규 항목 상세

### TD-17 — 무스코프 `DELETE FROM clients` 3경로 🟦 부분해결 [데이터결함] 🔍

| 위치 | 트리거 | 상태 |
|---|---|---|
| `replace_clients_preserving_mgmt` | 새로가져오기 | ✅ TD-05 해결 (`WHERE portal=?`) |
| `automation_runner._reset_batch` list phase | (호출 시) | ✅ no-op — clients wipe 제거 |
| `main_window._on_delete_all_clients` | 사용자 '모두 삭제' | ⬜ **의도 UX 유지** (확인 다이얼로그). TD-06 시 Service 계층으로 |

---

---

## 7. 라이브 검증 대기 (위험 게이트 — 부채 아님)

코드상 구현됐으나 실기기/실사이트 미검증 분기. 출하 전 반드시 스모크 필요.

| ID | 항목 | 위치 | 비고 |
|---|---|---|---|
| **LV-1** | NPS 국고지원금 col24 분기 등가 가정(통합엑셀 경로 vs 구 govt 엑셀 //2) | `src/utils/data_merger.py:301-327` | 수식 col10+col16−col24. 마지막 실질 수정 `b5e488b`(2026-06-14) — 이후 라이브 확인 근거 없음 |
| **LV-2** | Defender 무서명 빌드 스모크 1·2단계 (0x800700E1 오탐 회귀) | `build.py:247-` `verify_bundle()` | ⚠ `verify_bundle()` 은 **정적 번들 완전성 검사일 뿐** 실기기 Defender 스모크가 아님. 실기기 게이트는 여전히 수동·미코드화. v1.0.5 도 무서명·무스캔 출하됨. ★소스 보호(Cython) 도입으로 `_internal/src` 에 **.pyd 65개 추가**→"느슨한 네이티브 바이너리" 휴리스틱 표면 증가. 첫 보호 릴리스는 VT+실기기 Defender 풀스캔 필수(`RELEASE.md` 소스 보호 섹션 참조) |
| **LV-3** | EI v3 조정분(adjustment==0 → 0.9% 보존 자동산정) | `src/utils/data_merger.py:330-366` | 🟦 **부분 해소 가능** — `cfb501c`(2026-07-19) 가 라이브 실측으로 부호규칙을 정정했고 docstring 이 이를 명시. 단 `adjustment==0` 분기 자체가 그 테스트에 포함됐는지는 미확인 |
| **LV-4** | 병렬 영속 프로필(빈 프로필 → 보안프로그램 재설치 오탐 해결) | `src/utils/chrome_cdp.py:307-336` | 구현 완료, 라이브 대기. docstring 은 설계 근거만 기술(검증 기록 아님) |
| **LV-5** | 병렬 → WEHAGO 급여자료입력 E2E(공단EDI raw → SWSA 반영) | `src/workflows/wehago_swsa.py:207-227` | 마지막 관련 수정 `594ad22`(2026-07-05)는 버그픽스이지 E2E 확인이 아님. handoff §16.3 권장 |

---

## 8. 권장 실행 순서 (제안)

1. ~~**TD-08**~~ — 우선순위 하향. `Portal()` 호출부가 0곳이라 급하지 않고, 1줄이 아니라 2곳 수정이다. 구조 작업 시 함께.
2. ~~**TD-01**~~ — ✅ 해결됨(2026-07-20).
3. ~~**TD-05 + TD-17 + TD-02 + TD-10**~~ — ✅/🟦 2026-07-25 (옵션 A). 골든 없이도 단위테스트로 고정.
4. **[골든 선행]** Wave 3 골든 스냅샷 기준선 캡처 (TD-04/13 작업 전 권장 — `refactoring-handoff` §2.6)
5. **TD-03 / TD-04 / TD-06 / TD-13** — 구조 분할 (Wave 3/4 정렬, 동작 보존). TD-13 의 `tests/test_engine.py` 는 이 작업의 회귀 기준선이므로 보존.
6. **TD-09** — auth_config 상수 이동 (역참조 해소)
7. **TD-12** — 문서 폐기/병합 정리 (포트 오기 2곳부터: hometax PROGRESS·wehago guide)
8. **TD-11 / TD-14 / TD-15 / TD-16** — LOW 정리. TD-11 은 post-build DLL 제거 스크립트 필요(exclude 로는 불가).
9. **LV-1 ~ LV-5** — 출하 전 라이브 스모크 (부채 아님, 게이트). **LV-2 는 무서명 출하가 계속되는 한 상시 리스크.**

---

## 9. 변경 이력

| 일자 | HEAD | 내용 |
|---|---|---|
| 2026-07-16 | `ad483f8` | 최초 작성 (v1.0.3 기준, TD-01~16 + LV-1~5) |
| 2026-07-20 | `3202b50` | **전 항목 코드 재검증 후 갱신 (v1.0.5 기준)** — 아래 참조 |
| 2026-07-25 | `6484692` | **옵션 A 완료·세션 마무리.** TD-05·TD-10·TD-02 ✅, TD-17 🟦. 커밋 `fix(batch): TD-05/17/02/10…`. 위택스 제출·안전 리팩터(`8d7ad5d`/`d024177`)는 구조 부채 외 완료. **Wave 3(옵션 B) 보류** — 위험·골든 선행은 handoff §0/§3 및 아래 “옵션 B 위험” 참고. |

### 옵션 B (Wave 3) 보류 사유 (2026-07-25)

| 위험 | 설명 |
|------|------|
| 실행 경로 전면 변경 | runner 인라인 잡 루프 → `engine.run(hooks=)` — 전 Phase 영향 |
| 골든 미캡처 | `scripts/capture_golden.py` 기준선 없음 — 동작 보존 객관 검증 불가 |
| 체감 동작 변화 가능 | 크래시 복구·partial step 리셋이 살아나면 “항상 처음부터” UX와 달라질 수 있음 |
| 범위 | `engine.py` + `automation_runner.py`(1300+줄) 훅(stop/pause/page_alive/human_break) |
| 선택건 비대칭 | `start_selected_clients`/NoopStateManager 는 의도적으로 미통합 |
| A와 겹침 | `_reset_batch` / mark_crashed 를 Wave 3 에서 재조정할 수 있음 |

**재개 조건:** Phase 1–3 dry-run 골든 baseline → engine hooks + `tests/test_engine.py` 그린 → runner 교체 → compare + GUI 스모크.

**2026-07-20 갱신 상세** (이력 보존)
- 경로 표기 전면 수정, TD-01 ✅, TD-17 신규, 범례 상태/검증 분리 등.

---

*본 레지스터는 살아있는 문서. 항목 해결 시 **삭제하지 말고** 상태를 `✅ 해결(커밋)`로 바꾸고 §9 변경 이력에 기록할 것.*

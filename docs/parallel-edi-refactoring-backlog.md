# 공단 EDI 병렬 처리 — 리팩토링 백로그

> **목적:** v1.1.4에서 안정화된 공단 EDI 병렬(NPS+NHIS+COMWEL) 코드를 **당장 고치지 않고**,  
> 추후 별도 작업으로 리팩터링할 때 쓸 **단일 백로그**를 고정한다.  
> **코드 변경 없음** — 구조 작업은 별도 PR·별도 요청으로만 진행한다.

| 항목 | 값 |
|------|-----|
| **작성일** | 2026-08-06 |
| **재검증** | 2026-08-19 — v1.1.12 / `6ef206c` 코드 대조. **PE-P0-5 ✅**. 나머지 VALID. 신규 PE 없음 |
| **기준 버전** | `1.1.12` (`src/version.py`) |
| **기준 커밋** | `6ef206c` (재검증 HEAD). 안정화 원점 `deb0791` (v1.1.4) |
| **조사** | 전문 서브에이전트 + 코드 교차 확인 (초안·08-07·08-19 동일 방식) |
| **관련 문서** | [parallel-automation-handoff.md](parallel-automation-handoff.md) §17–§19 · [TECH_DEBT.md](TECH_DEBT.md) TD-06/TD-07/TD-19 |

---

## 1. 현재 아키텍처 (안정화 기준선)

```text
MainWindow
  ├─ ParallelPreflightWorker (선택, HTTPS only · CDP/프로필 미오픈)
  └─ ParallelCliRunner (QThread)
       ├─ bootstrap 순차: NPS → NHIS → COMWEL (--bootstrap-only)
       ├─ 업무 3-way: --auto (포트 9223 / 9224 / 9225)
       ├─ reader Thread → _out_q → drain_events() → Qt Signal
       └─ stop: Event + taskkill /T + kill_chrome_by_port

CLI (nps_auto_cdp / nhis_edi_auto_cdp / comwel_auto_cdp)
  └─ launch → connect → login → ready gate
       → bootstrap marker | run_auto_batch
```

### 1.1 이미 해결됨 — 리팩터로 “다시 열지 말 것” (회귀 테스트 보호)

| 계약 | 위치 / 테스트 |
|------|----------------|
| reader 스레드에서 Qt Signal 직접 emit 금지 | `parallel_cli_worker._pump` / `drain_events` |
| 완료 모달은 QThread 종료 후 | `main_window._deferred_parallel_report` |
| bootstrap 순차 + ready 마커 | `tests/test_parallel_bootstrap.py` |
| 포털 탭 우선 · 보안 `pages[0]` 금지 | `tests/test_edi_portal_pages.py` |
| NHIS `retrieveMain` 우선 · EDI 작업 탭 유지 | `_common_edi.close_popups` |
| 인쇄 버튼 가시 후 인쇄 | `_wait_print_button_ready` |
| 미리보기 URL 확장 | `tests/test_nhis_preview_url.py` |
| firm select 관리번호 digit exact | `_firm_selector.select_firm` |
| firm 전환 MISMATCH 시 해당 수임처 중단 (PE-P0-5) | `nhis_edi_auto_cdp.run_auto_batch` · `tests/test_nhis_parallel_batch.py` |
| 받은문서 `pages_before` 스냅샷 (즉시 열린 웹EDI 탭) | `wait_for_new_tab` · `tests/test_nhis_received_docs_tab.py` |
| 병렬 사전점검이 CDP/프로필을 열지 않음 | `run_parallel_preflight` · `tests/test_parallel_preflight.py` |

---

## 2. 주제별 진단 요약

### 2.1 병렬 CLI / GUI

| 강점 | 잔여 이슈 |
|------|-----------|
| 오케스트레이션 vs UI 분리 명확 | MainWindow에 포트/라벨/start 이중 복사 |
| queue/drain 으로 abort 클래스 차단 | QThread 경로 직접 emit + drain 이중 규약 |
| `lifecycle.log` 로 강제 종료 진단 | 로테이션 없음 · fail-soft만 존재 |
| stop 시 Chrome 포트 정리 | UI unlock 이 `all_finished` 단일 의존 |
| 사전점검이 CDP를 열지 않음 (`afd63c9`) | — |

### 2.2 NHIS / 포털 자동화

| 강점 | 잔여 이슈 |
|------|-----------|
| 행 열기 A–D · 인쇄 다전략으로 라이브 1–2건 통과 | 전략 폭증 · NPS/NHIS 클릭 헬퍼 중복 |
| viewport/DPI 진단 로그 | fallback 받은문서 경로 viewport 누락 등 엣지 |
| firm switch 폴링 + MISMATCH 시 해당 수임처 중단 | — (PE-P0-5 해결) |
| 상수 일부 중앙화 | magic timeout 산재 |

---

## 3. 백로그

### 3.1 P0 — 소규모 · 정확성/UX (추후 최우선)

| ID | 문제 | 왜 | 접근 | 노력 | 위험 |
|----|------|-----|------|------|------|
| **PE-P0-1** | `start()` 가 `is_running` 시 `RuntimeError`; UI `try/except` 없음 | `_on_start`/`_on_selected_run` 에 pre-check 는 있으나, `set_running(True)` 가 `start()` **앞** → 레이스 시 예외 + 테이블 잠금 잔존 가능 | start 직전 재검사 + try/except·statusBar; 또는 start → bool | S | 낮음 |
| **PE-P0-2** | 병렬 정지 시 UI 가 `all_finished` 에만 의존해 unlock | `_on_stop` 은 `stop()` 만; unlock 은 `_on_parallel_finished` 단일 | stop 직후 메시지 + 8–10s watchdog | S–M | 중 |
| **PE-P0-3** | MainWindow 병렬 라이프사이클 자동 테스트 부재 | 사전점검 UI 테스트(`test_parallel_preflight_ui.py`)는 생겼으나 **deferred modal / closeEvent / stop→unlock 미커버** | offscreen Qt 로 시그널·모달·close 계약 | M | 낮음 |
| **PE-P0-4** | 받은문서 **fallback** 경로 viewport 미설정 | 주 경로·`pageLinkPopup1` 성공 탭은 1920×1080; `_open_received_docs_fallback` 은 탭만 반환하고 `_ensure_edi_viewport` 미호출 | 기존 `_ensure_edi_viewport` 를 fallback 성공 탭에 연결(필요 시 export) | S | 낮음 |
| **PE-P0-5** | ~~firm 전환 2차 MISMATCH 후에도 워크플로우 진행~~ → **✅ 해결 (`9c34613`, v1.1.5)** | MISMATCH 시 `skipped` `전환실패` + `continue`. 잘못된 기본 사업장 PDF 방지. 회귀: `test_parallel_batch_stops_firm_when_switch_cannot_be_verified` | — | — | — |
| **PE-P0-6** | 행 상세 대기 `timeout_s=8` vs `PRINT_BUTTON_READY_TIMEOUT_S=20` | `_open_document_row` 전략 A–D 가 상수 무시하고 8s 고정 → 느린 병렬 페인트 false fail | 호출부 상수화(또는 `ROW_DETAIL_READY_TIMEOUT_S` 분리) | S | 낮–중 |

**주요 심볼**

- `src/ui/workers/parallel_cli_worker.py` — `start`, `stop`, `run` finally, `drain_events`
- `src/ui/main_window.py` — `_on_start`, `_on_selected_run`, `_on_stop`, `_on_parallel_finished`, `closeEvent`
- `src/automation/nhis/_doc_access.py` — `_open_received_docs_fallback`
- `src/automation/nhis/_doc_download.py` — `_open_document_row` (timeout 8)
- `src/automation/nhis/nhis_edi_auto_cdp.py` — `run_auto_batch` 전환 검증

### 3.2 P1 — 유지보수성 (라이브 순서·계약 유지)

| ID | 문제 | 왜 | 접근 | 노력 | 위험 |
|----|------|-----|------|------|------|
| **PE-P1-1** | 로그 emit 이중 경로 (reader queue vs QThread 직접 emit) | reader 는 enqueue-only(계약); `run`/`stop` 은 직접 emit → 규약 혼재·`_pump` emit 재도입 위험 | 워커 기원 로그는 전부 enqueue+drain (reader 경로 유지) | M | 중 |
| **PE-P1-2** | 포트/라벨/firms 조립 MainWindow 이중 | `_on_start`·`_on_selected_run` 동일 start kwargs 복제 | `_start_parallel_batch` + `PARALLEL_EDIS` | S | 낮음 |
| **PE-P1-3** | `set_running`(병렬 UI) vs `_automation_active`(직렬) 이중 플래그 | 현재 close/auth/logout/update 는 둘 다 OR — **당장 게이트 누락은 아님**. 이후 단일 플래그만 검사하기 쉬움 | `_any_automation_running()` 단일 헬퍼로 통일 | S | 낮음 |
| **PE-P1-4** | bootstrap 실패 모달 + 종료 메시지 병치 | 실패 early-return 후에도 `finally` 가 `all_finished` emit → `_on_parallel_finished` 가 `[병렬] 실행 종료 — 결과를 정리합니다` + deferred 리포트. `finished_reason` 없음 | `finished_reason` 페이로드 | S–M | 낮–중 |
| **PE-P1-5** | 인쇄 6 + 행 4 + NPS 출력 전략 중복 | 가독성·재시도 비용 (DRY; 라이브 실패 근거는 아님) | 얇은 `try_click_strategies`; **순서 유지** | M | **높음** |
| **PE-P1-6** | bootstrap skeleton 3중 복제 | 마커 계약 드리프트 | `portal_cli_bootstrap(ready_fn)` 골격만 | M | 중 |
| **PE-P1-7** | `connect_page` 3중 유사 | domain+stealth 중복 (COMWEL만 connect 시 viewport) | 파라미터 헬퍼 | S–M | 낮–중 |
| **PE-P1-8** | 1920×1080 리터럴 분산 (NHIS/COMWEL/`chrome_cdp`) | 튜닝 어려움. **NPS 자동화는 현재 viewport 미설정** — 통합·NPS 신규 적용 시 회귀 주의 | 공유 `EDI_VIEWPORT` | S | 낮–중 (NPS 적용 시 중) |
| **PE-P1-9** | 성공 경로 로그 폭주 | 실패 로그 매몰 | 성공 시 최종 전략만; `WTAX_EDI_DEBUG` | S | 낮음 |
| **PE-P1-10** | `_name_match` / switch wait 가 CLI에만 | 단위 테스트 곤란 | `_firm_selector` 근처 + pure unit test | S | 낮음 |
| **PE-P1-11** | lifecycle 로그 무한 append | 장기 실행 디스크 | 2–5MB 로테이션 | S | 낮음 |
| **PE-P1-12** | timeout magic number 산재 | 튜닝 불가 | 포털 `_constants` 이름 부여 | S | 낮음 |

### 3.3 P2 — 대형 / 제품 결정 후

| ID | 문제 | 접근 | 노력 | 위험 |
|----|------|------|------|------|
| **PE-P2-1** | TD-07: 병렬 SQLite 체크포인트 없음 | 포털별 진행 마커 또는 엔진 통합 | L | 높음 |
| **PE-P2-2** | MainWindow god-object | `ParallelAutomationController` | M–L | 중 |
| **PE-P2-3** | Runner = 프로세스+프로토콜+Qt | pure orchestrator + 얇은 QThread | L | 중–높음 |
| **PE-P2-4** | `select_doc_type` 인라인 MouseEvent | `nexacro_click` 재사용 | S | 낮음 |
| **PE-P2-5** | `_trace` NHIS/NPS/**COMWEL** 삼중 복제 | 공통 `debug_trace` | S | 낮음 |
| **PE-P2-6** | Crownix/rdPreview PDF wait/rename 유사 | 공통 `%PDF-` wait (**COMWEL ClipReport 는 분리 유지**) | M | 중 |

---

## 4. 금지구역 (리팩터 PR에서 변경 금지)

라이브·테스트로 고정된 계약이다. “정리” 목적으로 건드리면 회귀 비용이 크다.

1. NHIS 인쇄/행 열기 **전략 순서** (성공 메트릭으로 죽은 전략 증명 전)  
2. `select_firm` 관리번호 digit exact · 첫 행 선택 금지  
3. `_is_preview_url` / `find_preview_tab` 계약  
4. bootstrap 순서 + `BOOTSTRAP_READY_MARKER` + profile ready 파일  
5. `close_popups` EDI 작업 탭 유지 + `retrieveMain` 우선  
6. COMWEL 텍스트 매칭 인쇄 (동적 `wq_uuid`)  
7. `reset_main_page` goto-only (Nexacro wait 금지)  
8. reader → queue → drain 아키텍처 (Signal 재도입 금지)

---

## 5. 권장 착수 순서 (별도 스프린트)

```text
Wave A (1–2일, 저위험)
  PE-P0-1, P0-4, P0-6, P1-2, P1-3, P1-9, P1-11, P1-12

Wave B (테스트·UX)
  PE-P0-2, P0-3, P1-4, P1-10

Wave C (포털 DRY — 라이브 스모크 필수)
  P1-7, P1-8, P1-6
  (PE-P0-5 는 v1.1.5 에서 해결 — 본 Wave에서 제외)

Wave D1 (워커 emit 규약 통일 — 금지구역 8 인접)
  PE-P1-1

Wave D2 (전략 DRY — 성공 전략 메트릭 수집 후)
  PE-P1-5

Wave E (제품 펀딩 시)
  PE-P2-1 ~ P2-3  (+ 여유 시 P2-4 ~ P2-6)
```

**각 Wave 완료 조건**

1. 관련 `pytest` 스위트 통과  
2. **선택건 1~2건** 공단 EDI 병렬 스모크 —  
   `공단EDI_{YYYYMM}/{수임처}/{국민연금|국민건강보험|고용보험}/` 파일 존재

---

## 6. TECH_DEBT 매핑

| 기존 ID | 관계 |
|---------|------|
| **TD-07** | = **PE-P2-1** (병렬 SQLite 미사용) |
| **TD-06** | MainWindow 비대(1,639줄) — **PE-P2-2** 가 병렬 부분 분리 경로 |
| **PE-P0-5** | ✅ v1.1.5. 본 문서 §1.1 계약으로 이관 |
| handoff §17–§19 | 안정화 **이력**; 본 문서는 **후속 구조 작업** |

---

## 7. 핵심 파일 인덱스

| 경로 | 역할 |
|------|------|
| `src/ui/workers/parallel_cli_worker.py` | bootstrap, spawn, queue/drain, stop |
| `src/ui/main_window.py` | 병렬 start/stop/finish/close/bootstrap UI |
| `src/utils/lifecycle_log.py` | lifecycle / heartbeat |
| `src/automation/nhis/_doc_download.py` | 행 열기·인쇄 전략·Crownix PDF |
| `src/automation/nhis/_doc_access.py` | 받은문서·미리보기 URL |
| `src/automation/nhis/_firm_selector.py` | ready gate·사업장 선택 |
| `src/automation/nhis/nhis_edi_auto_cdp.py` | batch·전환 검증·bootstrap |
| `src/automation/nps/*` · `src/automation/comwel/*` | 형제 포털 CLI |
| `src/utils/nexacro.py` | 공유 합성/viewport 클릭 |
| `src/automation/_parallel_report.py` | 마커·요약 |
| `tests/test_parallel_bootstrap.py` · `test_nhis_parallel_batch.py` · `test_parallel_preflight.py` | 계약 테스트 |
| `run_gui.bat` | Job 분리 GUI 기동 |

---

## 8. 재검증 요약 (2026-08-19)

코드(`1.1.12` / `6ef206c`)와 전 항목을 다시 대조했다. 08-07 이후 기능 커밋: `9c34613`(NHIS 탭·전환 실패 전파), `afd63c9`(병렬 사전점검), `47f3722`(NPS 사업장 누락 시 계속), `d68b41a`(COMWEL 팝업 복구). **구조 리팩터는 없음.**

| 판정 | 내용 |
|------|------|
| **종합** | 백로그는 현 코드와 정합. **전면 재작성 불필요.** |
| **PE-P0-5** | **ALREADY_FIXED** — `run_auto_batch` 가 MISMATCH 시 `전환실패` skip. Wave C에서 제외, §1.1 계약으로 이관 |
| **나머지 PE** | P0-1~4·6, P1-1~12, P2-1~6 전부 **VALID(잔존)** |
| **STALE_DETAILS** | P0-3: 사전점검 UI 테스트는 생김(본 갭은 잔존). P1-4: 로그 문구가 `[병렬] 실행 종료 — 결과를 정리합니다` 로 바뀜(병치는 잔존) |
| **§1·§1.1·금지구역** | 아키텍처에 `ParallelPreflightWorker` 추가. 금지구역 8종 그대로. §1.1 에 전환 실패·탭 스냅샷·사전점검 계약 추가 |
| **신규 PE** | 없음. 08-07 이후 커밋은 버그픽스·사전점검이며 새 구조 부채 ID를 만들지 않음 |
| **코드** | 본 문서 갱신만 — 리팩터 미실시 |

---

## 9. 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-08-06 | 초안 — v1.1.4 안정화 직후 서브에이전트 조사 기반. **코드 리팩터 미실시.** |
| 2026-08-07 | 재검증(서브에이전트 2종 + 교차 확인). 문구 정밀화·Wave D1/D2 분리·§8 재검증 요약. 항목 폐기/신규 없음. |
| 2026-08-19 | 재검증(v1.1.12). PE-P0-5 ✅ · §1.1 계약 3건 추가 · Wave C에서 P0-5 제외 · P0-3/P1-4 문구 정밀화. 신규 PE 없음. **코드 리팩터 미실시.** |

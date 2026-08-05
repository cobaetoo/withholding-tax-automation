"""소스 보호: 컴파일된 스테이징 트리의 런타임 등가성 검증.

compile_protected.py 가 만든 build/native/ 스테이징(핵심 4패키지가 .pyd 로
컴파일됨)이 PyInstaller 번들 이전에 실제로 로드·등록되는지 확인한다.
이 게이트가 통과해야 build.py 가 이 스테이징으로 번들을 만든다.

검증 3종 (패키징 게이트 — unit test 와 분리)
------------------------------------------
1. import 전수  : manifest 의 모든 모듈이 import 되고 __file__ 이 .pyd 인가
                  (dev 트리 .py 오염 감지 + dataclass/Enum/async import-time 문제 포착)
2. registry     : 워크플로우 모듈 import 후 @register 데코레이터가 정상 등록했는가
3. 코루틴 스모크 : 컴파일된 async def(human_delay)를 asyncio.run 으로 실제 실행
                  (Cython 코루틴 ↔ asyncio 호환)

★ pytest / tests/ 는 이 스크립트에서 실행하지 않는다.
  회귀 테스트는 소스 트리에서 별도:  python -m pytest tests/
  설치 파일 빌드가 단위 테스트 실패에 막히지 않도록 분리한다.

실패 시 제품 모듈 컴파일/런타임 비호환이면
compile_protected.FALLBACK_EXCLUDE 에 해당 모듈을 추가할 수 있다.
(테스트 기법 불일치 때문에 보호를 약화하지 말 것.)

사용법
------
    python tools/verify_staging.py [staging_dir]
build.py 가 서브프로세스로 호출한다(기본 staging = build/native).
"""

import asyncio
import importlib
import json
import os
import sys

# main_window._load_phases 와 동일한 워크플로우 등록 모듈(레지스트리 채움).
WORKFLOW_MODULES = (
    "src.workflows.wehago_list_clients",
    "src.workflows.nhis_edi",
    "src.workflows.nps_edi",
    "src.workflows.comwel_edi",
    "src.workflows.wehago_swsa",
    "src.workflows.wehago_salary_pdf",
    "src.workflows.wehago_swta",
    "src.workflows.wehago_swer",
    "src.workflows.wehago_jitax_payment",
    "src.workflows.wehago_jitax_efile",
    "src.workflows.hometax",
    "src.workflows.wetax_local_tax",
)


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(msg):
    print(f"[verify_staging] {msg}", flush=True)


def _load_manifest(staging):
    mp = os.path.join(staging, "protected_manifest.json")
    if not os.path.isfile(mp):
        raise SystemExit(f"[FAIL] manifest 없음: {mp} (compile_protected.py 먼저 실행)")
    with open(mp, encoding="utf-8") as f:
        return json.load(f)


def _prime_sys_path(staging):
    """staging 을 최우선 import 경로로 만들고 dev 트리(repo/src)를 밀어낸다."""
    if "src" in sys.modules:
        raise SystemExit("[FAIL] src 가 이미 import 됨 — 격리 위반(검증 프로세스 오염)")
    root = repo_root()
    # repo root 가 경로에 있으면 dev 트리 src(.py)가 우선될 수 있어 제거
    sys.path[:] = [p for p in sys.path
                   if os.path.abspath(p or ".") != os.path.abspath(root)]
    sys.path.insert(0, os.path.abspath(staging))


# ── 검증 1: import 전수 ───────────────────────────────────────────────────────
def check_imports(staging, manifest):
    modules = manifest["modules"]
    bad_missing, bad_notpyd = [], []
    for dotted in sorted(modules):
        try:
            mod = importlib.import_module(dotted)
        except Exception as e:
            bad_missing.append(f"{dotted}: {type(e).__name__}: {e}")
            continue
        f = getattr(mod, "__file__", "") or ""
        if not f.endswith(".pyd"):
            bad_notpyd.append(f"{dotted} → {f}")
    if bad_missing:
        log(f"[FAIL] import 실패 {len(bad_missing)}건:")
        for b in bad_missing[:20]:
            log(f"    {b}")
        return False
    if bad_notpyd:
        log(f"[FAIL] .pyd 아닌 소스에서 로드({len(bad_notpyd)}건 — dev 트리 오염):")
        for b in bad_notpyd[:20]:
            log(f"    {b}")
        return False
    log(f"[OK] import 전수 {len(modules)}개 — 전부 .pyd 로드")
    return True


# ── 검증 2: registry 로딩 ─────────────────────────────────────────────────────
def check_registry():
    try:
        for m in WORKFLOW_MODULES:
            importlib.import_module(m)
        from src.workflows.registry import get_all_phases, get_workflow
    except Exception as e:
        log(f"[FAIL] 워크플로우 모듈 import: {type(e).__name__}: {e}")
        return False
    phases = get_all_phases()
    if not phases:
        log("[FAIL] 등록된 phase 0개")
        return False
    missing = []
    for p in phases:
        pid = p["phase_id"]
        if p.get("is_parallel"):
            continue  # class 없는 병렬 메타데이터
        if get_workflow(pid) is None:
            missing.append(pid)
    if missing:
        log(f"[FAIL] 워크플로우 인스턴스화 실패 phase: {missing}")
        return False
    log(f"[OK] registry — phase {len(phases)}개 등록, 워크플로우 인스턴스화 정상")
    return True


# ── 검증 3: 코루틴 스모크 ─────────────────────────────────────────────────────
def check_coroutine():
    try:
        from src.utils import human
        if not asyncio.iscoroutinefunction(human.human_delay):
            log("[FAIL] human_delay 가 코루틴 함수로 인식되지 않음")
            return False
        asyncio.run(human.human_delay(0.0))  # 즉시 반환 — Cython 코루틴↔asyncio 호환
    except Exception as e:
        log(f"[FAIL] 코루틴 스모크: {type(e).__name__}: {e}")
        return False
    log("[OK] 코루틴 스모크 — 컴파일된 async def 가 asyncio.run 정상 수신")
    return True


def verify(staging=None):
    staging = os.path.abspath(staging or os.path.join(repo_root(), "build", "native"))
    if not os.path.isdir(staging):
        raise SystemExit(f"[FAIL] 스테이징 없음: {staging}")
    manifest = _load_manifest(staging)
    _prime_sys_path(staging)

    ok1 = check_imports(staging, manifest)
    ok2 = check_registry()
    ok3 = check_coroutine()

    passed = ok1 and ok2 and ok3
    log("=" * 50)
    log("스테이징 검증 " + ("전부 통과 ✔" if passed else "실패 ✘")
        + " (import/registry/coroutine — pytest 미실행)")
    return passed


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    staging = argv[0] if argv else None
    return 0 if verify(staging) else 1


if __name__ == "__main__":
    sys.exit(main())

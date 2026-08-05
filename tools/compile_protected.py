"""소스 보호: 핵심 패키지를 Cython 네이티브 확장(.pyd)으로 컴파일.

목적
----
현재 배포물은 `src` 전체가 PyInstaller PYZ 아카이브에 .pyc 로 들어가
pyinstxtractor + 디컴파일러로 소스가 거의 원문 복원된다. 이 스크립트는
영업비밀이 집약된 4개 패키지(automation/batch/utils/workflows)를
build/native/ 스테이징 트리에서 Cython 으로 .pyd 로 컴파일하고 원본 .py 를
물리 삭제한다. 이후 build.py 가 이 스테이징을 기준으로 PyInstaller 를 돌리면
컴파일된 모듈은 PYZ 가 아니라 _internal 하위 느슨한 .pyd 로 수집되어
디컴파일이 사실상 불가능해진다.

핵심 원리 — PyInstaller 에게 선택권을 주지 않는다
--------------------------------------------------
스테이징에서 컴파일 대상의 .py 를 삭제하므로 modulegraph 는 .pyd(EXTENSION)만
발견한다. .py 와 .pyd 로더 우선순위에 의존하지 않고 물리 삭제 + 개수 대조로
강제한다.

컴파일 제외 (순수 .py 유지)
---------------------------
- src/ui/**            : PySide6 QObject 서브클래스(Shiboken 메타클래스)와 충돌
- gui_main.py          : 진입점 부트스트랩(_MEIPASS/resource_path/frozen dispatch)
- src/version.py       : build.py/deploy.sh 가 텍스트 정규식으로 파싱 — 컴파일 금지
- src/config.py        : frozen 경로 분기 부트스트랩
- 모든 __init__.py     : 리스크 대비 이득 없음(패키지 마커)

사용법
------
    python tools/compile_protected.py          # 스테이징 생성 + 컴파일
    python tools/compile_protected.py --check   # 환경(Cython/MSVC) 프로브만

빌드 PC 전제: Visual Studio 2022 Build Tools(VC 워크로드) + Cython>=3.0
build.py 가 이 스크립트를 서브프로세스로 호출하며, 이어서 verify_staging.py 로
import/registry/coroutine 스모크를 검증한다(pytest 는 실행하지 않음).
"""

import json
import os
import shutil
import subprocess
import sys

# ── 경계 정의 (단일 소스 — build.py 는 protected_manifest.json 만 소비) ─────────
PROTECTED_PACKAGES = (
    "src/automation",
    "src/batch",
    "src/utils",
    "src/workflows",
)

# 모든 패키지 공통 제외(파일명 기준)
EXCLUDE_NAMES = frozenset({"__init__.py"})

# 컴파일 실패/런타임 비호환이 확인된 모듈의 상대경로(POSIX 슬래시).
# verify_staging.py 실패 시 여기에 추가하면 해당 모듈만 순수 .py(PYZ 잔류)로 남고
# 나머지는 계속 보호된다. 예: "src/batch/models.py"
FALLBACK_EXCLUDE = frozenset()

STAGING_REL = os.path.join("build", "native")
MANIFEST_NAME = "protected_manifest.json"

# Cython 3 컴파일러 지시어 — 순수 Python 시맨틱 보존이 목표(속도 최적화 아님).
COMPILER_DIRECTIVES = {
    "language_level": "3",
    "annotation_typing": False,  # 타입 애노테이션을 C 타입으로 해석 금지(런타임 동작 보존)
    "binding": True,             # 함수 introspection 보존(Cython3 기본이나 명시)
    "embedsignature": False,
}

# 화이트리스트 복사에 포함할 src 하위 비-.py 런타임 리소스(POSIX 슬래시).
# ★ src 하위에서 런타임이 실제로 읽는 비-.py 파일은 이것뿐(gui_main.py:160 이 유일 소비자).
EXTRA_STAGING_FILES = ("src/ui/resources/style.qss",)


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(msg):
    print(f"[compile_protected] {msg}", flush=True)


def _ensure_program_files_env():
    """setuptools 의 MSVC 자동 탐지를 위한 ProgramFiles env 복구.

    Git Bash(MSYS2) 등 일부 셸은 괄호가 포함된 환경변수 이름(ProgramFiles(x86))을
    자식 프로세스에 전달하지 않는다. 그러면 setuptools._distutils 의 _find_vc2017 이
    vswhere.exe 경로를 조립하지 못해 "Unable to find a compatible Visual Studio
    installation." 로 컴파일이 실패한다. ★deploy.sh 는 Git Bash 에서 release.py→
    build.py→이 스크립트를 subprocess 로 부르므로 이 복구가 없으면 배포 빌드가 깨진다.
    누락 시 표준 경로로 채워 자동 탐지를 복구한다(값 손상 없음 — 없을 때만 설정).
    """
    sysdrive = os.environ.get("SystemDrive", "C:")
    defaults = {
        "ProgramFiles(x86)": sysdrive + r"\Program Files (x86)",
        "ProgramFiles": sysdrive + r"\Program Files",
        "ProgramW6432": sysdrive + r"\Program Files",
    }
    for k, v in defaults.items():
        if not os.environ.get(k) and os.path.isdir(v):
            os.environ[k] = v


def _find_vcvarsall():
    """vswhere 로 VS 설치 경로를 찾아 VC/Auxiliary/Build/vcvarsall.bat 반환(없으면 None)."""
    pf = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
    if not pf:
        return None
    vswhere = os.path.join(pf, "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.isfile(vswhere):
        return None
    try:
        out = subprocess.check_output(
            [vswhere, "-latest", "-prerelease", "-products", "*",
             "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "installationPath"],
            text=True, errors="replace").strip()
    except (subprocess.CalledProcessError, OSError):
        return None
    if not out:
        return None
    vcvarsall = os.path.join(out, "VC", "Auxiliary", "Build", "vcvarsall.bat")
    return vcvarsall if os.path.isfile(vcvarsall) else None


def _load_msvc_env(arch="x64"):
    """MSVC 빌드 환경을 os.environ 에 주입하고 DISTUTILS_USE_SDK=1 을 설정.

    setuptools 의 기본 MSVC 탐지는 `cmd /u /c vcvarsall.bat && set` 출력을
    utf-16le 로 디코드하는데, Git Bash(MSYS2)에서 실행하면 이 출력 인코딩이 깨져
    환경 캡처가 빈 dict 이 되고 "Unable to find a compatible Visual Studio
    installation." 로 실패한다(deploy.sh 는 Git Bash 경유라 직격탄). 이를 우회하기
    위해 vcvarsall 을 직접(문자열형·`/u` 없이·mbcs 디코드) 실행해 INCLUDE/LIB/Path
    등을 os.environ 에 주입하고, DISTUTILS_USE_SDK=1 을 세팅하면 setuptools 는 자체
    캡처를 건너뛰고 이 os.environ 을 그대로 사용한다. PowerShell/cmd 등 정상 셸에서도
    동일하게 안전(멱등).

    반환: 성공 시 True. 이미 dev 환경이면(INCLUDE/LIB 존재) 즉시 True.
    """
    _ensure_program_files_env()
    if os.environ.get("INCLUDE") and os.environ.get("LIB"):
        os.environ["DISTUTILS_USE_SDK"] = "1"
        return True
    vcvarsall = _find_vcvarsall()
    if not vcvarsall:
        log("[WARN] vcvarsall.bat 미발견 — setuptools 기본 탐지에 위임")
        return False
    # 문자열형(정확한 cmd 인용) + /u 없음(mbcs 출력) — Git Bash 인코딩 이슈 회피.
    cmdline = 'cmd /c ""' + vcvarsall + '" ' + arch + ' && set"'
    try:
        p = subprocess.run(cmdline, capture_output=True)
    except OSError as e:
        log(f"[WARN] vcvarsall 실행 실패: {e}")
        return False
    if p.returncode != 0:
        log(f"[WARN] vcvarsall 비정상 종료(rc={p.returncode})")
        return False
    out = p.stdout.decode("mbcs", errors="replace")
    captured = 0
    for line in out.splitlines():
        k, sep, v = line.partition("=")
        if sep and k and " " not in k and v:
            os.environ[k] = v
            captured += 1
    if not (os.environ.get("INCLUDE") and os.environ.get("LIB")):
        log("[WARN] vcvarsall 환경 캡처에 INCLUDE/LIB 없음")
        return False
    os.environ["DISTUTILS_USE_SDK"] = "1"
    log(f"MSVC 환경 로드 완료(vcvarsall {arch}, 변수 {captured}개, DISTUTILS_USE_SDK=1)")
    return True


# ── 단계 0: 환경 프로브 ───────────────────────────────────────────────────────
def check_environment():
    """Cython import + MSVC 로 한 줄짜리 모듈을 실제 컴파일해 툴체인을 검증."""
    try:
        import Cython
        log(f"Cython {Cython.__version__}")
    except ImportError:
        log("[FAIL] Cython 미설치 — pip install \"Cython>=3.0,<3.2\"")
        return False

    _load_msvc_env()
    import tempfile
    probe_dir = tempfile.mkdtemp(prefix="wtax_cython_probe_")
    try:
        probe_py = os.path.join(probe_dir, "_probe.py")
        with open(probe_py, "w", encoding="utf-8") as f:
            f.write("def ping():\n    return 42\n")
        prev = os.getcwd()
        os.chdir(probe_dir)
        try:
            from Cython.Build import cythonize
            from setuptools import setup
            ext = cythonize(["_probe.py"], compiler_directives=COMPILER_DIRECTIVES,
                            quiet=True)
            try:
                setup(script_args=["build_ext", "--inplace"], ext_modules=ext)
            except SystemExit as e:
                if e.code not in (None, 0):
                    raise RuntimeError(f"build_ext exit={e.code}")
            pyd = [f for f in os.listdir(".") if f.startswith("_probe") and f.endswith(".pyd")]
            if not pyd:
                log("[FAIL] .pyd 생성 실패 — MSVC Build Tools(VC 워크로드) 미설치 가능")
                return False
            sys.path.insert(0, probe_dir)
            import importlib
            mod = importlib.import_module("_probe")
            if mod.ping() != 42:
                log("[FAIL] 컴파일된 모듈 동작 이상")
                return False
        finally:
            os.chdir(prev)
        log("[OK] Cython + MSVC 툴체인 정상(probe .pyd import 성공)")
        return True
    except Exception as e:
        log(f"[FAIL] 툴체인 프로브 실패: {e}")
        log("  VS 2022 Build Tools 설치: winget install Microsoft.VisualStudio.2022.BuildTools "
            "--override \"--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended\"")
        return False
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)


# ── 단계 1: 스테이징 생성 ─────────────────────────────────────────────────────
def make_staging(root):
    """build/native 재생성 후 화이트리스트 복사(gui_main.py + src/**/*.py + 리소스)."""
    staging = os.path.join(root, STAGING_REL)
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)

    # gui_main.py (진입점, 컴파일 안 함)
    shutil.copy2(os.path.join(root, "gui_main.py"), os.path.join(staging, "gui_main.py"))

    # src/**/*.py — 트리 보존 복사(.py 만). __pycache__/png/md/xlsx/pdf 자연 배제.
    src_root = os.path.join(root, "src")
    copied = 0
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            abs_src = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_src, root)
            abs_dst = os.path.join(staging, rel)
            os.makedirs(os.path.dirname(abs_dst), exist_ok=True)
            shutil.copy2(abs_src, abs_dst)
            copied += 1

    # 런타임 리소스(style.qss 등)
    for rel in EXTRA_STAGING_FILES:
        abs_src = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(abs_src):
            raise FileNotFoundError(f"필수 스테이징 리소스 누락: {rel}")
        abs_dst = os.path.join(staging, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(abs_dst), exist_ok=True)
        shutil.copy2(abs_src, abs_dst)

    log(f"스테이징 생성: {staging} (.py {copied}개 + 리소스 {len(EXTRA_STAGING_FILES)}개)")
    return staging


# ── 단계 2: 컴파일 대상 수집 ──────────────────────────────────────────────────
def collect_targets(staging):
    """4개 보호 패키지 하위 *.py 중 EXCLUDE/FALLBACK 을 뺀 상대경로(POSIX) 목록."""
    targets = []
    for pkg in PROTECTED_PACKAGES:
        pkg_abs = os.path.join(staging, pkg.replace("/", os.sep))
        for dirpath, dirnames, filenames in os.walk(pkg_abs):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in filenames:
                if not fn.endswith(".py") or fn in EXCLUDE_NAMES:
                    continue
                abs_p = os.path.join(dirpath, fn)
                rel = os.path.relpath(abs_p, staging).replace(os.sep, "/")
                if rel in FALLBACK_EXCLUDE:
                    continue
                targets.append(rel)
    targets.sort()
    log(f"컴파일 대상 {len(targets)}개 수집")
    if FALLBACK_EXCLUDE:
        log(f"[WARN] FALLBACK_EXCLUDE 로 비보호(PYZ 잔류) 처리됨: {sorted(FALLBACK_EXCLUDE)}")
    return targets


# ── 단계 3: 컴파일 전 정적 게이트 ─────────────────────────────────────────────
def lint_targets(staging, targets):
    """모듈 레벨 __getattr__/__dir__(PEP 562, Cython 비호환 리스크) 검출 시 실패."""
    offenders = []
    for rel in targets:
        abs_p = os.path.join(staging, rel.replace("/", os.sep))
        with open(abs_p, encoding="utf-8") as f:
            for line in f:
                s = line.rstrip()
                if s.startswith("def __getattr__(") or s.startswith("def __dir__("):
                    offenders.append(rel)
                    break
    if offenders:
        log("[FAIL] 모듈 레벨 __getattr__/__dir__ 검출(컴파일 전 제거 필요):")
        for o in offenders:
            log(f"    {o}")
        raise SystemExit(3)
    log("정적 게이트 통과(모듈 레벨 __getattr__/__dir__ 없음)")


# ── 단계 4: 컴파일 ────────────────────────────────────────────────────────────
def compile_targets(staging, targets):
    """cwd=staging 에서 cythonize + build_ext --inplace.

    cwd 를 스테이징으로 옮기는 것이 핵심 — Cython 이 __init__.py 를 따라
    dotted 모듈명(src.automation.nps.nps_auto_cdp)을 정확히 추론한다.
    """
    from Cython.Build import cythonize
    from setuptools import setup

    if not _load_msvc_env():
        log("[WARN] MSVC 환경 자동 로드 실패 — setuptools 기본 탐지로 진행(실패 가능)")
    nthreads = os.cpu_count() or 4
    prev = os.getcwd()
    os.chdir(staging)
    try:
        ext_modules = cythonize(
            list(targets),
            compiler_directives=COMPILER_DIRECTIVES,
            nthreads=nthreads,
            annotate=False,   # .html 주석 파일 생성 억제(소스 유출 표면)
            quiet=False,
            force=True,
        )
        try:
            setup(
                script_args=["build_ext", "--inplace", "-j", str(nthreads)],
                ext_modules=ext_modules,
            )
        except SystemExit as e:
            if e.code not in (None, 0):
                raise RuntimeError(f"build_ext 실패 (exit={e.code})")
    finally:
        os.chdir(prev)
    log(f"컴파일 완료(cythonize {len(targets)}개, -j{nthreads})")


# ── 단계 5: 정리 + manifest ───────────────────────────────────────────────────
def _module_name(rel):
    """상대경로(POSIX .py) → dotted 모듈명."""
    return rel[:-3].replace("/", ".")


def cleanup_and_manifest(staging, targets):
    """.pyd rename → 원본 .py/.c/build temp 삭제 → 개수 대조 → manifest 기록."""
    modules = {}
    for rel in targets:
        abs_py = os.path.join(staging, rel.replace("/", os.sep))
        stem = os.path.basename(rel)[:-3]
        d = os.path.dirname(abs_py)

        # {stem}.cp312-win_amd64.pyd → {stem}.pyd
        produced = [f for f in os.listdir(d)
                    if f.startswith(stem + ".") and f.endswith(".pyd")]
        if not produced:
            raise RuntimeError(f"[FAIL] .pyd 미생성: {rel}")
        # 가장 구체적인(플랫폼 태그 포함) 산출물 선택 후 표준 이름으로 rename
        src_pyd = os.path.join(d, produced[0])
        dst_pyd = os.path.join(d, stem + ".pyd")
        if os.path.abspath(src_pyd) != os.path.abspath(dst_pyd):
            if os.path.exists(dst_pyd):
                os.remove(dst_pyd)
            os.replace(src_pyd, dst_pyd)
        # 여분의 플랫폼 태그 .pyd 가 더 있으면 제거
        for extra in produced[1:]:
            ep = os.path.join(d, extra)
            if os.path.exists(ep):
                os.remove(ep)

        # 원본 .py 삭제(디컴파일 표면 제거)
        if os.path.exists(abs_py):
            os.remove(abs_py)
        # 생성된 .c 삭제(원문 소스가 문자열로 박히는 유출물)
        c_file = os.path.join(d, stem + ".c")
        if os.path.exists(c_file):
            os.remove(c_file)
        # 방어적: annotate=False 라 .html 은 없지만 혹시 남으면 제거
        html_file = os.path.join(d, stem + ".html")
        if os.path.exists(html_file):
            os.remove(html_file)

        rel_pyd = os.path.relpath(dst_pyd, staging).replace(os.sep, "/")
        modules[_module_name(rel)] = rel_pyd

    # build_ext 임시 디렉토리 삭제
    build_tmp = os.path.join(staging, "build")
    if os.path.isdir(build_tmp):
        shutil.rmtree(build_tmp, ignore_errors=True)

    # 개수 대조 — 대상 == 생성된 .pyd == manifest 항목
    produced_pyd = sum(
        1
        for pkg in PROTECTED_PACKAGES
        for dp, dn, fns in os.walk(os.path.join(staging, pkg.replace("/", os.sep)))
        for fn in fns
        if fn.endswith(".pyd")
    )
    leftover_py = [
        rel for rel in targets
        if os.path.exists(os.path.join(staging, rel.replace("/", os.sep)))
    ]
    if leftover_py:
        raise RuntimeError(f"[FAIL] 컴파일 대상 .py 잔존: {leftover_py[:5]}")
    if produced_pyd != len(targets) or len(modules) != len(targets):
        raise RuntimeError(
            f"[FAIL] 개수 불일치: targets={len(targets)} "
            f"pyd={produced_pyd} manifest={len(modules)}")

    manifest = {
        "modules": modules,
        "fallback_excluded": sorted(FALLBACK_EXCLUDE),
        "protected_packages": list(PROTECTED_PACKAGES),
    }
    manifest_path = os.path.join(staging, MANIFEST_NAME)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    log(f"정리 완료: .pyd {produced_pyd}개, 컴파일 대상 .py 0개")
    log(f"manifest 기록: {manifest_path}")
    return manifest


def stage_and_compile(root=None):
    """전체 파이프라인. build.py 가 서브프로세스로 호출하거나 단독 실행."""
    root = root or repo_root()
    staging = make_staging(root)
    targets = collect_targets(staging)
    if not targets:
        raise RuntimeError("[FAIL] 컴파일 대상 0개 — 경계 상수 확인")
    lint_targets(staging, targets)
    compile_targets(staging, targets)
    manifest = cleanup_and_manifest(staging, targets)
    return staging, manifest


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--check" in argv:
        return 0 if check_environment() else 1
    try:
        stage_and_compile()
    except (RuntimeError, SystemExit) as e:
        code = e.code if isinstance(e, SystemExit) else 1
        if isinstance(e, RuntimeError):
            log(str(e))
        return code or 1
    log("보호 스테이징 준비 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())

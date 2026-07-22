"""원천징수 자동화 GUI 빌드 스크립트

사용법: python build.py
결과물:
  - dist/원천징수자동화/          (onedir 빌드)
  - installer_output/원천징수자동화_설치.exe  (Inno Setup installer)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request


_local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
ISCC_PATH = os.path.join(_local, "Programs", "Inno Setup 6", "ISCC.exe")
INNO_SETUP_URL = "https://jrsoftware.org/isdl.php"  # 공식 다운로드 페이지


# 앱은 QtWidgets/QtCore/QtGui 만 사용(브라우저 자동화는 Playwright + 시스템 Chrome).
# 그러나 --collect-submodules=PySide6 가 PySide6 전체(Qt6 DLL 595MB, 그중 WebEngine
# ~300MB 포함)을 번들에 끌어온다. 아래 미사용 모듈을 --exclude-module 로 명시 제거하면
# 번들 크기가 859→~315MB 로 줄고, 무엇보다 Defender 휴리스틱 오탐(0x800700E1)의 가장
# 큰 표면인 "대량의 느슨한 네이티브 바이너리"가 크게 감소한다.
# ★변경 시 반드시 verify_bundle() + 실기기 스모크(1·2단계) 로 ImportError/DLL 누락 확인.
_QT_EXCLUDE_MODULES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuickDelegatesQml",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.QtQuickTest", "PySide6.QtQuickTemplates2",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtLocation",
    "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtHttpServer", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSerialBus", "PySide6.QtSerialPort",
    "PySide6.QtVirtualKeyboard", "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtWebView",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtTest",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
]


def read_version():
    """src/version.py 에서 __version__ 파싱 (버전 단일 소스)."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "version.py")
    try:
        with open(p, encoding="utf-8") as f:
            m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', f.read())
        if m:
            return m.group(1)
    except OSError:
        pass
    print("[ERROR] src/version.py 에서 __version__ 을 찾을 수 없습니다.")
    sys.exit(1)


def resolve_iscc():
    """ISCC.exe 경로 해석: 환경변수(ISCC_PATH) → 하드코딩 경로 → PATH(which)."""
    return os.environ.get("ISCC_PATH") or (
        ISCC_PATH if os.path.exists(ISCC_PATH) else (shutil.which("ISCC") or ISCC_PATH)
    )


def find_playwright_driver():
    """Playwright Node.js 드라이버 경로 자동 탐지"""
    import playwright
    driver_dir = os.path.join(os.path.dirname(playwright.__file__), 'driver')
    node_exe = os.path.join(driver_dir, 'node.exe')
    if not os.path.exists(node_exe):
        print(f"[ERROR] Playwright driver를 찾을 수 없습니다: {node_exe}")
        print("  'playwright install'을 먼저 실행하세요.")
        sys.exit(1)
    print(f"[OK] Playwright driver: {driver_dir}")
    return driver_dir


def build_pyinstaller(driver_dir, staging_dir=None):
    """PyInstaller onedir 빌드.

    staging_dir 가 주어지면(보호 빌드) 그 디렉토리를 cwd 로 삼아 실행한다.
    스테이징에는 핵심 4패키지가 .pyd 로 컴파일돼 있고 원본 .py 는 삭제됐으므로
    modulegraph 는 컴파일 모듈을 EXTENSION(.pyd)으로만 발견 → PYZ 가 아니라
    _internal/src/... 하위 느슨한 파일로 수집된다(디컴파일 불가). cwd 이동이
    dev 트리 격리의 핵심 — src 해석이 스테이징으로만 떨어진다.
    --distpath/--workpath 는 repo 절대경로로 고정해 dist 레이아웃·PYZ TOC 경로·
    installer.iss Source·updater 가정을 전부 현행 유지한다.
    """
    repo = os.path.dirname(os.path.abspath(__file__))
    run_cwd = staging_dir or repo
    cmd = [
        sys.executable, "-m", "PyInstaller",

        # 출력 설정
        "--name", "원천징수자동화",
        "--noconfirm",
        "--clean",

        # GUI 모드 (콘솔 창 숨김)
        "--windowed",

        # 압축 없음 (안정성)
        "--noupx",

        # PySide6
        "--hidden-import=PySide6",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--collect-submodules=PySide6",

        # Playwright
        "--hidden-import=playwright",
        "--hidden-import=playwright.async_api",
        "--hidden-import=playwright._impl",
        "--collect-submodules=playwright",

        # playwright-stealth
        # js/ evasion 스크립트(20개)는 .py 가 아닌 데이터 파일이라 --collect-submodules
        # 로는 절대 따라오지 않고, playwright_stealth 용 PyInstaller 훅도 없다.
        # stealth.py 는 모듈 최상위에서 SCRIPTS 딕셔너리를 만들며 그 js 들을 read_text()
        # 하므로, 누락 시 `from playwright_stealth import Stealth` 자체가
        # FileNotFoundError 를 낸다. 그런데 src/utils/stealth.py 의 except Exception 이
        # 이를 삼켜 로그 없이 수동 폴백(navigator.webdriver 한 줄)으로 넘어간다
        # → 빌드/검증은 통과하는데 설치본에서만 스텔스가 조용히 꺼짐(xlrd 사고와 동형).
        "--hidden-import=playwright_stealth",
        "--collect-submodules=playwright_stealth",
        "--collect-data=playwright_stealth",

        # pywinauto + comtypes
        "--hidden-import=comtypes",
        "--hidden-import=comtypes.client",
        "--hidden-import=comtypes.gen",
        "--hidden-import=pywinauto",
        "--hidden-import=pywinauto.backend",
        "--hidden-import=pywinauto.backend.uia_element_info",
        "--hidden-import=pywinauto.backend.uia_wrap",
        "--collect-submodules=comtypes",
        "--collect-submodules=pywinauto",

        # openpyxl
        "--hidden-import=openpyxl",

        # xlrd — 고용보험료지원금정보 .xls(OLE2) 파싱. 함수 내부 import 라 보험으로 명시.
        # (누락 시 고용보험 실업급여 지원금/환수금이 조용히 미반영됨)
        "--hidden-import=xlrd",

        # PDF 파싱 — 함수 내부 import라 PyInstaller 정적 분석이 못 잡음. 명시 수집 필수.
        # (누락 시 런타임 ModuleNotFoundError: No module named 'pdfplumber')
        "--collect-submodules=pdfplumber",
        "--collect-submodules=PyMuPDF",
        "--hidden-import=fitz",
        "--hidden-import=pdfplumber",
        "--hidden-import=pdfminer",
        "--hidden-import=pdfminer.high_level",

        # src 전체 서브모듈 수집 — workflows/automation/utils 하위 동적 import 보장
        "--collect-submodules=src",

        # src 패키지 (워크플로우, 자동화, 유틸)
        "--hidden-import=src",
        "--hidden-import=src.version",
        "--hidden-import=src.utils",
        "--hidden-import=src.utils.updater",
        "--hidden-import=src.utils.auth",
        "--hidden-import=src.ui.workers.update_worker",
        "--hidden-import=src.ui.workers.auth_worker",
        "--hidden-import=src.ui.widgets.login_dialog",
        "--hidden-import=src.ui.resources.auth_config",
        "--hidden-import=src.utils.save_path",
        "--hidden-import=src.utils.chrome_cdp",
        "--hidden-import=src.utils.stealth",
        "--hidden-import=src.utils.log",
        "--hidden-import=src.workflows",
        "--hidden-import=src.workflows.base",
        "--hidden-import=src.workflows.registry",
        "--hidden-import=src.workflows.nps_edi",
        "--hidden-import=src.workflows.nhis_edi",
        "--hidden-import=src.workflows.comwel_edi",
        "--hidden-import=src.batch",
        "--hidden-import=src.batch.engine",
        "--hidden-import=src.batch.state",
        "--hidden-import=src.batch.models",
        "--hidden-import=src.batch.db",
        "--hidden-import=src.automation.nps",
        "--hidden-import=src.automation.nps._common",
        "--hidden-import=src.automation.nps.nps_auto_cdp",
        "--hidden-import=src.automation.nhis",
        "--hidden-import=src.automation.nhis._common_edi",
        "--hidden-import=src.automation.nhis.nhis_edi_auto_cdp",
        "--hidden-import=src.automation.comwel",
        "--hidden-import=src.automation.comwel._common",
        "--hidden-import=src.automation.comwel.comwel_auto_cdp",

        # Playwright Node.js 드라이버 (핵심)
        "--add-data", f"{driver_dir};playwright/driver",

        # UI 리소스
        "--add-data",
        os.path.join("src", "ui", "resources", "style.qss") + ";src/ui/resources",

        # dist/build 는 repo 절대경로로 고정 — cwd 가 스테이징이어도 산출물은 repo 로.
        "--distpath", os.path.join(repo, "dist"),
        "--workpath", os.path.join(repo, "build"),

        # 진입점 (cwd 기준 상대경로 → 스테이징이면 스테이징의 gui_main.py)
        "gui_main.py",
    ]
    # 보호 빌드: 스테이징의 src(.pyd 포함)를 확실히 잡도록 검색경로 명시.
    # collect_submodules 는 pkgutil.iter_modules 기반이라 .pyd 서브모듈도 이름으로 열거.
    if staging_dir:
        cmd += ["--paths", "."]
    # Qt 미사용 모듈 제외 — collect-submodules=PySide6 가 끌어온 Qt6 전체 중
    # 실제 미사용(WebEngine/Qml/Quick/3D/Multimedia/...)을 drop.
    for _mod in _QT_EXCLUDE_MODULES:
        cmd += ["--exclude-module", _mod]

    mode = "보호(Cython .pyd)" if staging_dir else "일반(순수 PYZ)"
    print(f"\n[1/3] PyInstaller onedir 빌드 시작... [{mode}]  cwd={run_cwd}")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=run_cwd)

    if result.returncode != 0:
        print(f"\n[ERROR] PyInstaller 빌드 실패 (exit code: {result.returncode})")
        sys.exit(1)

    exe_path = os.path.join(repo, "dist", "원천징수자동화", "원천징수자동화.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n[OK] PyInstaller 빌드 성공: {exe_path} ({size_mb:.1f} MB)")
    else:
        print("\n[ERROR] 빌드 완료되었으나 exe 파일을 찾을 수 없습니다.")
        sys.exit(1)

    return True


def verify_bundle(protected=False, manifest=None):
    """빌드 결과물의 핵심 의존 포함 여부 검증.

    PyInstaller 6.x onedir 은 두 종류로 나뉜다:
      - 순수-Python 패키지(pdfplumber/openpyxl/pywinauto/comtypes/src.ui/...) →
        exe 에 임베드된 PYZ 아카이브. dist/_internal 에 폴더가 없는 것이 정상.
        → build/원천징수자동화/PYZ-00.toc 에 모듈명이 있는지로 검증.
      - 네이티브 확장/DLL(PyMuPDF _mupdf.pyd, Qt 플러그인, node.exe, sqlite3) →
        dist/_internal 하위 느슨한 파일. 실제 경로로 검증.

    protected=True(소스 보호 빌드)면 핵심 4패키지가 Cython .pyd 로 컴파일돼
    _internal/src/... 하위 느슨한 파일로 들어가고 PYZ 에는 없어야 한다. 따라서:
      (a) manifest 의 모든 모듈이 _internal 에 .pyd 실파일로 존재(양성)
      (b) manifest 의 모든 모듈이 PYZ 에 .pyc 로 남아있지 않음(leak audit, 부정)
    를 추가로 강제한다. manifest 는 compile_protected.py 가 만든 dotted→상대경로 맵.

    "빌드 성공 = 번들 완전"이 아니므로 릴리스 전 필수.
    """
    repo = os.path.dirname(os.path.abspath(__file__))
    internal = os.path.join(repo, "dist", "원천징수자동화", "_internal")
    pyz_toc = os.path.join(repo, "build", "원천징수자동화", "PYZ-00.toc")
    if not os.path.isdir(internal):
        print(f"\n[ERROR] _internal 디렉토리 없음: {internal}")
        sys.exit(1)
    pyz_text = ""
    if os.path.isfile(pyz_toc):
        try:
            with open(pyz_toc, encoding="utf-8") as f:
                pyz_text = f.read()
        except Exception:
            pyz_text = ""
    else:
        print(f"[WARN] PYZ TOC 없음(순수-Python 검증 생략): {pyz_toc}")

    def in_pyz(modname):
        return f"'{modname}'" in pyz_text or f'"{modname}"' in pyz_text

    def pyd_isfile(dotted):
        """보호 모드: manifest 의 dotted 모듈이 _internal 에 .pyd 로 존재하는가."""
        rel = (manifest or {}).get("modules", {}).get(dotted)
        if not rel:
            return False
        return os.path.isfile(os.path.join(internal, rel.replace("/", os.sep)))

    # 보호 모드에서 컴파일 대상인 src.* 대표 모듈은 PYZ 가 아니라 .pyd 로 검증.
    # 일반 모드에서는 종전대로 PYZ 검증.
    def src_present(dotted):
        return pyd_isfile(dotted) if protected else in_pyz(dotted)

    checks = [
        # 순수-Python 패키지 → PYZ TOC 검증 (함수 내부 import 의존 포함)
        ("pdfplumber (PYZ)", lambda: in_pyz("pdfplumber")),
        ("PyMuPDF fitz 쉠 (PYZ)", lambda: in_pyz("fitz")),
        ("openpyxl (PYZ)", lambda: in_pyz("openpyxl")),
        ("pywinauto (PYZ)", lambda: in_pyz("pywinauto")),
        ("comtypes (PYZ)", lambda: in_pyz("comtypes")),
        ("src.utils.raw_data_reader",
         lambda: src_present("src.utils.raw_data_reader")),
        ("src.utils.data_merger",
         lambda: src_present("src.utils.data_merger")),
        # 병렬 자동화 경로 — gui_main --wtax-cli multiplex 가 런타임 import.
        # 누락 시 .exe 병렬 메뉴가 ModuleNotFoundError 로 실패 → 빌드 시 번들 포함 검증.
        # parallel_cli_worker 는 src/ui 소속이라 보호 모드에서도 PYZ 유지.
        ("src.ui.workers.parallel_cli_worker (PYZ)",
         lambda: in_pyz("src.ui.workers.parallel_cli_worker")),
        ("src.automation.nps.nps_auto_cdp",
         lambda: src_present("src.automation.nps.nps_auto_cdp")),
        ("src.automation.nhis.nhis_edi_auto_cdp",
         lambda: src_present("src.automation.nhis.nhis_edi_auto_cdp")),
        ("src.automation.nhis._firm_selector",
         lambda: src_present("src.automation.nhis._firm_selector")),
        ("src.automation.comwel.comwel_auto_cdp",
         lambda: src_present("src.automation.comwel.comwel_auto_cdp")),
        # 네이티브 확장/DLL → _internal 실제 파일 검증
        ("PyMuPDF 네이티브(_mupdf.pyd)",
         lambda: os.path.isfile(os.path.join(internal, "pymupdf", "_mupdf.pyd"))),
        ("PySide6 qwindows 플러그인",
         lambda: os.path.isfile(os.path.join(
             internal, "PySide6", "plugins", "platforms", "qwindows.dll"))),
        # Qt 미사용 모듈 exclude 검증 — WebEngine(~300MB)은 번들에 없어야 정상,
        # QtCore/Gui/Widgets(Qt6Widgets.dll)은 유지되어야 정상.
        ("WebEngine 제외 확인(Qt6WebEngineCore.dll 없음)",
         lambda: not os.path.isfile(os.path.join(
             internal, "PySide6", "Qt6WebEngineCore.dll"))),
        ("필수 Qt 위젯 유지(Qt6Widgets.dll)",
         lambda: os.path.isfile(os.path.join(
             internal, "PySide6", "Qt6Widgets.dll"))),
        ("playwright node 드라이버",
         lambda: os.path.isfile(os.path.join(
             internal, "playwright", "driver", "node.exe"))),
        # playwright_stealth 의 js/ evasion 스크립트 — 데이터 파일이라 PYZ 검증으로는
        # 절대 안 잡힌다(.py 만 PYZ 에 있어 in_pyz 는 green 이 뜨는 사각지대).
        # 반드시 실파일로 확인할 것. 누락 시 설치본에서만 스텔스가 조용히 꺼진다.
        ("playwright_stealth js evasion 리소스",
         lambda: os.path.isfile(os.path.join(
             internal, "playwright_stealth", "js", "evasions",
             "navigator.webdriver.js"))),
        ("sqlite3 dll",
         lambda: os.path.isfile(os.path.join(internal, "sqlite3.dll"))),
        ("VC 런타임",
         lambda: os.path.isfile(os.path.join(internal, "VCRUNTIME140.dll"))),
    ]

    # 보호 빌드: 컴파일 대상 전수에 대해 (a).pyd 존재 + (b)PYZ leak audit.
    if protected:
        mods = sorted((manifest or {}).get("modules", {}))
        if not mods:
            print("\n[ERROR] 보호 빌드인데 manifest 가 비어 있음(컴파일 누락)")
            sys.exit(1)
        missing_pyd = [m for m in mods if not pyd_isfile(m)]
        leaked = [m for m in mods if in_pyz(m)]
        checks.append((
            f"보호 대상 .pyd 전수({len(mods)}개) _internal 존재",
            lambda: not missing_pyd))
        checks.append((
            f"PYZ leak audit — 보호 대상 .pyc 부재({len(mods)}개)",
            lambda: not leaked))

    print("\n[번들 검증]" + ("  [보호(Cython .pyd) 모드]" if protected else ""))
    missing = []
    for name, ok in checks:
        try:
            passed = ok()
        except Exception:
            passed = False
        mark = "[OK]  " if passed else "[FAIL]"
        print(f"  {mark} {name}")
        if not passed:
            missing.append(name)

    if protected:
        if missing_pyd:
            print(f"\n[진단] .pyd 누락 {len(missing_pyd)}건(예): {missing_pyd[:8]}")
        if leaked:
            print(f"\n[진단] PYZ 유출 {len(leaked)}건(예): {leaked[:8]}")
            print("  → 보호 대상 모듈이 PYZ 에 .pyc 로 남음. 소스 유출 위험 — 릴리스 금지.")

    if missing:
        print(f"\n[ERROR] 번들에서 누락/유출된 핵심 의존: {', '.join(missing)}")
        print("  build.py 의 --collect-submodules / --hidden-import / --add-data 또는")
        print("  tools/compile_protected.py 의 컴파일 경계를 점검하세요.")
        sys.exit(1)
    print("  → 모든 핵심 의존 포함 확인" + (" + 보호 leak audit 통과" if protected else "") + "\n")
    return True


def ensure_inno_setup():
    """Inno Setup 설치 확인 — 없으면 winget 또는 직접 다운로드로 설치"""
    if os.path.exists(resolve_iscc()):
        return True

    print("\n[2/3] Inno Setup이 설치되어 있지 않습니다. 자동 설치 중...")

    # 방법 1: winget (Windows 10+ 기본 설치됨)
    try:
        print("  winget으로 설치 시도...")
        result = subprocess.run(
            ["winget", "install", "JRSoftware.InnoSetup",
             "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True, text=True, timeout=180,
        )
        if os.path.exists(ISCC_PATH):
            print("[OK] Inno Setup 설치 완료 (winget)")
            return True
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # 방법 2: 직접 다운로드
    try:
        print("  직접 다운로드로 설치 시도...")
        installer_path = os.path.join(tempfile.gettempdir(), "innosetup-6.exe")
        url = "https://jrsoftware.org/download.php?file=innosetup-6.exe"
        print(f"  다운로드: {url}")
        urllib.request.urlretrieve(url, installer_path)

        print("  설치 중 (관리자 권한 필요)...")
        subprocess.run(
            [installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            timeout=120,
        )

        if os.path.exists(installer_path):
            os.remove(installer_path)

        if os.path.exists(ISCC_PATH):
            print("[OK] Inno Setup 설치 완료")
            return True
    except Exception as e:
        print(f"  [WARN] 자동 설치 실패: {e}")

    print("  수동 설치: https://jrsoftware.org/isdl.php")
    print("  또는: winget install JRSoftware.InnoSetup")
    return False


def build_installer():
    """Inno Setup으로 installer.exe 생성"""
    iss_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "installer.iss"
    )
    if not os.path.exists(iss_path):
        print("\n[WARN] installer.iss 파일이 없습니다. installer 생성을 건너뜁니다.")
        return False

    version = read_version()
    iscc = resolve_iscc()
    print(f"\n[3/3] Inno Setup installer 생성 중... (v{version})")
    result = subprocess.run([iscc, f"/DAppVersion={version}", iss_path])

    if result.returncode != 0:
        print(f"[ERROR] Installer 생성 실패 (exit code: {result.returncode})")
        return False

    installer_path = os.path.join("installer_output", "원천징수자동화_설치.exe")
    if os.path.exists(installer_path):
        size_mb = os.path.getsize(installer_path) / (1024 * 1024)
        print(f"\n{'='*50}")
        print(f"  빌드 완료!")
        print(f"  Installer: {installer_path} ({size_mb:.1f} MB)")
        print(f"{'='*50}")
        return True
    else:
        print("[WARN] Installer 파일을 찾을 수 없습니다.")
        return False


def stage_protected(base_dir):
    """소스 보호 스테이징: compile_protected → verify_staging 순차 실행 후 manifest 반환.

    둘 중 하나라도 실패하면 빌드를 중단한다(부분 성공 번들 금지).
    """
    tools = os.path.join(base_dir, "tools")
    print("\n[0/3] 소스 보호 컴파일(Cython .pyd)...")
    r = subprocess.run([sys.executable, os.path.join(tools, "compile_protected.py")],
                       cwd=base_dir)
    if r.returncode != 0:
        print("\n[ERROR] 소스 보호 컴파일 실패 — 빌드 중단")
        sys.exit(1)

    print("\n[0.5/3] 스테이징 런타임 등가성 검증...")
    r = subprocess.run([sys.executable, os.path.join(tools, "verify_staging.py")],
                       cwd=base_dir)
    if r.returncode != 0:
        print("\n[ERROR] 스테이징 검증 실패 — 빌드 중단")
        sys.exit(1)

    staging = os.path.join(base_dir, "build", "native")
    with open(os.path.join(staging, "protected_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    print(f"[OK] 보호 스테이징 준비: 컴파일 모듈 {len(manifest.get('modules', {}))}개")
    return staging, manifest


def main():
    parser = argparse.ArgumentParser(description="원천징수 자동화 GUI 빌드")
    parser.add_argument(
        "--no-protect", action="store_true",
        help="소스 보호(Cython 컴파일) 없이 순수 PYZ 빌드 — 개발 반복용. "
             "릴리스에는 사용 금지(디컴파일 가능).")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    protected = not args.no_protect
    staging_dir = manifest = None
    if protected:
        staging_dir, manifest = stage_protected(base_dir)
    else:
        print("\n[!] --no-protect: 소스 보호 없이 빌드합니다(릴리스 금지).")

    driver_dir = find_playwright_driver()
    build_pyinstaller(driver_dir, staging_dir=staging_dir)

    # 핵심 의존(pdfplumber/fitz/Qt/node 등) + 보호 모드면 .pyd 전수/leak audit
    verify_bundle(protected=protected, manifest=manifest)

    if ensure_inno_setup():
        build_installer()
    else:
        print("\n" + "="*50)
        print("  PyInstaller 빌드 완료!")
        print(f"  dist/원천징수자동화/원천징수자동화.exe")
        print("  (Inno Setup installer는 생성되지 않음)")
        print("="*50)


if __name__ == "__main__":
    sys.exit(main())

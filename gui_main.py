"""원천징수 자동화 GUI 런처"""

import sys
import os


class _NullWriter:
    """windowed 모드에서 sys.stdout/stderr가 None일 때 대체"""
    def write(self, *args, **kwargs): pass
    def flush(self): pass
    def fileno(self): return -1
    def detach(self):
        import io
        return io.BufferedWriter(io.BytesIO())
    encoding = 'utf-8'


# 모듈 로드 시점에 즉시 교체 — 다른 어떤 import보다 먼저 실행
if sys.stdout is None:
    sys.stdout = _NullWriter()
if sys.stderr is None:
    sys.stderr = _NullWriter()


def resource_path(relative_path):
    """PyInstaller 번들 환경에서 리소스 경로 반환"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


_MUTEX_HANDLE = None


def _hide_owned_console(*, _kernel32=None, _user32=None, argv=None):
    """python.exe 로 뜬 *전용* 콘솔만 숨긴다.

    `start "WTaxGUI" python.exe` 처럼 이 프로세스만을 위해 생긴 검정 창은
    숨기고, 기존 터미널에서 실행한 경우(콘솔에 부모도 붙어 있음)는 그대로 둔다.
    pythonw / frozen windowed 는 콘솔이 없어 no-op.
    --wtax-cli 자식은 stdout 이 필요하므로 건드리지 않는다.

    Returns:
        True if a owned console was hidden.
    """
    if sys.platform != "win32":
        return False
    argv = sys.argv if argv is None else argv
    if "--wtax-cli" in argv:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = _kernel32 or ctypes.windll.kernel32
        user32 = _user32 or ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return False
        proc_ids = (wintypes.DWORD * 16)()
        n = int(kernel32.GetConsoleProcessList(proc_ids, 16))
        if n != 1:
            return False
        user32.ShowWindow(hwnd, 0)  # SW_HIDE
        return True
    except Exception:
        return False


def _create_single_instance_mutex():
    """installer.iss 의 AppMutex 와 일치하는 명명 뮤텍스 생성.

    Inno Setup이 업그레이드/제거 시 실행 중인 인스턴스를 감지해
    파일 잠금 충돌(반쪽 덮어쓰기)을 막을 수 있게 한다.
    핸들은 프로세스 종료 시 자동 해제되도록 일부러 닫지 않는다.

    Returns:
        True  if this process owns a new mutex (or non-Windows / failure → allow run)
        False if another instance already holds the mutex (ERROR_ALREADY_EXISTS)
    """
    global _MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # CreateMutex 직전 LastError 초기화 (이전 API 잔여 183 오인 방지)
        kernel32.SetLastError(0)
        _MUTEX_HANDLE = kernel32.CreateMutexW(
            None, False, "WithholdingTaxAutomation_SingleInstance"
        )
        if not _MUTEX_HANDLE:
            return True  # 생성 실패 시 실행은 허용
        # ERROR_ALREADY_EXISTS = 183 → 다른 인스턴스가 이미 보유
        if kernel32.GetLastError() == 183:
            return False
        return True
    except Exception:
        return True


def _apply_light_palette(app):
    """Windows 다크 모드에서 Fusion 기본 팔레트가 다크가 되어 QMessageBox/
    QDialog/QComboBox 팝업/QToolTip 등이 '검정 바탕 + 검정 글자'로 안 보이는
    것을 방지. 명시적 라이트 팔레트를 강제 적용한다 (style.qss 라이트 테마와 일치).
    메뉴바처럼 위젯별로 고치는 게 아니라 근본(palette)에서 해결."""
    from PySide6.QtGui import QPalette, QColor
    LIGHT_BG = QColor("#ffffff")
    LIGHT_BTN = QColor("#f5f5f5")
    DARK_TEXT = QColor("#1a1a1a")
    GRAY_TEXT = QColor("#999999")
    MID = QColor("#e0e0e0")
    p = QPalette()
    # Active / Inactive / Disabled 전 그룹에 라이트 강제
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        p.setColor(group, QPalette.Window, LIGHT_BG)
        p.setColor(group, QPalette.WindowText, DARK_TEXT if group != QPalette.Disabled else GRAY_TEXT)
        p.setColor(group, QPalette.Base, LIGHT_BG)
        p.setColor(group, QPalette.AlternateBase, QColor("#fafafa"))
        p.setColor(group, QPalette.Text, DARK_TEXT if group != QPalette.Disabled else GRAY_TEXT)
        p.setColor(group, QPalette.Button, LIGHT_BTN)
        p.setColor(group, QPalette.ButtonText, DARK_TEXT if group != QPalette.Disabled else GRAY_TEXT)
        p.setColor(group, QPalette.BrightText, DARK_TEXT)
        p.setColor(group, QPalette.ToolTipBase, QColor("#1e1e1e"))
        p.setColor(group, QPalette.ToolTipText, QColor("#ffffff"))
        p.setColor(group, QPalette.Highlight, QColor("#d0e4f7"))
        p.setColor(group, QPalette.HighlightedText, DARK_TEXT)
        p.setColor(group, QPalette.Light, LIGHT_BG)
        p.setColor(group, QPalette.Midlight, QColor("#f0f0f0"))
        p.setColor(group, QPalette.Mid, MID)
        p.setColor(group, QPalette.Dark, QColor("#aaaaaa"))
        p.setColor(group, QPalette.Shadow, QColor("#666666"))
        p.setColor(group, QPalette.Link, QColor("#0d47a1"))
        p.setColor(group, QPalette.LinkVisited, QColor("#4a148c"))
    p.setColor(QPalette.PlaceholderText, GRAY_TEXT)
    app.setPalette(p)
    # 자식 위젯이 시스템 다크 팔레트를 다시 물려받지 않도록
    app.setStyle("Fusion")


def _dispatch_cli_subprocess() -> bool:
    """병렬 자동화 subprocess 디스패치 (--wtax-cli).

    빌드된 exe(frozen)에서는 `python -m <module>` 모듈 실행이 불가하므로,
    GUI 진입점이 `--wtax-cli <module>` 인자를 받아 해당 CLI 모듈을 대신 실행한다.
    일반 GUI 실행에는 영향 없음(플래그가 없으면 False 반환).
    각 subprocess 는 WTAX_CDP_PORT env 로 포트가 격리된다(parallel_cli_worker 설정).
    """
    argv = sys.argv[1:]
    if "--wtax-cli" not in argv:
        return False

    idx = argv.index("--wtax-cli")
    module = argv[idx + 1] if idx + 1 < len(argv) else ""
    rest = argv[:idx] + argv[idx + 2:]

    # GUI main() 과 동일 환경 보장 (CWD, sys.path) — CLI 가 config/DB/import 를 정상 해석.
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))
    sys.path.insert(0, resource_path("."))

    # ── stdout/stderr 을 utf-8 로 강제 (frozen 병렬 다운로드 교착 근본 차단) ──
    # frozen exe 는 PYTHONUTF8 을 무시해 파이프 stdout 이 한글 Windows 기본값(cp949)
    # 으로 열린다. dev 의 `python -m` 은 모듈을 __main__ 로 실행해 각 CLI 파일 하단의
    # utf-8 재설정 블록이 돌지만, 이 --wtax-cli 는 importlib 로 import 진입이라(__main__
    # 아님) 그 블록을 건너뛴다. 그러면 부모(parallel_cli_worker)의 utf-8 파이프 reader
    # 가 첫 한글 줄에서 UnicodeDecodeError 로 죽고 → 파이프 미배수 → 자식이 버퍼가 찬
    # 시점에 print 에서 블록 → 다운로드가 중간에 교착된다. 자식 진입점인 여기서 강제.
    import io
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, io.UnsupportedOperation):
            pass

    if not module:
        print("[wtax-cli] 실행할 모듈이 없습니다.", file=sys.stderr)
        raise SystemExit(2)

    import argparse
    import asyncio
    import importlib

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--bootstrap-only", action="store_true",
                        help="최초 보안/로그인 준비만 수행")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--firms", type=str, default=None)
    parser.add_argument("--mgmts", type=str, default=None,
                        help="콤마로 구분된 사업장관리번호 (--firms 와 같은 순서)")
    parser.add_argument("--save-site", type=str, default=None,
                        help="저장 최상위 폴더명 오버라이드 (병렬: NHIS/NPS 공통 폴더)")
    args = parser.parse_args(rest)

    try:
        mod = importlib.import_module(module)
        result = asyncio.run(mod.main(args))
    except Exception as e:
        print(f"[wtax-cli] FATAL: {e}", file=sys.stderr)
        raise SystemExit(1)
    if result is False:
        print("[wtax-cli] 작업이 완료되지 않았습니다.", file=sys.stderr)
        raise SystemExit(1)
    return True


# 워치독으로 지역 루프를 빠져나왔을 때 아직 살아있는 UpdateWorker 를 담아두는 곳.
# 실행 중인 QThread 가 GC 되면 "QThread: Destroyed while thread is still running"
# → 프로세스 abort(0xC0000409) 다. 여기 담아 참조를 유지해 GC 를 막는다.
# 이 함수 직후 sys.exit(1) 로 프로세스가 끝나므로 이 정도로 충분하다.
_ORPHANED_WORKERS = []


def _show_expiry_notice():
    """기존 만료 안내 (문구·동작 그대로) — 폴백 경로에서 재사용."""
    from PySide6.QtWidgets import QMessageBox
    from src.ui.resources.auth_config import BETA_EXPIRES

    QMessageBox.critical(
        None, "사용 기간 만료",
        f"베타 사용 기간이 만료되었습니다.\n({BETA_EXPIRES})\n\n"
        "새 버전을 설치해 주세요.",
    )


def _run_expiry_update_gate() -> None:
    """베타 만료 시 '종료 직전' 업데이트 설치 경로를 제공한다.

    만료되면 앱이 sys.exit(1) 로 끝나 버려서, 사용자가 새 버전을 받을 자동 경로가
    전혀 없었다(자동 업데이트는 MainWindow 안에 있는데 거기까지 못 감). 그래서
    게이트 자체에서 버전 확인 → 다운로드 → 무인설치까지 밟아준다.

    ★ 이 함수는 어떤 경우에도 예외를 밖으로 던지지 않는다. 업데이트 로직 결함이
      만료 안내 자체를 막으면 안 되므로, 실패는 모두 기존 안내로 폴백한다.
    """
    try:
        from PySide6.QtWidgets import QMessageBox, QProgressDialog, QPushButton
        from PySide6.QtCore import Qt, QEventLoop, QTimer

        from src.utils import updater
        from src.ui.resources.auth_config import BETA_EXPIRES

        # 개발 모드에서는 설치를 진행하지 않는다 (main_window._apply_update 와 동일 규약).
        if not getattr(sys, "frozen", False):
            _show_expiry_notice()
            return

        from src.ui.workers.update_worker import UpdateWorker

        updater.log_event("trigger: expiry-gate")

        # ── 1) 버전 확인 ────────────────────────────────────────────────
        # 이 게이트는 MainWindow 생성 이전, 즉 app.exec() 가 아직 안 도는 시점에
        # 실행된다. 워커 시그널을 받으려면 이벤트 루프가 필요하므로 QEventLoop
        # 지역 루프로 완료를 기다린다 (nested exec — 여기서만 UI 를 돌린다).
        holder = {"res": None, "done": False}
        worker = UpdateWorker()
        loop = QEventLoop()

        def _on_check(r):
            holder["res"] = r
            holder["done"] = True
            loop.quit()

        def _on_check_failed(_msg):
            holder["done"] = True
            loop.quit()

        # QueuedConnection 을 명시 — 워커 스레드에서 emit 된 시그널을 반드시 메인
        # 스레드 이벤트 루프를 거쳐 배달해, exec() 진입 이전에 quit() 이 직접 호출돼
        # 유실되는(=영영 안 끝나는) 상황을 구조적으로 막는다.
        worker.check_done.connect(_on_check, Qt.QueuedConnection)
        worker.failed.connect(_on_check_failed, Qt.QueuedConnection)

        dlg = QProgressDialog("업데이트 확인 중...", None, 0, 0, None)
        dlg.setWindowTitle("업데이트")
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.show()

        # 워치독(20초) — fetch 의 timeout=6 은 DNS(getaddrinfo) 를 bound 하지 못하고,
        # start() 실패나 run() 이 BaseException 으로 죽으면 시그널이 영영 안 온다.
        # 그러면 취소 버튼도 없는 모달이 영구히 남아 강제 종료 말고는 길이 없으므로
        # 루프에 반드시 하한을 둔다. (lambda 가 loop 참조를 유지 → 조기 GC 방지)
        QTimer.singleShot(20000, lambda: loop.quit())

        worker.start_check()
        loop.exec()
        if not worker.wait(3000):
            _ORPHANED_WORKERS.append(worker)
        dlg.close()

        if not holder["done"]:
            updater.log_event("expiry-gate: check-timeout")
            _show_expiry_notice()
            return

        res = holder["res"]
        if not updater.should_offer_expiry_update(res):
            # 네트워크 불가 / 최신 버전 없음 → 현행 동작 그대로 (안내 후 종료)
            _show_expiry_notice()
            return

        version = str(res.get("version", ""))

        # ── 2) 설치 제안 ────────────────────────────────────────────────
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("사용 기간 만료")
        box.setText(
            f"베타 사용 기간이 만료되었습니다.\n({BETA_EXPIRES})\n\n"
            f"새 버전 v{version} 이 있습니다.\n지금 설치하시겠습니까?\n"
            "(설치 후 프로그램이 다시 실행됩니다.)"
        )
        btn_update = box.addButton("지금 업데이트", QMessageBox.AcceptRole)
        box.addButton("종료", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not btn_update:
            updater.log_event(f"expiry-gate: quit v={version}")
            return

        updater.log_event(f"expiry-gate: accept v={version}")

        # ── 3) 다운로드 ────────────────────────────────────────────────
        try:
            # version.json 의 size 가 비정상 문자열이어도 게이트가 죽으면 안 된다.
            size = int(res.get("size", 0) or 0)
        except (TypeError, ValueError):
            size = 0

        # 다운로드 + 설치 압축해제 여유공간(대략 2배) 확인
        if size and not updater.has_enough_disk(size * 2):
            updater.log_event(f"expiry-gate: fail insufficient-disk need={size * 2}")
            QMessageBox.warning(
                None, "디스크 공간 부족",
                "업데이트에 필요한 디스크 여유 공간이 부족합니다.",
            )
            _show_expiry_notice()   # 어떤 경로로 끝나든 만료 안내는 반드시 보여준다
            return

        state = {"path": None, "canceled": False}
        dl_worker = UpdateWorker()
        dl_loop = QEventLoop()

        prog = QProgressDialog("업데이트 다운로드 중...", "취소", 0, 100, None)
        prog.setWindowTitle("업데이트")
        prog.setWindowModality(Qt.ApplicationModal)
        prog.setMinimumDuration(0)
        prog.setAutoClose(False)
        prog.setAutoReset(False)
        prog.setValue(0)
        # 취소 버튼을 직접 만들어 참조를 쥔다 — 취소 후 '비활성화'만 하기 위해서다.
        # setCancelButton(None) 은 클릭 시그널 처리 도중 그 버튼을 delete 하게 되어 위험.
        cancel_btn = QPushButton("취소")
        prog.setCancelButton(cancel_btn)

        def _on_progress(done, total):
            # 취소 후에는 갱신하지 않는다 — 뒤늦게 도착한 진행률이 '취소 중...'
            # 라벨을 덮어써서 아직 받는 것처럼 보이면 안 된다.
            if state["canceled"]:
                return
            if total > 0:
                pct = min(int(done * 100 / total), 100)
                prog.setValue(pct)
                prog.setLabelText(
                    f"업데이트 다운로드 중... {pct}% "
                    f"({done // (1024 * 1024)}MB / {total // (1024 * 1024)}MB)"
                )

        def _on_cancel():
            # QProgressDialog 는 canceled 시그널과 함께 스스로 hide 한다
            # (setAutoClose/AutoReset(False) 로도 못 막는다). 그런데 워커는 다음
            # 262KB 청크 경계(최악은 30초 소켓 타임아웃)에서야 취소를 알아채므로,
            # 그대로 두면 '창도 없이 멈춘 것 같은' 구간이 생긴다 → 다시 띄운다.
            state["canceled"] = True
            dl_worker.cancel()
            cancel_btn.setEnabled(False)      # 중복 클릭 차단
            prog.setLabelText("취소 중... 잠시만 기다려 주세요.")
            prog.show()

        def _on_done(path):
            state["path"] = path or ""
            dl_loop.quit()

        prog.canceled.connect(_on_cancel)
        # 확인 단계와 같은 이유로 QueuedConnection 명시 (메인 스레드 배달 보장).
        dl_worker.download_progress.connect(_on_progress, Qt.QueuedConnection)
        dl_worker.download_done.connect(_on_done, Qt.QueuedConnection)
        dl_worker.failed.connect(lambda _m: _on_done(""), Qt.QueuedConnection)
        try:
            dl_worker.start_download(res.get("url", ""), size, res.get("sha256", ""))
            dl_loop.exec()
        finally:
            # ★ close() 보다 먼저 끊어야 한다. QProgressDialog 는 closeEvent 에서도
            #   canceled 를 emit 하므로, 연결을 남겨두면 '정상 완료 → prog.close()'
            #   가 _on_cancel 을 불러 state["canceled"] 를 True 로 뒤집는다.
            #   그러면 should_install_downloaded 가 False 가 되어 설치가 영영 안 된다.
            try:
                prog.canceled.disconnect(_on_cancel)
            except (RuntimeError, TypeError):
                pass                      # 이미 끊겼거나 파괴됨 — 무해
            # 어떤 이유로 루프를 빠져나오든 워커를 남기지 않는다 (실행 중 QThread
            # 가 GC 되면 프로세스 abort). 정리 안 되면 참조만 붙들고 넘어간다.
            dl_worker.cancel()
            if not dl_worker.wait(3000):
                _ORPHANED_WORKERS.append(dl_worker)
            prog.close()

        path = state["path"]
        # download_installer 는 마지막 청크 이후(sha256·검증·os.replace)의 취소를
        # 감지하지 못해 정상 경로를 돌려준다 → 취소 플래그를 함께 봐야 한다.
        if not updater.should_install_downloaded(path, state["canceled"]):
            if state["canceled"]:
                updater.log_event(f"expiry-gate: canceled v={version}")
            else:
                QMessageBox.warning(
                    None, "업데이트 실패",
                    "다운로드에 실패했습니다.\n잠시 후 다시 시도해 주세요.",
                )
            _show_expiry_notice()
            return

        # ── 4) 설치 ────────────────────────────────────────────────────
        # 성공 시 추가 안내 없이 반환 — 호출부의 sys.exit(1) 이 즉시 프로세스를
        # 끝내야 exe/_internal 파일 잠금이 풀려 무인설치가 성공한다.
        if not updater.spawn_installer_and_detach(path):
            QMessageBox.warning(
                None, "업데이트 실패", "설치 프로그램을 실행하지 못했습니다.",
            )
            _show_expiry_notice()
        return
    except Exception as e:
        try:
            from src.utils import updater as _u
            _u.log_event(f"expiry-gate: error {e!r}")
        except Exception:
            pass
        try:
            _show_expiry_notice()
        except Exception:
            pass
    finally:
        # 정리 못 한 워커가 남았다면 여기서 프로세스를 끝낸다.
        # _ORPHANED_WORKERS 로 참조를 유지해도 인터프리터 종료(sys.exit → 파이널라이즈)
        # 시점에 래퍼가 파괴되면서 결국 "QThread: Destroyed while thread is still
        # running" → abort(0xC0000409) 로 죽는 것을 헤드리스로 확인했다. 사용자는 이미
        # 만료 안내를 본 뒤이고 어차피 종료(코드 1)이므로, 크래시 대화상자를 띄우느니
        # 파이널라이즈를 건너뛰고 같은 코드로 조용히 끝낸다.
        if _ORPHANED_WORKERS:
            try:
                from src.utils import updater as _u2
                _u2.log_event("expiry-gate: hard-exit (worker still running)")
            except Exception:
                pass
            os._exit(1)


def main():
    # 병렬 자동화 subprocess 디스패치 (frozen exe --wtax-cli) — GUI 없이 CLI 실행 후 종료.
    # 빌드된 exe 에서는 python -m 이 불가해 parallel_cli_worker 가 이 진입점을 경유해 CLI 모듈을 실행.
    if _dispatch_cli_subprocess():
        return

    _hide_owned_console()

    # PyInstaller onefile/onedir 모두: exe 위치를 CWD로
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))

    sys.path.insert(0, resource_path("."))

    # 종료 원인 진단 로그 (traceback 없는 kill 도 heartbeat 단절로 판별)
    try:
        from src.utils.lifecycle_log import log_app_start, log_event, install_qt_message_handler
        log_app_start()
    except Exception:
        log_event = None  # type: ignore
        install_qt_message_handler = None  # type: ignore

    owned_mutex = _create_single_instance_mutex()
    if not owned_mutex:
        # 두 번째 실행: 조용히 종료(사용자는 “켰다 바로 꺼짐”으로 오인). 안내 후 exit.
        try:
            if log_event:
                log_event("app.duplicate_instance")
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication(sys.argv)
            QMessageBox.information(
                None, "원천징수 자동화",
                "이미 실행 중입니다.\n작업 표시줄에서 기존 창을 확인해 주세요.",
            )
        except Exception:
            pass
        sys.exit(0)

    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow
    from src.version import __version__
    from src.config import migrate_legacy_data

    # 구버전 데이터(설치 폴더 내) → %LOCALAPPDATA% 1회 이전 (DB 접근 전에)
    migrate_legacy_data()

    app = QApplication(sys.argv)
    app.setApplicationName("원천징수 자동화")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    _apply_light_palette(app)  # 다크 모드 대비 — 라이트 팔레트 강제
    try:
        if install_qt_message_handler:
            install_qt_message_handler()
    except Exception:
        pass

    # 스타일시트 로드 (QWidget 배경 포함 — 다크모드 검정 배경 방어)
    qss_path = resource_path(os.path.join("src", "ui", "resources", "style.qss"))
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    else:
        # qss 누락 시에도 최소 라이트 테마
        app.setStyleSheet(
            "QWidget { background-color: #ffffff; color: #1a1a1a; "
            "font-family: '맑은 고딕', 'Segoe UI', sans-serif; }"
        )
    # stylesheet 적용 후에도 팔레트 재적용 (Windows 다크 테마 덮어쓰기 방지)
    _apply_light_palette(app)

    # ── 인증 게이트 ────────────────────────────────────────────────────
    from PySide6.QtWidgets import QMessageBox, QDialog

    from src.utils.auth import is_beta_expired, validate_session, is_within_grace_period
    from src.ui.resources.auth_config import BETA_EXPIRES

    # 1) 베타 만료 확인
    if is_beta_expired():
        # 종료 전에 업데이트 설치 기회를 제공 (안내만 하고 끝나면 예전과 동일).
        try:
            if log_event:
                log_event("quit.path", reason="beta_expired")
        except Exception:
            pass
        _run_expiry_update_gate()
        sys.exit(1)

    # 2) 세션 검증 → 유효하면 바로 MainWindow 진입
    session_ok = validate_session()

    if not session_ok and not is_within_grace_period():
        # 3) 유예 기간도 초과 → 로그인 다이얼로그
        from src.ui.widgets.login_dialog import LoginDialog
        login_dlg = LoginDialog()
        if login_dlg.exec() != QDialog.Accepted:
            try:
                if log_event:
                    log_event("quit.path", reason="login_cancelled")
            except Exception:
                pass
            sys.exit(0)

    # ── 메인 윈도우 ────────────────────────────────────────────────────
    window = MainWindow()
    window.show()
    try:
        if log_event:
            log_event("app.main_window_shown")
    except Exception:
        pass

    code = app.exec()
    try:
        if log_event:
            log_event("app.exec_return", code=code)
    except Exception:
        pass
    sys.exit(code)


if __name__ == "__main__":
    main()

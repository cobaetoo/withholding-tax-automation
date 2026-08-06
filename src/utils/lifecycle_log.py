"""앱 생명주기/종료 원인 진단 로그.

실행 중 GUI 가 traceback 없이 사라질 때, 마지막 이벤트로 원인을 분류한다.

  - closeEvent          → 창 닫힘
  - quit.path=…         → 앱이 스스로 종료
  - heartbeat 후 단절   → 외부 킬 / Job / 네이티브 abort
  - faulthandler dump   → 네이티브 크래시

경로는 APP_DATA_DIR/logs/lifecycle.log (dev=repo, frozen=LocalAppData).
어떤 예외도 앱 동작을 막지 않는다.
"""
from __future__ import annotations

import atexit
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

_LOCK = threading.Lock()
_HEARTBEAT_STOP = threading.Event()
_HEARTBEAT_THREAD: threading.Thread | None = None
_STARTED = False


def _log_path() -> str:
    try:
        from src.config import APP_DATA_DIR
        base = APP_DATA_DIR
    except Exception:
        base = os.getcwd()
    return os.path.join(base, "logs", "lifecycle.log")


def log_event(event: str, **fields) -> None:
    """한 줄 lifecycle 이벤트 기록. 실패해도 무시."""
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        parts = [f"ts={ts}", f"pid={os.getpid()}", f"event={event}"]
        for k, v in fields.items():
            if v is None:
                continue
            s = str(v).replace("\n", "\\n").replace("\r", "")
            if len(s) > 400:
                s = s[:400] + "…"
            parts.append(f"{k}={s}")
        line = " ".join(parts) + "\n"
        with _LOCK:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
    except Exception:
        pass


def _heartbeat_loop(interval_s: float = 30.0) -> None:
    while not _HEARTBEAT_STOP.wait(interval_s):
        log_event("heartbeat")


def start_heartbeat(interval_s: float = 30.0) -> None:
    global _HEARTBEAT_THREAD
    if _HEARTBEAT_THREAD is not None and _HEARTBEAT_THREAD.is_alive():
        return
    _HEARTBEAT_STOP.clear()
    t = threading.Thread(
        target=_heartbeat_loop, args=(interval_s,), name="lifecycle-heartbeat",
        daemon=True,
    )
    t.start()
    _HEARTBEAT_THREAD = t


def stop_heartbeat() -> None:
    _HEARTBEAT_STOP.set()


def install_crash_hooks() -> None:
    """faulthandler + sys.excepthook. 중복 설치 안전."""
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    try:
        import faulthandler
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # append mode file kept open for fault dumps
        fh = open(path, "a", encoding="utf-8")
        faulthandler.enable(file=fh, all_threads=True)
    except Exception:
        try:
            import faulthandler
            faulthandler.enable(all_threads=True)
        except Exception:
            pass

    prev_hook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        try:
            log_event(
                "unhandled_exception",
                type=getattr(exc_type, "__name__", str(exc_type)),
                msg=str(exc),
                stack="".join(traceback.format_exception(exc_type, exc, tb))[:1500],
            )
        except Exception:
            pass
        if prev_hook:
            prev_hook(exc_type, exc, tb)

    sys.excepthook = _excepthook

    def _atexit():
        stop_heartbeat()
        log_event("atexit")

    atexit.register(_atexit)


def install_qt_message_handler() -> None:
    """Qt 치명 메시지를 lifecycle 에 남긴다 (가능한 환경에서만)."""
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType
    except Exception:
        return

    def _handler(mode, context, message):
        try:
            name = getattr(mode, "name", str(mode))
            # 잡음 많은 debug 는 생략
            if mode in (QtMsgType.QtDebugMsg, QtMsgType.QtInfoMsg):
                return
            log_event(
                "qt_message",
                level=name,
                msg=message,
                file=getattr(context, "file", None),
                line=getattr(context, "line", None),
            )
        except Exception:
            pass

    try:
        qInstallMessageHandler(_handler)
    except Exception:
        pass


def log_app_start(**extra) -> None:
    install_crash_hooks()
    log_event(
        "app.start",
        frozen=getattr(sys, "frozen", False),
        cwd=os.getcwd(),
        argv=" ".join(sys.argv[:8]),
        python=sys.version.split()[0],
        **extra,
    )
    start_heartbeat()

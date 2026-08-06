"""GUI 병렬 자동화용 subprocess 워커 (QThread).

세 CLI(NPS 9223 / NHIS 9224 / 고용보험 9225)를 WTAX_CDP_PORT env로 백그라운드 실행하고,
stdout 을 폴링해 [NPS]/[NHIS]/[고용] 접두사 로그로 방출한다.
정지는 proc.pid 를 taskkill /T (CLI→Chrome 트리 종료) — kill_chrome(port=) 은
GUI 프로세스의 _launched_pids 가 비어있어(자식 CLI 메모리) 안 통하므로 우회.
"""
import os
import sys
import subprocess
import threading
import time

from PySide6.QtCore import QThread, Signal

from src.automation._parallel_report import BOOTSTRAP_READY_MARKER, RESULT_MARKER
from src.utils.save_path import PARALLEL_SAVE_SITE

# CLI(_emit_summary)가 stdout 으로 찍는 구조화 결과 마커. 이 라인은 log_message 가
# 아니라 result_summary 로 변환되어 로그 패널에 raw JSON 이 노출되지 않는다.
# 세 EDI CLI(NPS/NHIS/COMWEL)의 _RESULT_MARKER와 동일.
_RESULT_MARKER = RESULT_MARKER
_BOOTSTRAP_READY_MARKER = BOOTSTRAP_READY_MARKER

# 병렬 실행 시 NHIS/NPS/고용보험이 같은 최상위 폴더에 저장하도록 두 CLI 에 전달할 저장 폴더명.
# → ~/Desktop/공단EDI_{YYYYMM}/{수임처}/ 안에 건강보험+국민연금+고용보험 자료가 함께 들어감.
# (상수는 src.utils.save_path 에서 import — wehago_swsa 경로 폴백과 단일 소스.)


class ParallelCliRunner(QThread):
    """최초 보안환경은 순차로, 실제 업무는 3-way 병렬로 실행한다.

    새 cdp 프로필에서는 Chrome CDP 포트가 열렸다고 해서 보안모듈/로그인까지
    준비된 것이 아니다. 준비되지 않은 포털만 하나씩 bootstrap하고, 세 포털이
    모두 준비된 뒤에 기존의 세 CLI 업무 배치를 동시에 시작한다.
    """

    log_message = Signal(str)
    finished_one = Signal(str, bool)
    all_finished = Signal()
    result_summary = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._procs = {}
        self._readers = {}
        self._nps_port = 9223
        self._nhis_port = 9224
        self._comwel_port = 9225
        self._request = {}
        self._active = False
        self._stop_requested = threading.Event()
        self._state_lock = threading.RLock()
        self._bootstrap_ready = set()

    def start(self, *, nps_port=9223, nhis_port=9224, comwel_port=9225,
              firms=None, mgmts=None, year=None, month=None):
        """요청만 저장하고 QThread에서 준비→병렬 실행을 시작한다."""
        if self.is_running():
            raise RuntimeError("병렬 자동화가 이미 실행 중입니다.")
        self._nps_port = nps_port
        self._nhis_port = nhis_port
        self._comwel_port = comwel_port
        self._request = {
            "firms": list(firms) if firms else None,
            "mgmts": list(mgmts) if mgmts else None,
            "year": year,
            "month": month,
        }
        with self._state_lock:
            self._procs.clear()
            self._readers.clear()
            self._bootstrap_ready.clear()
            self._stop_requested.clear()
            self._active = True
        super().start()

    def _make_specs(self):
        """포털별 child 실행 정보. 이 순서가 최초 bootstrap 순서다."""
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        pypath = repo_root + os.pathsep + os.environ.get("PYTHONPATH", "")
        enc_env = {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": pypath,
        }
        entries = (
            ("nps", "국민연금(NPS)", "nps", self._nps_port,
             "src.automation.nps.nps_auto_cdp"),
            ("nhis", "건강보험(NHIS)", "nhis", self._nhis_port,
             "src.automation.nhis.nhis_edi_auto_cdp"),
            ("comwel", "고용보험(COMWEL)", "comwel", self._comwel_port,
             "src.automation.comwel.comwel_auto_cdp"),
        )
        return [
            {
                "which": which,
                "label": label,
                "portal": portal,
                "port": port,
                "module": module,
                "env": {**os.environ, "WTAX_CDP_PORT": str(port), **enc_env},
                "cwd": repo_root,
            }
            for which, label, portal, port, module in entries
        ]

    def _spawn(self, spec, *, bootstrap_only=False, clear_fresh_profile=False):
        """한 CLI와 정확히 그 CLI를 읽는 reader thread를 시작한다."""
        module = spec["module"]
        if getattr(sys, "frozen", False):
            args = [sys.executable, "--wtax-cli", module]
        else:
            args = [sys.executable, "-u", "-m", module]
        if bootstrap_only:
            args += ["--bootstrap-only"]
        else:
            args += ["--auto"]
            if self._request.get("year") is not None:
                args += ["--year", str(self._request["year"])]
            if self._request.get("month") is not None:
                args += ["--month", str(self._request["month"])]
            if self._request.get("firms"):
                args += ["--firms", ",".join(self._request["firms"])]
            if self._request.get("mgmts"):
                args += ["--mgmts", ",".join(str(m) for m in self._request["mgmts"])]
            args += ["--save-site", PARALLEL_SAVE_SITE]

        env = dict(spec["env"])
        # fresh profile은 bootstrap 때만 적용한다. 직후 normal child까지 상속되면
        # 방금 준비한 프로필과 ready 마커를 다시 지워 버린다.
        if clear_fresh_profile:
            env.pop("WTAX_FRESH_PROFILE", None)
        kwargs = dict(
            args=args, env=env, cwd=spec["cwd"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
        )
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        with self._state_lock:
            # stop()이 Popen 직전에 들어온 경우 새 child를 만들지 않는다. Popen과
            # 등록을 같은 lock으로 묶어 stop()의 종료 대상 snapshot에서 빠지는
            # child/Chrome이 없게 한다.
            if self._stop_requested.is_set():
                return None
            proc = subprocess.Popen(**kwargs)
            self._procs[spec["which"]] = proc
        reader = threading.Thread(
            target=self._pump, args=(spec["which"], proc), daemon=True,
        )
        reader.start()
        with self._state_lock:
            self._readers[spec["which"]] = reader
        return proc

    def _pump(self, which, proc=None):
        """stdout reader. proc를 캡처해 bootstrap/normal 키 재사용 레이스를 막는다."""
        prefix = {"nps": "[NPS]", "nhis": "[NHIS]", "comwel": "[고용]"}.get(
            which, f"[{which.upper()}]")
        if proc is None:  # 기존 테스트/호출부 호환
            with self._state_lock:
                proc = self._procs.get(which)
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line == _BOOTSTRAP_READY_MARKER:
                    with self._state_lock:
                        self._bootstrap_ready.add(which)
                    self.log_message.emit(f"{prefix} 최초 보안/로그인 준비 완료")
                    continue
                if line.startswith(_RESULT_MARKER):
                    self.result_summary.emit(which, line[len(_RESULT_MARKER):].strip())
                    continue
                self.log_message.emit(f"{prefix} {line}")
        except Exception as e:
            self.log_message.emit(f"{prefix} [reader 예외] {e!r}")

    def _wait_for_process(self, proc):
        """정지 요청도 즉시 반영할 수 있도록 poll 기반으로 기다린다."""
        if proc is None:
            return None
        while proc.poll() is None:
            if self._stop_requested.wait(0.1):
                return None
        return proc.returncode

    def _join_reader(self, which, proc, *, timeout=5.0):
        with self._state_lock:
            reader = self._readers.get(which)
        if reader is not None:
            try:
                reader.join(timeout=timeout)
            except RuntimeError:
                # Thread.start() 직후의 예외 경로에서는 아직 시작되지 않은 reader가
                # 남을 수 있다. child 정리는 계속 진행한다.
                pass
        with self._state_lock:
            if self._procs.get(which) is proc:
                self._procs.pop(which, None)
            if self._readers.get(which) is reader:
                self._readers.pop(which, None)

    @staticmethod
    def _terminate_processes(procs):
        """살아 있는 child CLI와 그 Chrome 트리를 best-effort로 종료한다."""
        for proc in procs:
            try:
                if proc.poll() is not None:
                    continue
            except Exception:
                continue
            try:
                proc.terminate()
            except Exception:
                pass
            if sys.platform == "win32":
                try:
                    if proc.poll() is None:
                        subprocess.run(
                            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5,
                        )
                except Exception:
                    pass

    def _cleanup_child_processes(self):
        """예외·중단 경로에서도 child/reader 추적 상태를 비운다."""
        with self._state_lock:
            children = list(self._procs.items())
        self._terminate_processes(proc for _which, proc in children)

        # GUI 종료 시 reader가 더 이상 Qt signal을 보내지 않도록 총 대기 시간을
        # 제한한 채 drain한다. 정상 완료 시에는 이미 비어 있어 즉시 반환한다.
        deadline = time.monotonic() + 5.0
        for which, proc in children:
            self._join_reader(
                which,
                proc,
                timeout=max(0.0, deadline - time.monotonic()),
            )

    def _kill_port_chromes(self):
        """child 트리 밖에 남은 포트별 Chrome을 종료한다."""
        from src.utils.chrome_cdp import kill_chrome_by_port

        kill_chrome_by_port(self._nps_port)
        kill_chrome_by_port(self._nhis_port)
        kill_chrome_by_port(self._comwel_port)

    def _bootstrap_one(self, spec):
        """한 포털의 신규 프로필을 로그인 가능한 상태까지 순차 준비한다."""
        self.log_message.emit(
            f"[병렬 준비] {spec['label']} 최초 보안환경을 준비합니다. "
            "열린 브라우저에서 로그인해 주세요."
        )
        with self._state_lock:
            self._bootstrap_ready.discard(spec["which"])
        proc = self._spawn(spec, bootstrap_only=True)
        if proc is None:
            return False
        returncode = self._wait_for_process(proc)
        self._join_reader(spec["which"], proc)
        if self._stop_requested.is_set():
            return False

        from src.utils.chrome_cdp import is_parallel_profile_ready
        with self._state_lock:
            marker_seen = spec["which"] in self._bootstrap_ready
        profile_ready = is_parallel_profile_ready(
            spec["port"], portal=spec["portal"], respect_fresh_profile=False,
        )
        if returncode == 0 and marker_seen and profile_ready:
            self.log_message.emit(
                f"[병렬 준비] {spec['label']} 준비 완료. 다음 기관을 준비합니다."
            )
            return True

        self.log_message.emit(
            f"[병렬 준비] {spec['label']} 준비 실패 "
            f"(exit={returncode}, ready-marker={marker_seen}, profile={profile_ready}). "
            "업무 병렬 실행은 시작하지 않았습니다."
        )
        return False

    def run(self):
        """준비되지 않은 포털은 직렬 bootstrap 후 실제 업무만 병렬 시작."""
        normal = []
        normal_completed = False
        try:
            specs = self._make_specs()
            from src.utils.chrome_cdp import is_parallel_profile_ready
            bootstrap_performed = False
            for spec in specs:
                if self._stop_requested.is_set():
                    return
                if is_parallel_profile_ready(spec["port"], portal=spec["portal"]):
                    continue
                bootstrap_performed = True
                if not self._bootstrap_one(spec):
                    return

            if self._stop_requested.is_set():
                return
            self.log_message.emit("[병렬] 보안환경 준비 완료 — 세 기관 업무를 병렬 시작합니다.")
            for spec in specs:
                if self._stop_requested.is_set():
                    return
                proc = self._spawn(
                    spec, clear_fresh_profile=bootstrap_performed,
                )
                if proc is None:
                    return
                normal.append((spec, proc))
            for spec, proc in normal:
                returncode = self._wait_for_process(proc)
                if returncode is None:
                    return
                self.finished_one.emit(spec["which"], returncode == 0)
            # 마지막 결과 마커까지 reader가 처리된 뒤 UI 완료를 알린다.
            for spec, proc in normal:
                self._join_reader(spec["which"], proc)
            normal_completed = True
        except Exception as e:
            self.log_message.emit(f"[병렬] 실행 준비 중 예외: {e!r}")
        finally:
            self._cleanup_child_processes()
            # 정상 완료 때는 다음 실행의 세션 재사용을 위해 Chrome을 남긴다. 반면
            # normal child를 하나라도 띄운 뒤 중단·spawn 예외가 나면 detached Chrome이
            # 남을 수 있으므로 포트 기준으로도 정리한다.
            if normal and not normal_completed:
                self._kill_port_chromes()
            with self._state_lock:
                self._active = False
            self.all_finished.emit()

    def stop(self):
        """bootstrap 또는 업무 child와 포트별 Chrome을 모두 중단한다."""
        self._stop_requested.set()
        self.requestInterruption()
        with self._state_lock:
            procs = list(self._procs.values())
        self._terminate_processes(procs)
        # 재사용/분리(detached) Chrome은 child 트리 밖일 수 있어 포트별로 종료한다.
        self._kill_port_chromes()

    def is_running(self):
        with self._state_lock:
            active = self._active
            procs = list(self._procs.values())
        return active or self.isRunning() or any(p.poll() is None for p in procs)

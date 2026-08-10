"""공단 EDI 병렬 실행 전 읽기 전용 환경 점검.

새 PC에서 병렬 EDI를 시작하기 전에, 앱이 자동으로 확인할 수 있는 범위만
검사한다. 이 모듈은 Chrome을 실행하거나, 프로필/보안모듈/인증서를 수정하지
않는다. 공동인증서와 기관별 업무 권한은 개인정보·권한 영역이므로 별도 안내
항목으로만 남긴다.
"""
from __future__ import annotations

import os
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.config import APP_DATA_DIR, PORTAL_URLS
from src.utils.chrome_cdp import find_chrome, is_parallel_profile_ready
from src.utils.save_path import get_desktop_path


# 병렬 CLI(ParallelCliRunner._make_specs)와 같은 기관/전용 프로필 계약이다.
PARALLEL_PORTALS = (
    {
        "which": "nps",
        "label": "국민연금(NPS)",
        "portal": "nps",
        "port": 9223,
        "url": PORTAL_URLS["nps_edi"],
    },
    {
        "which": "nhis",
        "label": "건강보험(NHIS)",
        "portal": "nhis",
        "port": 9224,
        "url": PORTAL_URLS["nhis_edi"],
    },
    {
        "which": "comwel",
        "label": "고용보험(COMWEL)",
        "portal": "comwel",
        "port": 9225,
        "url": PORTAL_URLS["comwel_edi"],
    },
)

DEBUG_ENV_NAMES = (
    "WTAX_CDP_PORT",
    "WTAX_FRESH_PROFILE",
    "WTAX_SEPARATE_USER_DATA",
)

_MIN_FREE_BYTES = 1 * 1024 * 1024 * 1024


def _item(key: str, label: str, status: str, detail: str) -> dict[str, str]:
    """GUI와 테스트가 공유하는 점검 결과 한 항목."""
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
    }


def probe_portal_connection(url: str, *, timeout: float = 2.0) -> dict[str, str]:
    """로그인하지 않고 포털 HTTPS 접속 가능성만 확인한다.

    HTTP 401/403/405도 목적지 서버까지 도달했다는 뜻이므로 연결 가능으로 간주한다.
    이 검사는 프록시·사내 방화벽 정책 때문에 참고용이며, 실패해도 자동화를 막는
    차단 오류로 취급하지 않는다.
    """
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "WithholdingTaxAutomation-preflight"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {
                "reachable": "true",
                "detail": f"HTTPS 연결 확인됨 (HTTP {response.status}).",
            }
    except urllib.error.HTTPError as exc:
        return {
            "reachable": "true",
            "detail": f"포털 서버 응답 확인됨 (HTTP {exc.code}).",
        }
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = str(getattr(exc, "reason", exc)).strip()
        return {
            "reachable": "false",
            "detail": "HTTPS 연결을 확인하지 못했습니다"
                    + (f" ({reason})" if reason else "")
                    + ". 프록시·방화벽·인터넷 연결을 확인하세요.",
        }


def _is_writable(path: str) -> bool:
    """파일을 만들지 않고 OS가 보고하는 쓰기 권한만 확인한다."""
    return bool(path and os.path.isdir(path) and os.access(path, os.W_OK))


def run_parallel_preflight(
    *,
    chrome_finder: Callable[[], str | None] | None = None,
    profile_ready_checker: Callable[..., bool] | None = None,
    portal_probe: Callable[..., Mapping[str, str]] | None = None,
    desktop_path_getter: Callable[[], str] | None = None,
    app_data_dir: str | None = None,
    env: Mapping[str, str] | None = None,
    disk_usage: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """병렬 EDI의 PC 환경을 읽기 전용으로 검사해 구조화된 결과를 반환한다.

    의존성 주입 인자를 두어 실제 Chrome/포털을 건드리지 않는 단위 테스트가
    가능하다. ``ready``는 *자동화 시작을 막을 차단 오류가 없는지*만 뜻하며,
    warning은 최초 로그인·보안모듈 설치 같은 사용자의 확인이 필요함을 뜻한다.
    """
    chrome_finder = chrome_finder or find_chrome
    profile_ready_checker = profile_ready_checker or is_parallel_profile_ready
    portal_probe = portal_probe or probe_portal_connection
    desktop_path_getter = desktop_path_getter or get_desktop_path
    disk_usage = disk_usage or shutil.disk_usage
    app_data_dir = app_data_dir or APP_DATA_DIR
    env = env if env is not None else os.environ

    checks: list[dict[str, str]] = []

    try:
        chrome_path = chrome_finder()
    except Exception as exc:
        chrome_path = None
        checks.append(_item(
            "chrome", "Google Chrome", "error",
            f"Chrome 확인 중 오류가 발생했습니다: {exc}",
        ))
    else:
        if chrome_path:
            checks.append(_item(
                "chrome", "Google Chrome", "ok",
                f"실행 파일을 찾았습니다: {chrome_path}",
            ))
        else:
            checks.append(_item(
                "chrome", "Google Chrome", "error",
                "Google Chrome을 찾을 수 없습니다. Chrome stable을 설치한 뒤 다시 점검하세요.",
            ))

    # 앱 데이터 폴더는 새 설치에서 아직 없을 수 있다. 만들어 보지 않고 상위 폴더의
    # 쓰기 가능 여부만 판단한다.
    if os.path.isdir(app_data_dir):
        if _is_writable(app_data_dir):
            checks.append(_item(
                "app_data", "병렬 Chrome 프로필 저장 위치", "ok",
                f"앱 데이터 폴더에 쓸 수 있습니다: {app_data_dir}",
            ))
        else:
            checks.append(_item(
                "app_data", "병렬 Chrome 프로필 저장 위치", "error",
                f"앱 데이터 폴더에 쓸 수 없습니다: {app_data_dir}",
            ))
    else:
        parent = os.path.dirname(app_data_dir)
        if _is_writable(parent):
            checks.append(_item(
                "app_data", "병렬 Chrome 프로필 저장 위치", "info",
                f"첫 실행 때 자동 생성될 위치입니다: {app_data_dir}",
            ))
        else:
            checks.append(_item(
                "app_data", "병렬 Chrome 프로필 저장 위치", "error",
                f"앱 데이터 상위 폴더에 쓸 수 없습니다: {parent or app_data_dir}",
            ))

    try:
        desktop = desktop_path_getter()
    except Exception as exc:
        desktop = ""
        checks.append(_item(
            "desktop", "결과 저장 위치", "warning",
            f"바탕화면 경로를 확인하지 못했습니다: {exc}. 앱의 저장 경로 폴백을 사용합니다.",
        ))
    else:
        if _is_writable(desktop):
            checks.append(_item(
                "desktop", "결과 저장 위치", "ok",
                f"바탕화면에 결과를 저장할 수 있습니다: {desktop}",
            ))
        else:
            # 실제 저장 시 문서/홈/LOCALAPPDATA/TEMP 순으로 폴백하므로 차단 오류는 아니다.
            checks.append(_item(
                "desktop", "결과 저장 위치", "warning",
                "바탕화면 쓰기 권한을 확인하지 못했습니다. 실행 시 대체 저장 위치를 사용할 수 있습니다.",
            ))

    # 다운로드·설치·보안모듈 갱신에 필요한 최소 여유 공간 안내. 존재하지 않는
    # app_data_dir 대신 접근 가능한 상위 폴더를 사용한다.
    disk_target = app_data_dir if os.path.isdir(app_data_dir) else os.path.dirname(app_data_dir)
    if not disk_target or not os.path.isdir(disk_target):
        disk_target = desktop
    try:
        free = int(disk_usage(disk_target).free)
    except Exception:
        checks.append(_item(
            "disk_space", "디스크 여유 공간", "info",
            "여유 공간을 확인하지 못했습니다. 설치·결과 저장을 위해 1 GB 이상을 권장합니다.",
        ))
    else:
        free_gib = free / (1024 * 1024 * 1024)
        if free >= _MIN_FREE_BYTES:
            checks.append(_item(
                "disk_space", "디스크 여유 공간", "ok",
                f"여유 공간 {free_gib:.1f} GB를 확인했습니다.",
            ))
        else:
            checks.append(_item(
                "disk_space", "디스크 여유 공간", "warning",
                f"여유 공간이 {free_gib:.1f} GB입니다. 설치·보안모듈·결과 저장을 위해 1 GB 이상을 권장합니다.",
            ))

    active_debug_env = [name for name in DEBUG_ENV_NAMES if str(env.get(name, "")).strip()]
    if active_debug_env:
        checks.append(_item(
            "debug_environment", "병렬 EDI 환경변수", "warning",
            "디버그용 WTAX 환경변수가 설정되어 있습니다: "
            + ", ".join(active_debug_env)
            + ". 지원 안내가 아니라면 제거 후 다시 실행하세요.",
        ))
    else:
        checks.append(_item(
            "debug_environment", "병렬 EDI 환경변수", "ok",
            "수동 WTAX 환경변수가 설정되어 있지 않습니다.",
        ))

    # 준비 마커는 작은 로컬 파일이므로 즉시 순차 확인한다. CDP 포트는 실행할 때
    # 자동화가 열고 검증할 대상이므로, 실행 전 사전점검에서 조회하지 않는다.
    # 포털 HTTPS 확인만 동시에 수행해 대기 시간을 짧게 유지한다.
    profile_checks: dict[str, dict[str, str]] = {}
    for spec in PARALLEL_PORTALS:
        which = spec["which"]
        label = spec["label"]
        port = int(spec["port"])
        try:
            profile_ready = bool(profile_ready_checker(port, portal=spec["portal"]))
        except Exception as exc:
            profile_checks[which] = _item(
                f"{which}_profile", f"{label} 전용 프로필", "warning",
                f"준비 상태를 읽지 못했습니다: {exc}",
            )
        else:
            if profile_ready:
                profile_checks[which] = _item(
                    f"{which}_profile", f"{label} 전용 프로필", "ok",
                    "최초 보안/로그인 준비 마커가 있습니다.",
                )
            else:
                profile_checks[which] = _item(
                    f"{which}_profile", f"{label} 전용 프로필", "warning",
                    "준비 마커가 없습니다. 첫 실행 때 보안모듈 설치와 로그인이 필요합니다.",
                )

    with ThreadPoolExecutor(max_workers=len(PARALLEL_PORTALS)) as executor:
        network_futures = {
            spec["which"]: executor.submit(portal_probe, str(spec["url"]))
            for spec in PARALLEL_PORTALS
        }

        for spec in PARALLEL_PORTALS:
            which = spec["which"]
            label = spec["label"]
            checks.append(profile_checks[which])
            try:
                network = network_futures[which].result()
                reachable = str(network.get("reachable", "false")).lower() == "true"
                network_detail = str(network.get("detail", "포털 접속 상태를 확인하지 못했습니다."))
            except Exception as exc:
                reachable = False
                network_detail = f"포털 접속 확인 중 오류: {exc}"
            checks.append(_item(
                f"{which}_network", f"{label} HTTPS 연결",
                "ok" if reachable else "warning", network_detail,
            ))

    checks.append(_item(
        "manual_auth", "공동인증서·기관 업무 권한", "info",
        "개인 인증서와 기관 권한은 읽지 않습니다. 각 전용 Chrome 창에서 로그인 가능한지 직접 확인하세요.",
    ))

    errors = sum(check["status"] == "error" for check in checks)
    warnings = sum(check["status"] == "warning" for check in checks)
    infos = sum(check["status"] == "info" for check in checks)
    return {
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "ready": errors == 0,
    }

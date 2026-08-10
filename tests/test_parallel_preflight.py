"""공단 EDI 병렬 사전점검의 읽기 전용 판정 회귀 테스트."""
from __future__ import annotations

from types import SimpleNamespace

from src.utils.parallel_preflight import PARALLEL_PORTALS, run_parallel_preflight


def _checks_by_key(report):
    return {item["key"]: item for item in report["checks"]}


def _run(tmp_path, *, chrome_path="C:/Program Files/Google/Chrome/Application/chrome.exe",
         ready_by_port=None, network_ok=True, env=None, free_gib=5):
    """외부 Chrome/포털에 접근하지 않는 공통 테스트 호출."""
    ready_by_port = ready_by_port or {9223: True, 9224: True, 9225: True}
    app_data = tmp_path / "new-app-data"  # 호출 뒤에도 없어야 한다(읽기 전용 계약).

    return run_parallel_preflight(
        chrome_finder=lambda: chrome_path,
        profile_ready_checker=lambda port, **_kwargs: ready_by_port[port],
        portal_probe=lambda _url: {
            "reachable": "true" if network_ok else "false",
            "detail": "연결됨" if network_ok else "연결 실패",
        },
        desktop_path_getter=lambda: str(tmp_path),
        app_data_dir=str(app_data),
        env=env or {},
        disk_usage=lambda _path: SimpleNamespace(free=free_gib * 1024 ** 3),
    )


def test_clean_first_run_environment_is_nonblocking_and_does_not_create_profile_dir(tmp_path):
    """새 앱 데이터 폴더는 정상 최초 실행 상태이며 사전점검은 아무것도 만들지 않는다."""
    app_data = tmp_path / "new-app-data"
    report = _run(tmp_path)
    checks = _checks_by_key(report)

    assert report["ready"] is True
    assert report["errors"] == 0
    assert report["warnings"] == 0
    assert checks["app_data"]["status"] == "info"
    assert not any(key.endswith("_cdp") for key in checks)
    assert all("port " not in item["detail"].lower() for item in checks.values())
    assert not app_data.exists()  # ★ 점검은 폴더/프로필을 만들지 않는다.


def test_missing_chrome_is_blocking_error_but_debug_environment_is_warning(tmp_path):
    """실행 전 차단은 실제 선행조건(Chrome)만 대상으로 한다."""
    report = _run(
        tmp_path,
        chrome_path=None,
        env={"WTAX_FRESH_PROFILE": "1"},
    )
    checks = _checks_by_key(report)

    assert report["ready"] is False
    assert checks["chrome"]["status"] == "error"
    assert checks["debug_environment"]["status"] == "warning"
    assert report["errors"] == 1


def test_first_run_profile_and_network_warning_do_not_hide_actionable_setup(tmp_path):
    """준비 마커 부재/네트워크 미확인은 경고로 보이되, 차단 오류와 구분한다."""
    report = _run(
        tmp_path,
        ready_by_port={9223: True, 9224: False, 9225: True},
        network_ok=False,
    )
    checks = _checks_by_key(report)

    assert report["ready"] is True
    assert checks["nhis_profile"]["status"] == "warning"
    assert "첫 실행" in checks["nhis_profile"]["detail"]
    for spec in PARALLEL_PORTALS:
        assert checks[f"{spec['which']}_network"]["status"] == "warning"
    # 1개 프로필 + 세 기관 네트워크 = 사용자가 볼 확인 항목 4개.
    assert report["warnings"] == 4


def test_low_disk_space_is_warning_not_implicit_write_attempt(tmp_path):
    """용량 권고는 보여 주되, 사전점검이 디스크 상태를 변경하지 않는다."""
    report = _run(tmp_path, free_gib=0)
    checks = _checks_by_key(report)

    assert report["ready"] is True
    assert checks["disk_space"]["status"] == "warning"
    assert "1 GB" in checks["disk_space"]["detail"]


def test_preflight_never_calls_cdp_ports_before_parallel_run(tmp_path):
    """실행 전 포트는 자동화가 열 대상이므로 사전점검 결과에 넣지 않는다."""
    report = _run(tmp_path)
    assert all(not item["key"].endswith("_cdp") for item in report["checks"])

"""병렬 진단 trace 로그 위치 회귀 테스트.

frozen 실행은 gui_main 이 CWD 를 설치 폴더로 바꾼다. trace 를 상대경로 "debug/" 에
쓰면 설치 폴더 안에 Inno Setup 이 모르는 폴더가 생겨 프로그램 제거 후에도 남는다.
세 병렬 CLI 의 trace 는 APP_DATA_DIR 하위 DEBUG_DIR 에 고정돼야 한다.
"""
import importlib
import os

import pytest

from src import config

_CLI_MODULES = [
    "src.automation.nhis.nhis_edi_auto_cdp",
    "src.automation.nps.nps_auto_cdp",
    "src.automation.comwel.comwel_auto_cdp",
]


def test_debug_dir_lives_under_app_data_dir():
    assert config.DEBUG_DIR == os.path.join(config.APP_DATA_DIR, "debug")


@pytest.mark.parametrize("module_name", _CLI_MODULES)
def test_trace_path_uses_debug_dir(module_name):
    module = importlib.import_module(module_name)

    assert os.path.dirname(module._TRACE_PATH) == config.DEBUG_DIR


@pytest.mark.parametrize("module_name", _CLI_MODULES)
def test_trace_does_not_create_debug_folder_in_cwd(module_name, monkeypatch, tmp_path):
    module = importlib.import_module(module_name)
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    debug_dir = tmp_path / "app-data" / "debug"
    monkeypatch.chdir(install_dir)  # frozen 실행: CWD = 설치 폴더
    monkeypatch.setattr(module, "DEBUG_DIR", str(debug_dir))
    monkeypatch.setattr(module, "_TRACE_PATH", str(debug_dir / "trace.log"))

    module._trace("probe")

    assert (debug_dir / "trace.log").read_text(encoding="utf-8") == "probe\n"
    assert not (install_dir / "debug").exists()

"""베타 만료 게이트의 업데이트 제안 판정(should_offer_expiry_update) 테스트.

만료 상태에서는 업데이트가 앱을 다시 쓸 수 있는 **유일한 경로**이므로, 일반
프롬프트(should_prompt)와 달리 '이 버전 건너뛰기'(skip_version) / 세션 '나중에'
(deferred) 이력을 의도적으로 무시해야 한다. 동시에 url/sha256 이 없어
validate_installer 가 어차피 거부할 결과로는 사용자를 다운로드시키지 않는다.

네트워크/실제 파일시스템 접근 없음 — 전부 monkeypatch/tmp_path.
"""
import pytest

from src.utils import updater


def _res(**over) -> dict:
    """정상적으로 제안 가능한 판정 결과 기본형."""
    base = {
        "action": "optional",
        "version": "9.9.9",
        "url": "https://github.com/o/r/releases/download/v9.9.9/setup.exe",
        "size": 1234,
        "sha256": "a" * 64,
        "notes": "",
    }
    base.update(over)
    return base


@pytest.fixture
def prefs_in_tmp(monkeypatch, tmp_path):
    """_PREFS_PATH 를 tmp 로 격리 — 실제 사용자 환경설정을 건드리지 않는다."""
    prefs = tmp_path / "update_prefs.json"
    monkeypatch.setattr(updater, "_PREFS_PATH", str(prefs))
    monkeypatch.setattr(updater, "APP_DATA_DIR", str(tmp_path))
    return prefs


@pytest.fixture
def log_in_tmp(monkeypatch, tmp_path):
    """update.log 기록 경로를 tmp 로 격리 (check() 경유 테스트용)."""
    monkeypatch.setattr(updater, "_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(updater, "_LOG_PATH", str(tmp_path / "logs" / "update.log"))


# ── 제안해야 하는 경우 ──

def test_optional_with_url_and_sha_offers():
    """선택 업데이트라도 만료 게이트에서는 제안한다 — 만료 해제 경로가 이것뿐이므로."""
    assert updater.should_offer_expiry_update(_res(action="optional")) is True


def test_mandatory_with_url_and_sha_offers():
    """필수 업데이트는 당연히 제안한다."""
    assert updater.should_offer_expiry_update(_res(action="mandatory")) is True


# ── action 게이트 ──

def test_action_none_does_not_offer():
    """최신 버전(action='none')이면 설치할 것이 없으므로 제안하지 않는다."""
    assert updater.should_offer_expiry_update(_res(action="none")) is False


def test_action_missing_does_not_offer():
    """action 키가 아예 없는 결과는 신뢰할 수 없으므로 제안하지 않는다."""
    res = _res()
    del res["action"]
    assert updater.should_offer_expiry_update(res) is False


@pytest.mark.parametrize("action", ["", None, "OPTIONAL", "unknown", 0])
def test_unknown_action_values_do_not_offer(action):
    """알 수 없는/빈/대소문자 다른 action 값은 화이트리스트 밖이므로 제안하지 않는다."""
    assert updater.should_offer_expiry_update(_res(action=action)) is False


# ── url / sha256 게이트 ──

@pytest.mark.parametrize("url", ["", None])
def test_empty_url_does_not_offer(url):
    """다운로드 URL 이 비면 설치가 불가능하므로 제안하지 않는다."""
    assert updater.should_offer_expiry_update(_res(url=url)) is False


def test_missing_url_key_does_not_offer():
    """url 키 누락도 빈 값과 동일하게 취급한다."""
    res = _res()
    del res["url"]
    assert updater.should_offer_expiry_update(res) is False


@pytest.mark.parametrize("sha", ["", None])
def test_empty_sha256_does_not_offer(sha):
    """sha256 이 없으면 validate_installer 가 어차피 거부 → 헛다운로드를 시키지 않는다."""
    assert updater.should_offer_expiry_update(_res(sha256=sha)) is False


def test_missing_sha256_key_does_not_offer():
    """sha256 키 누락도 빈 값과 동일하게 취급한다."""
    res = _res()
    del res["sha256"]
    assert updater.should_offer_expiry_update(res) is False


# ── 비-dict 입력: 예외 없이 False (만료 게이트가 죽으면 안 됨) ──

@pytest.mark.parametrize("bad", [None, "", "optional", [], 0, 1, (), set(), object()])
def test_non_dict_input_returns_false_without_raising(bad):
    """dict 아닌 입력은 raise 하지 말고 False — 만료 게이트에서 예외가 새면 앱이 멈춘다."""
    assert updater.should_offer_expiry_update(bad) is False


# ── ★ 핵심 회귀 방지: skip_version 무시 ──

def test_skipped_version_still_offers(prefs_in_tmp):
    """'이 버전 건너뛰기' 한 버전과 동일해도 만료 게이트에서는 그대로 제안한다.

    should_offer_expiry_update 는 skip 을 인자로 받지 않는 설계다 —
    should_prompt 처럼 skip 을 참조하도록 '고치는' 회귀를 막기 위한 명시적 고정.
    """
    updater.set_skip_version("9.9.9")
    assert updater.get_skip_version() == "9.9.9"   # prefs 격리·기록 확인

    res = _res(version="9.9.9")
    assert updater.should_offer_expiry_update(res) is True

    # 대조군: 같은 상황에서 일반 무음 프롬프트는 억제된다 (두 정책의 의도적 분기)
    assert updater.should_prompt(
        True, False, "9.9.9", skip_version=updater.get_skip_version(),
    ) is False


def test_deferred_version_still_offers(prefs_in_tmp):
    """세션 '나중에'(deferred) 이력도 만료 게이트 제안에 영향을 주지 않는다."""
    res = _res(action="optional", version="9.9.9")
    assert updater.should_offer_expiry_update(res) is True
    assert updater.should_prompt(True, False, "9.9.9", deferred={"9.9.9"}) is False


def test_signature_takes_only_result(prefs_in_tmp):
    """단일 인자 계약 고정 — 호출부가 skip/deferred 를 넘기지 않아도 동작해야 한다."""
    assert updater.should_offer_expiry_update(_res()) is True


# ── decide() 실제 출력 통합 (네트워크 금지: fetch_version_info monkeypatch) ──

def test_decide_output_flows_into_offer(monkeypatch, log_in_tmp):
    """가짜 version.json → check()(=fetch+decide) 결과를 그대로 흘려 True 가 나오는지."""
    fake = {
        "version": "999.0.0",
        "mandatory": False,
        "url": "https://github.com/o/r/releases/download/v999.0.0/setup.exe",
        "size": 200_000_000,
        "sha256": "B" * 64,          # decide 가 소문자화
        "notes": "테스트 릴리스",
    }
    monkeypatch.setattr(updater, "fetch_version_info", lambda *a, **k: fake)

    res = updater.check()
    assert res["action"] == "optional"
    assert res["sha256"] == "b" * 64
    assert updater.should_offer_expiry_update(res) is True


def test_decide_no_update_does_not_offer(monkeypatch, log_in_tmp):
    """원격이 로컬보다 낮으면 decide 가 action='none' → 제안하지 않는다."""
    monkeypatch.setattr(
        updater, "fetch_version_info",
        lambda *a, **k: {"version": "0.0.1", "url": "https://github.com/x",
                         "sha256": "c" * 64},
    )
    res = updater.check()
    assert res["action"] == "none"
    assert updater.should_offer_expiry_update(res) is False


# ── 다운로드 결과 → 설치 전달 판정 (should_install_downloaded) ──
# download_installer 는 read 루프에서만 취소를 보므로, 마지막 청크 이후
# (sha256·검증·os.replace, 200MB면 수 초) 에 누른 취소는 무시되고 정상 경로가
# 반환된다. 호출부가 path 만 보면 사용자가 방금 거부한 무인설치가 그대로 실행된다.

def test_downloaded_path_without_cancel_installs():
    """정상 완료(경로 있음 + 취소 안 함) → 설치 진행."""
    assert updater.should_install_downloaded(r"C:\tmp\setup.exe", False) is True


def test_downloaded_path_with_cancel_does_not_install():
    """★ 회귀 방지: 경로가 돌아왔어도 사용자가 취소했으면 설치하지 않는다."""
    assert updater.should_install_downloaded(r"C:\tmp\setup.exe", True) is False


@pytest.mark.parametrize("path", ["", None])
@pytest.mark.parametrize("canceled", [False, True])
def test_empty_path_never_installs(path, canceled):
    """실패/취소로 경로가 비면 취소 여부와 무관하게 설치하지 않는다."""
    assert updater.should_install_downloaded(path, canceled) is False


def test_decide_missing_asset_fields_does_not_offer(monkeypatch, log_in_tmp):
    """버전만 올라가고 url/sha256 이 빠진 version.json → 제안 차단 (배포 실수 방어)."""
    monkeypatch.setattr(
        updater, "fetch_version_info", lambda *a, **k: {"version": "999.0.0"},
    )
    res = updater.check()
    assert res["action"] == "optional"      # decide 는 업데이트로 판정하지만
    assert updater.should_offer_expiry_update(res) is False   # 게이트가 막는다

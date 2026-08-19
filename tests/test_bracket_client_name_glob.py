"""수임처명 대괄호가 glob 문자 클래스로 해석되는 회귀.

위하고 수임처명에는 담당자 접두가 붙는다(예: '[손예린] 엘리야레포츠주식회사').
이 이름이 그대로 저장 경로에 들어가는데(make_save_dir / _locate_raw_data),
glob 은 '[손예린]' 을 리터럴이 아니라 '손·예·린 중 한 글자' 문자 클래스로
해석한다 → 경로 불일치 → 파일이 있어도 매칭 0건.

특히 건강보험 경로는 실패해도 예외·경고가 없다. nhis_pdf=None 이면 병합만
조용히 스킵되어 다운로드·업로드는 성공한 채 건강보험/장기요양 컬럼만 0원이
된다(실측: 엘리야레포츠 202608). 그래서 '값이 0' 이 아니라
'경로를 찾았는가' 를 직접 검증한다.
"""
import os

import pytest

from src.workflows.wehago_swsa import WehagoSwsaWorkflow

# 대괄호 + 공백(폴더에서 '_' 로 치환됨) 둘 다 포함하는 실제 형태
BRACKET_CLIENT = "[손예린] 엘리야레포츠주식회사"
BRACKET_FOLDER = "[손예린]_엘리야레포츠주식회사"
PLAIN_CLIENT = "코드크레인유한회사"


def _make_edi_tree(desktop, folder, period="202608"):
    """병렬 실행 레이아웃(공단EDI_{period}/{folder}/{포털}/)에 rawdata 3종 생성."""
    base = os.path.join(desktop, f"공단EDI_{period}", folder)
    files = {
        "국민건강보험": f"가입자고지내역서_건강_{period}.pdf",
        "국민연금": f"결정내역통보서_{period}.xlsx",
        "고용보험": f"고용보험료지원금정보_{period}.xls",
    }
    for sub, fname in files.items():
        d = os.path.join(base, sub)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, fname), "wb") as f:
            f.write(b"x")
    return base


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    d = tmp_path / "Desktop"
    d.mkdir()
    monkeypatch.setattr(
        "src.workflows.wehago_swsa.get_desktop_path", lambda: str(d))
    return str(d)


@pytest.mark.parametrize("client,folder", [
    (BRACKET_CLIENT, BRACKET_FOLDER),      # ★회귀: 대괄호
    (PLAIN_CLIENT, PLAIN_CLIENT),          # 대조군: 평범한 이름
])
def test_locate_raw_data_finds_all_three(desktop, client, folder):
    _make_edi_tree(desktop, folder)

    raw = WehagoSwsaWorkflow._locate_raw_data(client, 2026, 8)

    assert raw is not None, f"rawdata 미발견: {client}"
    assert raw["nhis_pdf"], (
        f"건강보험 PDF 를 찾지 못했다 ({client}) — 디렉토리에 glob.escape 가 "
        f"빠지면 대괄호가 문자 클래스로 해석돼 조용히 0원 업로드로 이어진다"
    )
    assert raw["nps_integrated"], f"국민연금 통합엑셀 미발견: {client}"
    assert raw["ei_xls"], f"고용보험 xls 미발견: {client}"


def test_bracket_and_plain_client_resolve_same_file_set(desktop):
    """대괄호 유무로 탐색 결과가 달라지면 안 된다(비대칭이 곧 이 버그)."""
    _make_edi_tree(desktop, BRACKET_FOLDER)
    _make_edi_tree(desktop, PLAIN_CLIENT)

    a = WehagoSwsaWorkflow._locate_raw_data(BRACKET_CLIENT, 2026, 8)
    b = WehagoSwsaWorkflow._locate_raw_data(PLAIN_CLIENT, 2026, 8)

    found = lambda r: sorted(k for k, v in (r or {}).items() if v)
    assert found(a) == found(b), (
        f"대괄호 수임처만 탐색 결과가 다르다: {found(a)} != {found(b)}"
    )


def test_hometax_declaration_file_lookup_escapes_brackets(tmp_path, monkeypatch):
    """홈택스 .01 신고파일 탐색도 같은 결함 — 디렉토리 이스케이프 필요.

    hometax.run_single 은 브라우저에 의존해 통째로 돌릴 수 없으므로,
    해당 호출부와 동일한 식(glob.escape 적용 여부)만 좁게 재현한다.
    """
    import glob

    save_dir = tmp_path / "원천전자신고_202608" / BRACKET_FOLDER
    save_dir.mkdir(parents=True)
    (save_dir / "sample.01").write_bytes(b"x")

    # 수정 전 동작(이스케이프 없음) — 대괄호 때문에 못 찾는다
    assert glob.glob(os.path.join(str(save_dir), "*.01")) == []
    # 수정 후 동작
    assert glob.glob(os.path.join(glob.escape(str(save_dir)), "*.01"))


def test_hometax_source_uses_glob_escape():
    """소스 수준 가드 — hometax 의 .01 탐색에서 glob.escape 가 빠지지 않도록."""
    import inspect

    import src.workflows.hometax as ht

    src = inspect.getsource(ht)
    assert 'glob.escape(save_dir)' in src, (
        "hometax 의 .01 탐색이 glob.escape(save_dir) 를 쓰지 않는다 — "
        "대괄호 수임처에서 '신고파일 없음' 으로 실패한다"
    )

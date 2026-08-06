"""NHIS 미리보기 URL 판정 / 인쇄 버튼 게이트 단위 테스트."""
import asyncio

from src.automation.nhis._doc_access import _is_preview_url, find_preview_tab


def test_is_preview_url_accepts_classic_wetz_popup():
    assert _is_preview_url(
        "https://edi.nhis.or.kr/webedi/popup.html?formname=CO::WETZ_163.xfdl"
    )


def test_is_preview_url_accepts_encoded_formname_and_reportview():
    assert _is_preview_url(
        "https://edi.nhis.or.kr/webedi/popup.html?formname=CO%3A%3AWETZ_163.xfdl"
    )
    assert _is_preview_url(
        "https://edi.nhis.or.kr/something/reportview.jsp?id=1"
    )
    assert _is_preview_url(
        "https://viewer.example/crownix/report?x=1"
    )


def test_is_preview_url_rejects_unrelated():
    assert not _is_preview_url("https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx")
    assert not _is_preview_url("about:blank")
    assert not _is_preview_url("")


class _Page:
    def __init__(self, url):
        self.url = url


class _Context:
    def __init__(self, pages):
        self.pages = pages


def test_find_preview_tab_prefers_new_page(monkeypatch):
    old = _Page("https://edi.nhis.or.kr/webedi/main")
    stale = _Page(
        "https://edi.nhis.or.kr/webedi/popup.html?formname=CO::WETZ_old.xfdl"
    )
    fresh = _Page(
        "https://edi.nhis.or.kr/webedi/popup.html?formname=CO::WETZ_163.xfdl"
    )
    ctx = _Context([old, stale, fresh])
    before = {id(old), id(stale)}

    async def no_sleep(_):
        return None

    monkeypatch.setattr(
        "src.automation.nhis._doc_access.asyncio.sleep", no_sleep,
    )
    found = asyncio.run(find_preview_tab(ctx, before, timeout=1))
    assert found is fresh


def test_find_preview_tab_falls_back_to_existing():
    only = _Page(
        "https://edi.nhis.or.kr/webedi/popup.html?formname=CO::WETZ_163.xfdl"
    )
    ctx = _Context([only])
    found = asyncio.run(find_preview_tab(ctx, {id(only)}, timeout=1))
    assert found is only

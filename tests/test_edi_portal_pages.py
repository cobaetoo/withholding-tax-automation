"""보안 팝업을 EDI 작업 탭으로 오인하지 않는 연결 회귀 테스트."""
import asyncio

import pytest

from src.automation.comwel import _common as comwel_common
from src.automation.nhis import _common_edi as nhis_common
from src.automation.nps import _common as nps_common
from src.utils import stealth


class _Page:
    def __init__(self, url, *, closed=False):
        self.url = url
        self._closed = closed
        self.viewports = []
        self.closed_by_helper = False

    def is_closed(self):
        return self._closed

    async def set_viewport_size(self, size):
        self.viewports.append(size)

    async def close(self):
        self.closed_by_helper = True


class _Context:
    def __init__(self, pages, new_page=None):
        self.pages = pages
        self._new_page = new_page or _Page("about:blank")
        self.new_page_calls = 0

    async def new_page(self):
        self.new_page_calls += 1
        self.pages.append(self._new_page)
        return self._new_page


class _Browser:
    def __init__(self, context):
        self.contexts = [context]


class _Chromium:
    def __init__(self, browser):
        self.browser = browser
        self.urls = []

    async def connect_over_cdp(self, url):
        self.urls.append(url)
        return self.browser


class _Playwright:
    def __init__(self, context):
        self.chromium = _Chromium(_Browser(context))


async def _noop_stealth(_context):
    return None


def _patch_stealth(monkeypatch):
    monkeypatch.setattr(stealth, "stealth_all_pages", _noop_stealth)
    monkeypatch.setattr(stealth, "register_auto_stealth", lambda _context: None)


@pytest.mark.parametrize(
    ("module", "portal_url"),
    [
        (nps_common, "https://edi.nps.or.kr/login"),
        (nhis_common, "https://edi.nhis.or.kr/login"),
        (comwel_common, "https://total.comwel.or.kr/login"),
    ],
)
def test_connect_page_prefers_portal_tab_over_security_popup(monkeypatch, module, portal_url):
    _patch_stealth(monkeypatch)
    popup = _Page("chrome-extension://security-popup")
    portal = _Page(portal_url)
    context = _Context([popup, portal])

    _browser, returned_context, returned_page = asyncio.run(
        module.connect_page(_Playwright(context), url="http://127.0.0.1:9999")
    )

    assert returned_context is context
    assert returned_page is portal
    assert context.new_page_calls == 0
    if module is comwel_common:
        assert portal.viewports == [{"width": 1920, "height": 1080}]


def test_connect_page_creates_normal_tab_when_only_security_popup_exists(monkeypatch):
    _patch_stealth(monkeypatch)

    async def immediate_sleep(_seconds):
        return None

    monkeypatch.setattr(nps_common.asyncio, "sleep", immediate_sleep)
    popup = _Page("chrome-extension://security-popup")
    normal_page = _Page("about:blank")
    context = _Context([popup], new_page=normal_page)

    _browser, _context, page = asyncio.run(nps_common.connect_page(_Playwright(context)))

    assert page is normal_page
    assert context.new_page_calls == 1
    assert popup is not page


def test_nhis_prelogin_close_popups_keeps_known_normal_edi_tab():
    popup = _Page("chrome-extension://security-popup")
    work_page = _Page("https://edi.nhis.or.kr/")
    context = _Context([popup, work_page])

    page = asyncio.run(nhis_common.close_popups(context, preferred_page=work_page))

    assert page is work_page
    assert popup.closed_by_helper is False


def test_nhis_logged_in_page_prefers_retrieve_main_over_homeapp():
    """homeapp 이 pages[0] 이어도 retrieveMain 을 메인으로 고른다."""
    homeapp = _Page("https://edi.nhis.or.kr/homeapp/wep/m/other.xx")
    main = _Page("https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx")
    context = _Context([homeapp, main])

    assert nhis_common._logged_in_page(context) is main


def test_nhis_close_popups_keeps_edi_work_tabs_closes_security_popup():
    """로그인 후 보안 팝업만 닫고 EDI 작업 탭(retrieveMain/homeapp)은 유지."""
    popup = _Page("chrome-extension://security-popup")
    homeapp = _Page("https://edi.nhis.or.kr/homeapp/wep/m/other.xx")
    main = _Page("https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx")
    context = _Context([popup, homeapp, main])

    page = asyncio.run(nhis_common.close_popups(context))

    assert page is main
    assert popup.closed_by_helper is True
    assert homeapp.closed_by_helper is False
    assert main.closed_by_helper is False


@pytest.mark.parametrize(
    "module",
    [nps_common, nhis_common, comwel_common],
)
def test_closed_login_page_fails_without_waiting(monkeypatch, module):
    async def forbidden_sleep(_seconds):
        raise AssertionError("closed browser must not enter 5-second polling")

    monkeypatch.setattr(module.asyncio, "sleep", forbidden_sleep)
    page = _Page("https://example.invalid", closed=True)
    if module is nhis_common:
        page.context = _Context([])

    assert asyncio.run(module.wait_for_login(page)) is False


def test_comwel_disconnected_login_page_fails_without_waiting(monkeypatch):
    class _DisconnectedPage:
        def is_closed(self):
            return False

        async def evaluate(self, *_args):
            raise RuntimeError("CDP connection lost")

    async def forbidden_sleep(_seconds):
        raise AssertionError("disconnected browser must not enter polling")

    monkeypatch.setattr(comwel_common.asyncio, "sleep", forbidden_sleep)

    assert asyncio.run(comwel_common.wait_for_login(_DisconnectedPage())) is False

"""NHIS 받은문서 클릭 직후 동기 생성된 웹EDI 탭 감지 회귀 테스트."""
import asyncio

from src.automation.nhis import _doc_access as docs
from src.utils.polling import wait_for_new_tab


class _Context:
    def __init__(self, pages):
        self.pages = pages


class _NewPage:
    def __init__(self, url="https://edi.nhis.or.kr/webedi/main.xx"):
        self.url = url
        self.viewport = None
        self.fronted = False

    async def set_viewport_size(self, size):
        self.viewport = size

    async def bring_to_front(self):
        self.fronted = True


class _MainPage:
    def __init__(self, context):
        self.context = context
        self.url = "https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx"

    async def evaluate(self, script):
        if "typeof pageLinkPopup1" in script:
            return True
        if "pageLinkPopup1('201')" in script:
            # NHIS의 window.open처럼 evaluate가 끝나기 전에 새 탭이 context에 보이는
            # 경우를 재현한다.
            self.context.pages.append(_NewPage())
            return None
        raise AssertionError(f"unexpected evaluate: {script[:60]}")


async def _no_sleep(*_args, **_kwargs):
    return None


def test_wait_for_new_tab_accepts_preclick_snapshot(monkeypatch):
    monkeypatch.setattr(docs.asyncio, "sleep", _no_sleep)
    old = _NewPage("https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx")
    context = _Context([old])
    before = {id(old)}
    new = _NewPage()
    context.pages.append(new)  # click 직후 동기 생성

    found, returned_before = asyncio.run(
        wait_for_new_tab(context, "webedi", timeout=1, interval=0, pages_before=before)
    )

    assert found is new
    assert returned_before == before


def test_open_received_docs_detects_synchronously_opened_webedi_tab(monkeypatch):
    monkeypatch.setattr(docs.asyncio, "sleep", _no_sleep)
    context = _Context([])
    page = _MainPage(context)
    context.pages.append(page)

    opened = asyncio.run(docs.open_received_docs(page, context))

    assert opened is context.pages[-1]
    assert opened.url == "https://edi.nhis.or.kr/webedi/main.xx"
    assert opened.viewport == {"width": 1920, "height": 1080}
    assert opened.fronted is True

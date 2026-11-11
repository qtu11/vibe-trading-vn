"""Google News wrapper resolution: modern ``batchexecute`` handshake, no icons.

The failed TCB run cited a ``news.google.com/rss/articles/...`` link that no
reader could fetch. Modern wrappers hide the publisher URL behind a
signature/timestamp handshake; the old resolver looked for a redirect in the
markup and could return a Google icon asset. These tests pin the handshake and
the strict publisher-only output.
"""

from __future__ import annotations

import json

import pytest

from src.tools.scraper import url_resolver

WRAPPER = (
    "https://news.google.com/rss/articles/CBMirgFBVV95cUxPblo2NS1nY0dNdmdta0RK"
    "QzBDbWltZlFKbnB0VHlCZmYyYjRONjZOZTNRaGQ4S1VldklsZDAtWk5MbmE0OFF6cHVw"
    "X1o3WEZua0ZqcklqY2ZmVXk4bU5kZU50VXlPWFY3aEMzZ2F5a2s1X3dGWHJGUl9IdVM3"
    "cnBvak53SXlUY3huU3ZOVk5uY0RtSjdIbzZfTVhaM2JYMXFDY1NrOGVVTHRCUmhwY2fS"
    "AaoBQVVfeXFMT2IzNndXa0FkVGRsU2JuczdhY19YMDM1RUlVbXhKZFFQQXFJemRTbEt4"
    "VFdGdzh1YWpvUmVnWFhQcHZzTVU4VkVLTnRaNFotMF9STDJDSHM3M3RIbVhfaHFrNVY3"
    "dFBJNU1iaGtlN2NJa1lZNFI2OFBDM1oycEVCOUhjUEdCNFJvTGEwQ0pfMVFrbGVWcEdl"
    "cTFhLTlkYVNadGl5TGkyRTNaWnc?oc=5"
)
PUBLISHER = "https://www.tinnhanhchungkhoan.vn/techcombank-tcb-post399882.html"


class _Response:
    def __init__(self, status_code: int = 200, text: str = "", url: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self.url = url


class _FakeClient:
    """Records calls and returns a scripted wrapper page and handshake frame."""

    def __init__(self, page: str, handshake: str) -> None:
        self.page = page
        self.handshake = handshake
        self.calls: list[tuple[str, str, str]] = []

    async def get(self, url: str) -> _Response:
        self.calls.append(("GET", url, ""))
        return _Response(200, self.page)

    async def post(self, url: str, **kwargs) -> _Response:
        self.calls.append(("POST", url, str(kwargs.get("content", ""))))
        return _Response(200, self.handshake)


def _page(signature: str = "SIGNATURE", timestamp: str = "1700000000") -> str:
    return (
        "<html><body><c-wiz><div data-n-a-sg=\"%s\" data-n-a-ts=\"%s\">"
        "</div></c-wiz></body></html>" % (signature, timestamp)
    )


def _handshake(asset: str = PUBLISHER) -> str:
    payload = json.dumps(["garturlres", asset, 1])
    frame = json.dumps([["wrb.fr", "Fbv4je", payload, None, None, None, "generic"]])
    return ")]}'\n\n" + frame


@pytest.mark.asyncio
async def test_resolver_performs_batchexecute_and_returns_publisher():
    client = _FakeClient(_page(), _handshake())

    resolved = await url_resolver.resolve_url(WRAPPER, client=client)

    assert resolved == PUBLISHER
    assert [kind for kind, _, _ in client.calls] == ["GET", "POST"]
    assert client.calls[0][1] == WRAPPER
    body = client.calls[1][2]
    assert body.startswith("f.req=")
    assert "Fbv4je" in body
    assert "SIGNATURE" in body
    assert "1700000000" in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "asset",
    [
        "https://lh3.googleusercontent.com/icon.png",
        "https://www.google.com/url?q=https://cafef.vn/tcb.chn",
        "https://news.google.com/rss/articles/OTHER",
        "https://user:secret@cafef.vn/tcb.chn",
        "javascript:alert(1)",
        "",
    ],
)
async def test_resolver_never_returns_a_google_asset_or_non_http(asset):
    """An icon, a Google page or a non-HTTP value is not a publisher URL."""
    client = _FakeClient(_page(), _handshake(asset))

    resolved = await url_resolver.resolve_url(WRAPPER, client=client)

    assert resolved == WRAPPER


@pytest.mark.asyncio
async def test_resolver_returns_original_when_handshake_is_blocked():
    client = _FakeClient(_page(signature=""), "")  # no data-n-a-sg

    assert await url_resolver.resolve_url(WRAPPER, client=client) == WRAPPER
    assert [kind for kind, _, _ in client.calls] == ["GET"]


class _RedirectClient:
    """A wrapper variant that answers with a plain HTTP redirect."""

    def __init__(self, final_url: str) -> None:
        self.final_url = final_url
        self.calls: list[tuple[str, str]] = []

    async def get(self, url: str) -> _Response:
        self.calls.append(("GET", url))
        return _Response(200, "", url=self.final_url)

    async def post(self, url: str, **kwargs) -> _Response:  # pragma: no cover
        self.calls.append(("POST", url))
        return _Response(200, "")


@pytest.mark.asyncio
async def test_plain_redirect_to_publisher_needs_no_handshake():
    client = _RedirectClient(PUBLISHER)

    assert await url_resolver.resolve_url(WRAPPER, client=client) == PUBLISHER
    assert [kind for kind, _ in client.calls] == ["GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "final_url",
    [
        "https://www.google.com/url?q=https://cafef.vn/tcb.chn",
        "https://consent.google.com/ml?continue=https://cafef.vn/tcb.chn",
    ],
)
async def test_redirect_to_a_google_host_is_not_a_publisher(final_url):
    client = _RedirectClient(final_url)

    assert await url_resolver.resolve_url(WRAPPER, client=client) == WRAPPER
    assert [kind for kind, _ in client.calls] == ["GET"]


@pytest.mark.asyncio
async def test_non_wrapper_url_is_returned_without_any_request():
    client = _FakeClient(_page(), _handshake())

    assert await url_resolver.resolve_url(
        "https://cafef.vn/tcb.chn", client=client
    ) == "https://cafef.vn/tcb.chn"
    assert client.calls == []


def test_wrapper_detection_covers_rss_and_web_paths():
    assert url_resolver.is_unreadable_wrapper(WRAPPER) is True
    assert url_resolver.is_unreadable_wrapper(
        "https://news.google.com/articles/CBMi-example?hl=vi"
    ) is True
    assert url_resolver.is_unreadable_wrapper("https://news.google.com/") is False
    assert url_resolver.is_unreadable_wrapper("https://cafef.vn/tcb.chn") is False

import time

import pytest

from scrape_mcp import scrape as scrape_module
from scrape_mcp.cache import Cache
from scrape_mcp.extract import extract_body, truncate
from scrape_mcp.fetch import FetchResult, detect_block, normalize_url
from scrape_mcp.scrape import BlockedError, scrape

ARTICLE = """<!doctype html><html><head><title>Motion design basics</title>
<meta name="author" content="Wons Designer"><meta property="og:site_name" content="Studio Blog"></head>
<body><nav><a href="/">Home</a><a href="/about">About</a></nav>
<article><h1>Motion design basics</h1>
<p>Easing gives movement weight. A linear tween feels mechanical, while an ease-out
curve feels like an object settling into place. This is the first rule of motion.</p>
<p>Duration matters too. Small elements should move in 150 to 250 milliseconds, while
large panels can take up to 400 milliseconds without feeling slow to the user.</p>
<p>Finally, choreograph related elements with short staggers so the eye can follow.</p>
</article><footer>Copyright 2026</footer></body></html>"""


def test_normalize_url_adds_scheme():
    assert normalize_url("example.com/a") == "https://example.com/a"


@pytest.mark.parametrize("bad", ["", "ftp://x.com", "file:///etc/passwd", "https://"])
def test_normalize_url_rejects(bad):
    with pytest.raises(ValueError):
        normalize_url(bad)


def test_detect_block_cloudflare_challenge():
    html = "<html><head><title>Just a moment...</title></head><body></body></html>"
    assert detect_block(403, "cloudflare", html) == "Cloudflare challenge"


def test_detect_block_ignores_normal_article_mentioning_cloudflare():
    html = "<html><title>Why we moved to Cloudflare</title><p>Cloudflare is a CDN.</p></html>"
    assert detect_block(200, "cloudflare", html) is None


def test_detect_block_cloudflare_status():
    assert detect_block(503, "cloudflare", "<html></html>") == "Cloudflare HTTP 503"


def test_extract_html_keeps_article_drops_nav():
    out = extract_body("text/html; charset=utf-8", ARTICLE, "https://blog.example/motion")
    assert "Easing gives movement weight" in out.markdown
    assert "About" not in out.markdown
    assert out.title == "Motion design basics"
    assert out.meta.get("author") == "Wons Designer"


def test_extract_json_is_pretty_printed():
    out = extract_body("application/json", '{"a":1}', "https://x")
    assert out.markdown == '```json\n{\n  "a": 1\n}\n```'


def test_truncate_on_paragraph_boundary():
    text = ("word " * 100 + "\n\n") * 5
    cut, was_cut = truncate(text, 1200)
    assert was_cut and len(cut) <= 1200 and cut.endswith("word")


def test_cache_roundtrip_and_ttl(tmp_path):
    cache = Cache(tmp_path / "c.db", ttl=60)
    result = FetchResult("https://a", "https://a/", 200, "text/html", b"<p>x</p>")
    cache.put(result)
    hit = cache.get("https://a")
    assert hit is not None and hit[0].body == b"<p>x</p>"
    cache.ttl = -1
    assert cache.get("https://a") is None


async def test_scrape_formats_header_and_uses_cache(tmp_path, monkeypatch):
    calls = 0

    async def fake_fetch(url, **_):
        nonlocal calls
        calls += 1
        return FetchResult(url, url, 200, "text/html", ARTICLE.encode()), None

    monkeypatch.setattr(scrape_module, "fetch_http", fake_fetch)
    cache = Cache(tmp_path / "c.db")

    first = await scrape("blog.example/motion", cache=cache)
    assert first.startswith("# Motion design basics")
    assert "- Source: https://blog.example/motion" in first
    assert "- Author: Wons Designer" in first
    assert "- Date:" not in first
    assert "Easing gives movement weight" in first

    second = await scrape("https://blog.example/motion", cache=cache)
    assert "(cached)" in second and calls == 1

    await scrape("https://blog.example/motion", cache=cache, fresh=True)
    assert calls == 2


async def test_scrape_raises_on_block(monkeypatch):
    async def fake_fetch(url, **_):
        return FetchResult(url, url, 403, "text/html", b""), "Cloudflare challenge"

    monkeypatch.setattr(scrape_module, "fetch_http", fake_fetch)
    with pytest.raises(BlockedError, match="Cloudflare challenge"):
        await scrape("https://protected.example")


async def test_server_lists_scrape_tool():
    from scrape_mcp.server import mcp

    tools = await mcp.list_tools()
    assert [t.name for t in tools] == ["scrape"]
    assert "url" in tools[0].input_schema["properties"]


def test_normalize_url_keeps_nested_url_in_query():
    url = "example.com/login?next=https://example.com/a"
    assert normalize_url(url) == "https://" + url


@pytest.mark.parametrize(
    "html",
    [
        '<html><title>Post</title><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script><p>Hi</p></html>',
        '<html><title>Post</title><form><div class="g-recaptcha"></div></form></html>',
        '<html><title>Post</title><script src="https://client.perimeterx.net/x/main.min.js"></script></html>',
    ],
)
def test_detect_block_ignores_widgets_on_normal_pages(html):
    assert detect_block(200, "cloudflare", html) is None


def test_detect_block_flags_markers_on_error_pages():
    html = '<html><script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></html>'
    assert detect_block(403, "cloudflare", html) == "Cloudflare challenge"


def test_text_uses_meta_charset_when_header_has_none():
    html = '<html><head><meta charset="windows-1252"></head><body>caf\xe9 d\xe9j\xe0 vu</body></html>'
    result = FetchResult("https://a", "https://a", 200, "text/html", html.encode("windows-1252"))
    assert "café déjà vu" in result.text


def test_text_handles_quoted_header_charset():
    result = FetchResult("https://a", "https://a", 200, 'text/html; charset="iso-8859-1"', "caf\xe9".encode("latin-1"))
    assert result.text == "café"


@pytest.mark.parametrize("url", ["http://localhost:8080/admin", "http://169.254.169.254/latest/", "http://192.168.1.1/"])
async def test_private_hosts_are_refused(url, monkeypatch):
    from scrape_mcp.fetch import FetchError, ensure_public_host

    monkeypatch.delenv("SCRAPE_MCP_ALLOW_PRIVATE", raising=False)
    with pytest.raises(FetchError, match="private or local"):
        await ensure_public_host(url)


async def test_private_hosts_allowed_with_opt_in(monkeypatch):
    from scrape_mcp.fetch import ensure_public_host

    monkeypatch.setenv("SCRAPE_MCP_ALLOW_PRIVATE", "1")
    await ensure_public_host("http://localhost:8080/")


def test_cache_prunes_expired_rows(tmp_path):
    cache = Cache(tmp_path / "c.db", ttl=60)
    cache.put(FetchResult("https://a", "https://a", 200, "text/html", b"x"))
    cache._db.execute("UPDATE pages SET fetched_at = 0")
    cache._db.commit()
    reopened = Cache(tmp_path / "c.db", ttl=60)
    assert reopened._db.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


def test_cache_errors_are_not_fatal(tmp_path):
    cache = Cache(tmp_path / "c.db")
    cache.close()
    cache.put(FetchResult("https://a", "https://a", 200, "text/html", b"x"))
    assert cache.get("https://a") is None


async def test_binary_responses_are_not_cached(tmp_path, monkeypatch):
    from scrape_mcp.fetch import FetchError

    async def fake_fetch(url, **_):
        return FetchResult(url, url, 200, "application/pdf", b"%PDF"), None

    monkeypatch.setattr(scrape_module, "fetch_http", fake_fetch)
    cache = Cache(tmp_path / "c.db")
    with pytest.raises(FetchError, match="not a web page"):
        await scrape("https://x.example/report.pdf", cache=cache)
    assert cache.get("https://x.example/report.pdf") is None

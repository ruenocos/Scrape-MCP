"""Fast HTTP fetching with a real browser TLS fingerprint, plus block detection."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from dataclasses import dataclass
from functools import cached_property
from urllib.parse import urlparse

from curl_cffi import CurlError
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException
from trafilatura.utils import decode_file

DEFAULT_TIMEOUT = 25.0
MAX_BYTES = 15 * 1024 * 1024
BINARY_TYPES = ("image/", "video/", "audio/", "application/pdf", "application/octet-stream", "application/zip")


class FetchError(Exception):
    """The page could not be fetched at all (DNS, timeout, bad URL, not a web page)."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    fetcher: str = "http"

    @cached_property
    def text(self) -> str:
        match = re.search(r"""charset\s*=\s*["']?([\w.:-]+)""", self.content_type, re.I)
        if match:
            try:
                return self.body.decode(match.group(1))
            except (LookupError, UnicodeDecodeError):
                pass
        # No usable header charset: let Trafilatura sniff BOMs, <meta charset> and the bytes.
        return decode_file(self.body)


def is_binary(content_type: str) -> bool:
    return content_type.lower().startswith(BINARY_TYPES)


def normalize_url(url: str) -> str:
    """Add a scheme when missing and reject anything that is not http(s)."""
    url = url.strip()
    if not url:
        raise ValueError("URL is empty")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http and https URLs are supported, got {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError(f"URL has no host: {url!r}")
    return url


async def ensure_public_host(url: str) -> None:
    """Refuse local and private network addresses, so a page that tricks Claude into
    scraping http://localhost or a router admin page gets nowhere.

    Set SCRAPE_MCP_ALLOW_PRIVATE=1 to scrape your own local servers on purpose.
    """
    if os.environ.get("SCRAPE_MCP_ALLOW_PRIVATE") == "1":
        return
    host = urlparse(url).hostname or ""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve {host}: {exc}") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise FetchError(
                f"{host} points to a private or local address ({addr}); refusing to scrape it. "
                "Set SCRAPE_MCP_ALLOW_PRIVATE=1 to allow this."
            )


# Interstitial pages that replace the whole response. Their titles are specific enough
# to trust on any status code.
_WALL_TITLES: list[tuple[str, re.Pattern[str]]] = [
    ("Cloudflare challenge", re.compile(r"<title>\s*Just a moment\.\.\.\s*</title>", re.I)),
    ("Cloudflare block", re.compile(r"<title>\s*Attention Required! \| Cloudflare\s*</title>", re.I)),
    ("Fastly client challenge", re.compile(r"<title>\s*Client Challenge\s*</title>", re.I)),
]

# Markers that normal pages also carry (Cloudflare's JS detection script, a reCAPTCHA
# comment form, the PerimeterX sensor), so they only count on an error response.
_ERROR_MARKERS: list[tuple[str, re.Pattern[str]]] = [
    ("Cloudflare challenge", re.compile(r"cf-chl-|challenges\.cloudflare\.com/turnstile|/cdn-cgi/challenge-platform/", re.I)),
    ("Cloudflare block", re.compile(r"cf-error-details", re.I)),
    ("DataDome", re.compile(r"captcha-delivery\.com", re.I)),
    ("PerimeterX", re.compile(r"px-captcha|_pxCaptcha", re.I)),
    ("Akamai", re.compile(r"errors\.edgesuite\.net|<title>\s*Access Denied\s*</title>", re.I)),
    ("CAPTCHA", re.compile(r"g-recaptcha|hcaptcha\.com/1/api\.js|<title>[^<]*captcha[^<]*</title>", re.I)),
]


def detect_block(status: int, headers_server: str, html: str) -> str | None:
    """Return a short reason when the response looks like an anti-bot wall, else None."""
    head = html[:200_000]
    for name, pattern in _WALL_TITLES:
        if pattern.search(head):
            return name
    if status < 400:
        return None
    for name, pattern in _ERROR_MARKERS:
        if pattern.search(head):
            return name
    if status in (403, 429, 503) and "cloudflare" in headers_server.lower():
        return f"Cloudflare HTTP {status}"
    if status == 429:
        return "rate limited (HTTP 429)"
    return None


async def fetch_http(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> tuple[FetchResult, str | None]:
    """Fetch with curl_cffi impersonating Chrome. Returns the result and a block reason, if any.

    The body is streamed and capped at MAX_BYTES, and binary files are refused from
    their headers before the body is downloaded.
    """
    await ensure_public_host(url)
    try:
        async with AsyncSession(impersonate="chrome") as session:
            async with session.stream(
                "GET",
                url,
                timeout=timeout,
                allow_redirects=True,
                max_redirects=10,
                headers={"Accept-Language": "en-US,en;q=0.9"},
            ) as response:
                content_type = response.headers.get("content-type", "")
                if is_binary(content_type):
                    raise FetchError(f"{url} is not a web page ({content_type}); binary files are not supported yet.")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_content():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_BYTES:
                        break
                result = FetchResult(
                    url=url,
                    final_url=str(response.url),
                    status=response.status_code,
                    content_type=content_type,
                    body=b"".join(chunks)[:MAX_BYTES],
                )
                server = response.headers.get("server", "")
    except (RequestException, CurlError) as exc:
        raise FetchError(f"Could not fetch {url}: {exc}") from exc

    reason = None
    if "html" in result.content_type or not result.content_type:
        reason = detect_block(result.status, server, result.text)
    elif result.status == 429:
        reason = "rate limited (HTTP 429)"
    return result, reason

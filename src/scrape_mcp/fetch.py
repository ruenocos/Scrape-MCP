"""Fast HTTP fetching with a real browser TLS fingerprint, plus block detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

DEFAULT_TIMEOUT = 25.0
MAX_BYTES = 15 * 1024 * 1024


class FetchError(Exception):
    """The page could not be fetched at all (DNS, timeout, bad URL)."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    fetcher: str = "http"

    @property
    def text(self) -> str:
        charset = "utf-8"
        match = re.search(r"charset=([\w-]+)", self.content_type, re.I)
        if match:
            charset = match.group(1)
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def normalize_url(url: str) -> str:
    """Add a scheme when missing and reject anything that is not http(s)."""
    url = url.strip()
    if not url:
        raise ValueError("URL is empty")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http and https URLs are supported, got {parsed.scheme!r}")
    if not parsed.netloc:
        raise ValueError(f"URL has no host: {url!r}")
    return url


# Markers that anti-bot interstitials put in the page. Kept specific so a normal
# article that merely mentions Cloudflare is not flagged.
_BLOCK_MARKERS: list[tuple[str, re.Pattern[str]]] = [
    ("Cloudflare challenge", re.compile(r"<title>\s*Just a moment\.\.\.\s*</title>|cf-chl-|challenges\.cloudflare\.com/turnstile|/cdn-cgi/challenge-platform/", re.I)),
    ("Cloudflare block", re.compile(r"<title>\s*Attention Required! \| Cloudflare\s*</title>|cf-error-details", re.I)),
    ("DataDome", re.compile(r"captcha-delivery\.com|geo\.captcha-delivery", re.I)),
    ("PerimeterX", re.compile(r"px-captcha|_pxCaptcha|perimeterx", re.I)),
    ("Akamai", re.compile(r"<title>\s*Access Denied\s*</title>[\s\S]{0,2000}Reference&#32;&#35;|errors\.edgesuite\.net", re.I)),
    ("CAPTCHA", re.compile(r"g-recaptcha|hcaptcha\.com/1/api\.js|<title>[^<]*captcha[^<]*</title>", re.I)),
]


def detect_block(status: int, headers_server: str, html: str) -> str | None:
    """Return a short reason when the response looks like an anti-bot wall, else None."""
    head = html[:200_000]
    for name, pattern in _BLOCK_MARKERS:
        if pattern.search(head):
            return name
    if status in (403, 429, 503) and "cloudflare" in headers_server.lower():
        return f"Cloudflare HTTP {status}"
    if status == 429:
        return "rate limited (HTTP 429)"
    return None


async def fetch_http(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> tuple[FetchResult, str | None]:
    """Fetch with curl_cffi impersonating Chrome. Returns the result and a block reason, if any."""
    try:
        async with AsyncSession(impersonate="chrome") as session:
            response = await session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
                max_redirects=10,
                headers={"Accept-Language": "en-US,en;q=0.9"},
            )
    except RequestException as exc:
        raise FetchError(f"Could not fetch {url}: {exc}") from exc

    body = response.content[:MAX_BYTES]
    result = FetchResult(
        url=url,
        final_url=str(response.url),
        status=response.status_code,
        content_type=response.headers.get("content-type", ""),
        body=body,
    )
    reason = None
    if "html" in result.content_type or not result.content_type:
        reason = detect_block(result.status, response.headers.get("server", ""), result.text)
    elif result.status == 429:
        reason = "rate limited (HTTP 429)"
    return result, reason

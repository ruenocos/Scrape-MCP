"""The scrape pipeline: cache, fetch, block check, extract, format."""

from __future__ import annotations

from datetime import datetime, timezone

from .cache import Cache
from .extract import extract_body, truncate
from .fetch import FetchError, fetch_http, normalize_url


class BlockedError(Exception):
    """The site answered with an anti-bot wall instead of the page."""


async def scrape(
    url: str,
    *,
    cache: Cache | None = None,
    max_chars: int = 20_000,
    include_links: bool = False,
    fresh: bool = False,
) -> str:
    url = normalize_url(url)

    cached_at = None
    hit = None if (fresh or cache is None) else cache.get(url)
    if hit is not None:
        result, cached_at = hit
    else:
        result, block = await fetch_http(url)
        if block:
            raise BlockedError(
                f"{url} returned an anti-bot page ({block}). The fast fetcher cannot get past it; "
                "the stealth browser fallback is planned for the next phase."
            )
        if result.status >= 400:
            raise FetchError(f"{url} returned HTTP {result.status}.")
        if cache is not None:
            cache.put(result)

    ct = result.content_type.lower()
    if ct.startswith(("image/", "video/", "audio/")) or "pdf" in ct or "octet-stream" in ct:
        raise FetchError(f"{url} is not a web page ({result.content_type or 'unknown type'}); binary files are not supported yet.")

    extracted = extract_body(result.content_type, result.text, result.final_url, include_links=include_links)
    body, cut = truncate(extracted.markdown, max_chars)
    if not body:
        body = "_No readable text found. The page may render its content with JavaScript, which the next phase will handle._"

    fetched = datetime.fromtimestamp(cached_at, timezone.utc) if cached_at else datetime.now(timezone.utc)
    lines = [f"# {extracted.title}" if extracted.title else f"# {result.final_url}", ""]
    lines.append(f"- Source: {result.final_url}")
    for key in ("sitename", "author", "date"):
        if key in extracted.meta:
            lines.append(f"- {key.capitalize()}: {extracted.meta[key]}")
    lines.append(f"- Fetched: {fetched:%Y-%m-%d %H:%M} UTC via {result.fetcher}{' (cached)' if cached_at else ''}")
    if cut:
        lines.append(f"- Truncated to {len(body):,} of {len(extracted.markdown):,} characters; raise max_chars to see more.")
    lines += ["", "---", "", body]
    return "\n".join(lines)

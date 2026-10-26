"""The scrape pipeline: cache, fetch, block check, extract, format."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from .cache import Cache
from .extract import extract_body, truncate
from .fetch import FetchError, FetchResult, fetch_http, is_binary, normalize_url
from . import youtube as yt


# Less text than this from a page bigger than this usually means a JavaScript app shell.
THIN_CHARS = 300
THIN_HTML_BYTES = 3000


class BlockedError(Exception):
    """The site answered with an anti-bot wall instead of the page."""


def _status_hint(url: str, status: int) -> str:
    host = (urlparse(url).hostname or "").lower()
    if status in (401, 403) and (host == "reddit.com" or host.endswith(".reddit.com")):
        return (
            " Reddit has refused anonymous access since May 2026. Reddit support through its "
            "free official API (OAuth keys) is planned for Phase 2."
        )
    return ""


async def scrape(
    url: str,
    *,
    cache: Cache | None = None,
    max_chars: int = 20_000,
    include_links: bool = False,
    fresh: bool = False,
) -> str:
    url = normalize_url(url)
    if yt.is_youtube_url(url):
        try:
            yt.parse_video_id(url)
        except ValueError:
            pass  # a channel or playlist page: scrape it as a normal page
        else:
            return await youtube(url, cache=cache, max_chars=max_chars, fresh=fresh)

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
            raise FetchError(f"{url} returned HTTP {result.status}.{_status_hint(result.final_url, result.status)}")
        if is_binary(result.content_type):
            raise FetchError(f"{url} is not a web page ({result.content_type}); binary files are not supported yet.")
        if cache is not None:
            cache.put(result)

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
    if len(extracted.markdown) < THIN_CHARS and len(result.body) > THIN_HTML_BYTES:
        lines.append(
            "- Note: very little text came back from a much larger page, so it probably renders its "
            "content with JavaScript. The stealth browser planned for the next phase will handle it."
        )
    if cut:
        lines.append(f"- Truncated to {len(body):,} of {len(extracted.markdown):,} characters; raise max_chars to see more.")
    lines += ["", "---", "", body]
    return "\n".join(lines)


async def youtube(
    video: str,
    *,
    cache: Cache | None = None,
    lang: str = "en",
    transcript: bool = True,
    max_chars: int = 40_000,
    fresh: bool = False,
) -> str:
    """Video details and transcript as markdown. Cached like pages, keyed by video and language."""
    video_id = yt.parse_video_id(video)
    key = f"youtube:{video_id}:{lang}:{int(transcript)}"
    hit = None if (fresh or cache is None) else cache.get(key)
    if hit is not None:
        markdown = hit[0].body.decode()
    else:
        try:
            info = await yt.get_video(video_id, lang=lang, transcript=transcript)
        except yt.YouTubeBlockedError as exc:
            raise BlockedError(
                f"YouTube asked for a bot check on {video_id}: {exc}. This usually clears from a home "
                "connection; heavy use from one IP can trigger it for a while."
            ) from exc
        except yt.YouTubeError as exc:
            raise FetchError(f"Could not read YouTube video {video_id}: {exc}") from exc
        header, text = yt.format_video(info)
        if transcript and not text:
            text = "_No transcript available: the video has no captions in any language._"
        markdown = header + ("\n\n## Transcript\n\n" + text if transcript else "")
        if cache is not None:
            url = f"https://www.youtube.com/watch?v={video_id}"
            cache.put(FetchResult(key, url, 200, "text/markdown", markdown.encode(), "yt-dlp"))
    body, cut = truncate(markdown, max_chars)
    if cut:
        body += f"\n\n_Truncated to {len(body):,} of {len(markdown):,} characters; raise max_chars to see more._"
    return body

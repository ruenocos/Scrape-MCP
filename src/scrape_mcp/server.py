"""MCP server entry point. Runs over stdio for Claude Code and Claude Desktop."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import __version__
from .cache import Cache
from .fetch import FetchError
from .scrape import BlockedError, scrape as run_scrape, youtube as run_youtube

INSTRUCTIONS = """\
Use `scrape` to read a web page as clean markdown. It is usually better than a generic
web fetch: it sends a real browser fingerprint, strips navigation and ads, and caches
pages for an hour. Pass fresh=true when the user needs the latest version of a page.
Use `youtube` for a YouTube video's details and transcript; `scrape` also routes video
links there automatically.
"""

mcp = MCPServer("scrape-mcp", version=__version__, instructions=INSTRUCTIONS)
_cache: Cache | None = None


def _get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def scrape(url: str, max_chars: int = 20_000, include_links: bool = False, fresh: bool = False) -> str:
    """Read a web page and return its main content as markdown, with title, source and date.

    Args:
        url: The page to read. https:// is added when missing.
        max_chars: Cut the content to about this many characters. Use 0 for no limit.
        include_links: Keep hyperlinks in the markdown (longer output).
        fresh: Skip the one-hour cache and fetch the page again.
    """
    try:
        return await run_scrape(
            url, cache=_get_cache(), max_chars=max_chars, include_links=include_links, fresh=fresh
        )
    except (ValueError, FetchError, BlockedError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def youtube(
    video: str, transcript: bool = True, lang: str = "en", max_chars: int = 40_000, fresh: bool = False
) -> str:
    """Get a YouTube video's details (title, channel, date, duration, stats, chapters,
    description) and its transcript as timestamped paragraphs.

    Args:
        video: A YouTube URL (watch, youtu.be, shorts, embed, live) or an 11-character video ID.
        transcript: Include the transcript. Set false for details only (faster).
        lang: Preferred caption language code, such as "en" or "nl". Falls back to English,
            then the video's own language.
        max_chars: Cut the output to about this many characters. Use 0 for no limit.
        fresh: Skip the one-hour cache.
    """
    try:
        return await run_youtube(
            video, cache=_get_cache(), lang=lang, transcript=transcript, max_chars=max_chars, fresh=fresh
        )
    except (ValueError, FetchError, BlockedError) as exc:
        raise ToolError(str(exc)) from exc


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()

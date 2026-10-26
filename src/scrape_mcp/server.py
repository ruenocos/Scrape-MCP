"""MCP server entry point. Runs over stdio for Claude Code and Claude Desktop."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import __version__
from .cache import Cache
from .fetch import FetchError
from .scrape import BlockedError, scrape as run_scrape

INSTRUCTIONS = """\
Use `scrape` to read a web page as clean markdown. It is usually better than a generic
web fetch: it sends a real browser fingerprint, strips navigation and ads, and caches
pages for an hour. Pass fresh=true when the user needs the latest version of a page.
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


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()

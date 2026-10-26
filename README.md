# Scrape MCP

A local MCP server that reads web pages as clean markdown for Claude. It aims to do better than a generic web fetch, taking cues from Firecrawl and Apify, while running on your own machine for free.

**Status:** Phase 0 (foundation). The `scrape` tool works for normal websites. Stealth browsing for Cloudflare-protected sites, YouTube and Reddit come in the next phases.

## What it does today

- **`scrape(url)`** returns the page's main content as markdown, with title, source, author and date when the page states them.
- Sends requests with a real Chrome TLS fingerprint (curl_cffi), which gets past many basic bot filters that block plain HTTP clients.
- Strips navigation, footers and ads with Trafilatura.
- Caches pages for one hour in `~/.cache/scrape-mcp/`. Pass `fresh: true` to refetch.
- Recognises anti-bot walls (Cloudflare, DataDome, PerimeterX, CAPTCHAs) and says so, instead of handing Claude a "Just a moment..." page.

## Install on a Mac

You need [uv](https://docs.astral.sh/uv/), which also fetches the right Python for you:

```sh
brew install uv
```

### Cowork

Install the plugin file `web-scraper.plugin` (built from [`plugin/web-scraper`](plugin/web-scraper)). It adds the `scrape` tool and a skill that tells Claude when to use it. The first start downloads dependencies and can take a minute; if the tool doesn't appear, start a new task.

### Claude Code

```sh
claude mcp add scrape --scope user -- uvx --from git+https://github.com/ruenocos/Scrape-MCP scrape-mcp
```

Then ask Claude something like "scrape https://www.nngroup.com/articles/animation-purpose-ux/ and summarise it".

### Claude Desktop

Open **Settings → Developer → Edit Config** and add this to `claude_desktop_config.json`, then restart Claude Desktop:

```json
{
  "mcpServers": {
    "scrape": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/ruenocos/Scrape-MCP", "scrape-mcp"]
    }
  }
}
```

If Claude Desktop cannot find `uvx`, replace it with the full path from `which uvx`.

## Tool reference

| Parameter | Default | What it does |
| --- | --- | --- |
| `url` | required | Page to read. `https://` is added when missing. |
| `max_chars` | 20000 | Cut content to about this many characters. `0` means no limit. |
| `include_links` | false | Keep hyperlinks in the markdown. |
| `fresh` | false | Skip the cache. |

Set `SCRAPE_MCP_CACHE_DIR` to move the cache. Local and private network addresses (localhost, 192.168.x.x and so on) are refused so a malicious page can't make Claude read your internal services; set `SCRAPE_MCP_ALLOW_PRIVATE=1` to allow them.

## Development

```sh
uv sync
uv run pytest
uv run python scripts/check_sites.py   # live check against 20 real sites
```

## Roadmap

1. **Phase 0, foundation:** `scrape` with fast fetch, clean markdown, cache. *(this release)*
2. **Phase 1, hard websites:** stealth browser fallback (Camoufox via Scrapling) for Cloudflare and JavaScript-heavy pages, plus `crawl` and `map_site`.
3. **Phase 2, platforms:** YouTube metadata and transcripts (yt-dlp with PO tokens) and Reddit threads (official OAuth API).
4. **Phase 3, ship it:** Claude Code plugin, one-command installer and a `doctor` check.

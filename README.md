# Scrape MCP

A local MCP server that reads web pages as clean markdown for Claude. It aims to do better than a generic web fetch, taking cues from Firecrawl and Apify, while running on your own machine for free.

**Status:** Phase 1 in progress. `scrape` works for normal websites and `youtube` reads video details and transcripts. Stealth browsing for Cloudflare-protected and JavaScript-heavy sites is next, then Reddit.

## What it does today

- **`scrape(url)`** returns the page's main content as markdown, with title, source, author and date when the page states them.
- Sends requests with a real Chrome TLS fingerprint (curl_cffi), which gets past many basic bot filters that block plain HTTP clients.
- Strips navigation, footers and ads with Trafilatura.
- Caches pages for one hour in `~/.cache/scrape-mcp/`. Pass `fresh: true` to refetch.
- Recognises anti-bot walls (Cloudflare, DataDome, PerimeterX, CAPTCHAs) and says so, instead of handing Claude a "Just a moment..." page.

- **`youtube(video)`** returns a video's title, channel, date, duration, stats, chapters, description and transcript. The transcript comes back as timestamped paragraphs grouped by chapter. It works with any video link or ID, and `scrape` hands video links to it automatically. It uses yt-dlp (with a bundled Deno runtime for YouTube's player code), and falls back to youtube-transcript-api when yt-dlp finds no captions.

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

| `youtube` parameter | Default | What it does |
| --- | --- | --- |
| `video` | required | Any YouTube video URL or 11-character ID. |
| `transcript` | true | Include the transcript. `false` is faster. |
| `lang` | `en` | Preferred caption language; falls back to English, then the video's language. |
| `max_chars` | 40000 | Cut output to about this many characters. `0` means no limit. |
| `fresh` | false | Skip the cache. |

Set `SCRAPE_MCP_CACHE_DIR` to move the cache. Local and private network addresses (localhost, 192.168.x.x and so on) are refused so a malicious page can't make Claude read your internal services; set `SCRAPE_MCP_ALLOW_PRIVATE=1` to allow them.

## Development

```sh
uv sync
uv run pytest
uv run python scripts/check_sites.py   # live check against 20 real sites
```

## Roadmap

1. **Phase 0, foundation:** `scrape` with fast fetch, clean markdown, cache. *(done)*
2. **Phase 1a, YouTube:** video details and transcripts. *(this release)*
3. **Phase 1b, hard websites:** stealth browser fallback (Camoufox via Scrapling) for Cloudflare, JavaScript-heavy and listing pages, plus `crawl` and `map_site`.
4. **Phase 2, Reddit:** posts and comment trees through the official OAuth API.
5. **Phase 3, polish:** Claude Code plugin, one-command installer and a `doctor` check.

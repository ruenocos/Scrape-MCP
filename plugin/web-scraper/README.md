# Web Scraper plugin

Adds the Scrape MCP server to Cowork and Claude Code, plus a skill that tells Claude when to use it.

- **Tool:** `scrape(url, max_chars, include_links, fresh)` returns a page's main content as markdown.
- **Skill:** `scrape-web-pages` makes Claude reach for `scrape` when you share a URL or a web fetch fails.

The server runs on your own machine through `uvx`. If `uv` is not installed, the launcher installs it once from astral.sh. No API keys or accounts are needed.

Source and full docs: https://github.com/ruenocos/Scrape-MCP

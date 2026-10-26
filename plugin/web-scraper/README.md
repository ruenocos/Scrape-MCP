# Web Scraper plugin

Adds the Scrape MCP server to Cowork and Claude Code, plus a skill that tells Claude when to use it.

- **Tool:** `scrape(url, max_chars, include_links, fresh)` returns a page's main content as markdown.
- **Tool:** `youtube(video, transcript, lang)` returns a video's details and timestamped transcript.
- **Skill:** `scrape-web-pages` makes Claude reach for these tools when you share a link or a web fetch fails.

The server runs on your own machine through `uvx`, so install uv first (`brew install uv`). No API keys or accounts are needed.

Source and full docs: https://github.com/ruenocos/Scrape-MCP

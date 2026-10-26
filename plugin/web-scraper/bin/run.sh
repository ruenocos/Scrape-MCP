#!/bin/sh
# Starts the Scrape MCP server. Desktop apps launch without your shell's PATH,
# so look in the usual install folders, and install uv once if it is missing.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v uvx >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >&2
fi
exec uvx --from "git+https://github.com/ruenocos/Scrape-MCP" scrape-mcp

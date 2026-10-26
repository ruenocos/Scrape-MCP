"""Phase 0 gate: scrape a fixed set of real sites and report which return clean markdown.

Run from the repo root:  uv run python scripts/check_sites.py
"""

from __future__ import annotations

import asyncio
import sys
import time

from scrape_mcp.fetch import FetchError
from scrape_mcp.scrape import BlockedError, scrape

SITES = [
    "https://en.wikipedia.org/wiki/Animation",
    "https://developer.mozilla.org/en-US/docs/Web/CSS/animation",
    "https://www.bbc.com/news",
    "https://www.theverge.com/",
    "https://www.smashingmagazine.com/",
    "https://css-tricks.com/",
    "https://www.nngroup.com/articles/animation-purpose-ux/",
    "https://m3.material.io/styles/motion/overview",
    "https://developer.apple.com/design/human-interface-guidelines/motion",
    "https://github.com/D4Vinci/Scrapling",
    "https://news.ycombinator.com/",
    "https://www.python.org/",
    "https://docs.python.org/3/library/asyncio.html",
    "https://www.figma.com/blog/",
    "https://stackoverflow.com/questions/tagged/css-animations",
    "https://medium.com/",
    "https://www.awwwards.com/",
    "https://www.nytimes.com/",
    "https://www.gov.uk/",
    "https://arxiv.org/abs/2605.21097",
]


async def check(url: str) -> tuple[str, str, int, float]:
    start = time.perf_counter()
    try:
        out = await scrape(url, max_chars=0)
    except BlockedError as exc:
        return url, "BLOCKED", 0, time.perf_counter() - start
    except (FetchError, ValueError) as exc:
        return url, f"ERROR {str(exc)[:60]}", 0, time.perf_counter() - start
    body = out.split("\n---\n", 1)[-1]
    status = "OK" if len(body) > 500 else "THIN"
    return url, status, len(body), time.perf_counter() - start


async def main() -> int:
    results = await asyncio.gather(*(check(u) for u in SITES))
    ok = 0
    for url, status, chars, secs in results:
        ok += status == "OK"
        print(f"{status:<8} {chars:>7,} chars {secs:5.1f}s  {url}")
    print(f"\n{ok}/{len(SITES)} returned clean markdown")
    return 0 if ok == len(SITES) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

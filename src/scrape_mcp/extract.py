"""Turn fetched content into compact, LLM-friendly markdown."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import trafilatura
from trafilatura.metadata import extract_metadata


# Page furniture that Trafilatura keeps as text: Wikipedia "[edit]" links and the like.
_PRUNE_XPATH = [
    "//span[contains(@class, 'mw-editsection')]",
    "//sup[contains(@class, 'reference')]",
]


_NAME_PARTICLES = {"de", "da", "di", "du", "del", "der", "den", "van", "von", "la", "le", "bin", "al", "ten", "ter"}


def _plausible_author(value: str) -> bool:
    """Reject menu text and link lists that metadata extraction mistakes for an author,
    such as 'Filter by author' or Wikipedia's 'Authority control databases ...'."""
    if len(value) > 80:
        return False
    for name in re.split(r"[,;&]| and ", value):
        words = name.split()
        if len(words) > 4:
            return False
        # Real names are capitalised apart from particles like "van" or "de".
        if any(w[0].islower() and w not in _NAME_PARTICLES for w in words):
            return False
    return True


@dataclass
class Extracted:
    markdown: str
    title: str | None = None
    meta: dict[str, str] = field(default_factory=dict)


def extract_html(html: str, url: str, *, include_links: bool = False) -> Extracted:
    """Main content as markdown via Trafilatura, falling back to a looser pass."""
    markdown = trafilatura.extract(
        html,
        prune_xpath=_PRUNE_XPATH,
        url=url,
        output_format="markdown",
        include_links=include_links,
        include_tables=True,
        include_formatting=True,
        include_comments=False,
        favor_recall=True,
    )
    if not markdown:
        # Pages that are mostly navigation or lists can fail the main-content
        # heuristics; the baseline pass keeps whatever readable text exists.
        _, text, _ = trafilatura.baseline(html)
        markdown = text or ""

    meta: dict[str, str] = {}
    title = None
    # Only trust dates the page states in its markup; the extensive search guesses
    # from things like copyright lines and invents dates such as Jan 1.
    doc = extract_metadata(html, default_url=url, date_config={"extensive_search": False, "original_date": True})
    if doc is not None:
        title = doc.title
        for key in ("author", "date", "sitename", "description"):
            value = getattr(doc, key, None)
            if value and (key != "author" or _plausible_author(str(value))):
                meta[key] = str(value)
    return Extracted(markdown=markdown.strip(), title=title, meta=meta)


def extract_body(content_type: str, text: str, url: str, *, include_links: bool = False) -> Extracted:
    """Pick an extractor by content type."""
    ct = content_type.lower()
    if "json" in ct:
        try:
            pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except ValueError:
            pretty = text
        return Extracted(markdown=f"```json\n{pretty}\n```")
    if ct.startswith("text/plain") or "markdown" in ct or "csv" in ct:
        return Extracted(markdown=text.strip())
    if "xml" in ct and "html" not in ct:
        return Extracted(markdown=f"```xml\n{text.strip()}\n```")
    return extract_html(text, url, include_links=include_links)


def truncate(markdown: str, max_chars: int) -> tuple[str, bool]:
    """Cut to max_chars on a paragraph boundary when possible."""
    if max_chars <= 0 or len(markdown) <= max_chars:
        return markdown, False
    cut = markdown.rfind("\n\n", 0, max_chars)
    if cut < max_chars * 0.6:
        cut = max_chars
    return markdown[:cut].rstrip(), True

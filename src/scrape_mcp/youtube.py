"""YouTube metadata and transcripts via yt-dlp, with youtube-transcript-api as a fallback."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from curl_cffi.requests import AsyncSession

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtube-nocookie.com"}
PARAGRAPH_SECONDS = 30


class YouTubeError(Exception):
    """The video could not be read (unavailable, private, bad ID)."""


class YouTubeBlockedError(YouTubeError):
    """YouTube asked for a sign-in or bot check instead of serving the video."""


def is_youtube_url(url: str) -> bool:
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return host in _HOSTS


def parse_video_id(value: str) -> str:
    """Accept a bare 11-character ID or any common YouTube URL shape."""
    value = value.strip()
    if _ID.match(value):
        return value
    parsed = urlparse(value if "://" in value else "https://" + value)
    host = (parsed.hostname or "").lower()
    if host not in _HOSTS:
        raise ValueError(f"Not a YouTube URL: {value!r}")
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif parsed.path == "/watch":
        candidate = parse_qs(parsed.query).get("v", [""])[0]
    else:
        parts = [p for p in parsed.path.split("/") if p]
        candidate = parts[1] if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v") else ""
    if not _ID.match(candidate):
        raise ValueError(f"Could not find a video ID in {value!r}")
    return candidate


@dataclass
class Segment:
    start: float
    text: str


@dataclass
class Video:
    id: str
    info: dict
    segments: list[Segment] = field(default_factory=list)
    transcript_lang: str | None = None
    transcript_kind: str | None = None  # "manual" or "auto-generated"


# ---- caption track selection and parsing -------------------------------------------


def pick_track(info: dict, lang: str) -> tuple[str, str, list[dict]] | None:
    """Choose the best caption track: manual before auto-generated, the requested language
    first, then English, then the video's own language. Returns (lang, kind, formats)."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    wanted = [lang, "en", info.get("language") or ""]
    for tracks, kind in ((manual, "manual"), (auto, "auto-generated")):
        for want in filter(None, wanted):
            for code, formats in tracks.items():
                # Auto captions list every translation as "xx"; the original is "xx-orig".
                if code == want or code == f"{want}-orig" or code.split("-")[0] == want:
                    if formats:
                        return code, kind, formats
    for tracks, kind in ((manual, "manual"), (auto, "auto-generated")):
        for code, formats in tracks.items():
            if formats and code.endswith("-orig"):
                return code, kind, formats
    return None


def parse_json3(raw: str) -> list[Segment]:
    data = json.loads(raw)
    segments = []
    for event in data.get("events", []):
        text = "".join(seg.get("utf8", "") for seg in event.get("segs") or []).replace("\n", " ").strip()
        if text:
            segments.append(Segment(event.get("tStartMs", 0) / 1000, text))
    return segments


_VTT_TIME = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3}) -->")


def parse_vtt(raw: str) -> list[Segment]:
    segments: list[Segment] = []
    last = ""
    for block in re.split(r"\n\s*\n", raw):
        lines = block.strip().splitlines()
        for i, line in enumerate(lines):
            match = _VTT_TIME.match(line)
            if not match:
                continue
            h, m, s, ms = match.groups()
            start = int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
            text = re.sub(r"<[^>]+>", "", " ".join(lines[i + 1 :])).strip()
            # Auto captions repeat the previous line as each new word rolls in.
            if text and text != last:
                segments.append(Segment(start, text.removeprefix(last).strip() if text.startswith(last) else text))
                last = text
            break
    return [s for s in segments if s.text]


async def _download_track(formats: list[dict]) -> list[Segment]:
    by_ext = {f.get("ext"): f for f in formats if f.get("url")}
    for ext, parser in (("json3", parse_json3), ("vtt", parse_vtt)):
        fmt = by_ext.get(ext)
        if not fmt:
            continue
        async with AsyncSession(impersonate="chrome") as session:
            response = await session.get(fmt["url"], timeout=25)
        if response.status_code == 200 and response.text.strip():
            return parser(response.text)
    return []


# ---- fetching -----------------------------------------------------------------------


def _ydl_options() -> dict:
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
    }
    try:
        from deno import find_deno_bin

        options["js_runtimes"] = {"deno": {"path": find_deno_bin()}}
    except Exception:  # deno wheel missing for this platform: let yt-dlp search PATH
        pass
    return options


def _extract_info(video_id: str) -> dict:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    try:
        with YoutubeDL(_ydl_options()) as ydl:
            return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except DownloadError as exc:
        message = re.sub(r"^ERROR: (\[youtube\] \S+: )?", "", str(exc))
        message = message.split("; please report this issue")[0]
        if re.search(r"not a bot|sign in to confirm|429|captcha", message, re.I):
            raise YouTubeBlockedError(message) from exc
        raise YouTubeError(message) from exc


def _fallback_transcript(video_id: str, lang: str) -> tuple[list[Segment], str, str] | None:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import YouTubeTranscriptApiException

    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=list(dict.fromkeys([lang, "en"])))
    except YouTubeTranscriptApiException:
        return None
    segments = [Segment(s.start, s.text.replace("\n", " ")) for s in fetched.snippets]
    kind = "auto-generated" if fetched.is_generated else "manual"
    return segments, fetched.language_code, kind


async def get_video(video_id: str, *, lang: str = "en", transcript: bool = True) -> Video:
    info = await asyncio.to_thread(_extract_info, video_id)
    video = Video(id=video_id, info=info)
    if not transcript:
        return video
    track = pick_track(info, lang)
    if track:
        code, kind, formats = track
        try:
            video.segments = await _download_track(formats)
        except Exception:
            video.segments = []
        if video.segments:
            video.transcript_lang, video.transcript_kind = code.removesuffix("-orig"), kind
    if not video.segments:
        fallback = await asyncio.to_thread(_fallback_transcript, video_id, lang)
        if fallback:
            video.segments, video.transcript_lang, video.transcript_kind = fallback
    return video


# ---- formatting ---------------------------------------------------------------------


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _date(value: str | None) -> str | None:
    return f"{value[:4]}-{value[4:6]}-{value[6:]}" if value and len(value) == 8 else None


def paragraphs(segments: list[Segment], chapters: list[dict] | None = None) -> str:
    """Join caption lines into timestamped paragraphs, breaking at chapters or every ~30 s."""
    starts = sorted((c.get("start_time", 0), c.get("title", "")) for c in chapters or [])
    out: list[str] = []
    chunk: list[str] = []
    chunk_start = None
    next_chapter = 0

    def flush():
        if chunk:
            out.append(f"[{_clock(chunk_start)}] " + " ".join(chunk))

    for seg in segments:
        while next_chapter < len(starts) and seg.start >= starts[next_chapter][0]:
            flush()
            chunk, chunk_start = [], None
            out.append(f"### {starts[next_chapter][1]}")
            next_chapter += 1
        if chunk_start is None:
            chunk_start = seg.start
        elif seg.start - chunk_start >= PARAGRAPH_SECONDS and chunk and chunk[-1][-1:] in ".?!":
            flush()
            chunk, chunk_start = [], seg.start
        chunk.append(seg.text)
    flush()
    return "\n\n".join(out)


def format_video(video: Video, *, include_description: bool = True) -> tuple[str, str]:
    """Return (header and description, transcript) as markdown."""
    info = video.info
    lines = [f"# {info.get('title') or video.id}", ""]
    lines.append(f"- URL: https://www.youtube.com/watch?v={video.id}")
    if info.get("channel") or info.get("uploader"):
        lines.append(f"- Channel: {info.get('channel') or info.get('uploader')}")
    if _date(info.get("upload_date")):
        lines.append(f"- Published: {_date(info.get('upload_date'))}")
    if info.get("duration"):
        lines.append(f"- Duration: {_clock(info['duration'])}")
    stats = [
        f"{info[k]:,} {label}"
        for k, label in (("view_count", "views"), ("like_count", "likes"), ("comment_count", "comments"))
        if isinstance(info.get(k), int)
    ]
    if stats:
        lines.append(f"- Stats: {', '.join(stats)}")
    if info.get("tags"):
        lines.append(f"- Tags: {', '.join(info['tags'][:15])}")
    if video.segments:
        lines.append(f"- Transcript: {video.transcript_kind} captions, language {video.transcript_lang}")
    if info.get("chapters"):
        lines += ["", "## Chapters", ""]
        lines += [f"- {_clock(c.get('start_time', 0))} {c.get('title', '')}" for c in info["chapters"]]
    description = (info.get("description") or "").strip()
    if include_description and description:
        if len(description) > 3000:
            description = description[:3000].rstrip() + " …"
        lines += ["", "## Description", "", description]
    transcript = paragraphs(video.segments, info.get("chapters")) if video.segments else ""
    return "\n".join(lines), transcript

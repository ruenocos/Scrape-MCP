import json

import pytest

from scrape_mcp import scrape as scrape_module
from scrape_mcp import youtube as yt
from scrape_mcp.cache import Cache
from scrape_mcp.scrape import BlockedError, scrape, youtube

INFO = {
    "id": "dQw4w9WgXcQ",
    "title": "The 12 principles of animation",
    "channel": "Motion Studio",
    "upload_date": "20250314",
    "duration": 754,
    "view_count": 1234567,
    "like_count": 45678,
    "tags": ["animation", "motion design"],
    "description": "We walk through all twelve principles.",
    "language": "en",
    "chapters": [{"start_time": 0, "title": "Intro"}, {"start_time": 60, "title": "Squash and stretch"}],
    "subtitles": {},
    "automatic_captions": {
        "nl": [{"ext": "json3", "url": "https://yt/nl.json3"}],
        "en-orig": [{"ext": "json3", "url": "https://yt/en.json3"}, {"ext": "vtt", "url": "https://yt/en.vtt"}],
        "en": [{"ext": "json3", "url": "https://yt/en-tr.json3"}],
    },
}


@pytest.mark.parametrize(
    "value",
    [
        "dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
        "youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=abc",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RD",
    ],
)
def test_parse_video_id(value):
    assert yt.parse_video_id(value) == "dQw4w9WgXcQ"


@pytest.mark.parametrize("value", ["https://www.youtube.com/@MotionStudio", "https://vimeo.com/123", "short"])
def test_parse_video_id_rejects(value):
    with pytest.raises(ValueError):
        yt.parse_video_id(value)


def test_pick_track_prefers_manual_then_requested_language():
    info = dict(INFO, subtitles={"en": [{"ext": "vtt", "url": "m"}]})
    assert yt.pick_track(info, "en")[:2] == ("en", "manual")
    assert yt.pick_track(INFO, "nl")[:2] == ("nl", "auto-generated")
    assert yt.pick_track(INFO, "en")[:2] == ("en-orig", "auto-generated")
    assert yt.pick_track(INFO, "de")[:2] == ("en-orig", "auto-generated")


def test_pick_track_none_without_captions():
    assert yt.pick_track(dict(INFO, automatic_captions={}), "en") is None


def test_parse_json3():
    raw = json.dumps({"events": [
        {"tStartMs": 0, "segs": [{"utf8": "Hello "}, {"utf8": "there"}]},
        {"tStartMs": 1500, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 2000, "segs": [{"utf8": "general"}]},
    ]})
    segs = yt.parse_json3(raw)
    assert [(s.start, s.text) for s in segs] == [(0, "Hello there"), (2.0, "general")]


def test_parse_vtt_dedupes_rolling_auto_captions():
    raw = """WEBVTT

00:00:00.000 --> 00:00:02.000
squash and

00:00:02.000 --> 00:00:04.000
squash and stretch gives

00:01:05.500 --> 00:01:07.000
<c>weight</c> to motion
"""
    segs = yt.parse_vtt(raw)
    assert [s.text for s in segs] == ["squash and", "stretch gives", "weight to motion"]
    assert segs[-1].start == 65.5


def test_paragraphs_break_at_chapters():
    segs = [yt.Segment(0, "Welcome."), yt.Segment(10, "Today is about motion."), yt.Segment(61, "Squash it."), yt.Segment(70, "Then stretch.")]
    text = yt.paragraphs(segs, INFO["chapters"])
    assert text.split("\n\n") == [
        "### Intro",
        "[0:00] Welcome. Today is about motion.",
        "### Squash and stretch",
        "[1:01] Squash it. Then stretch.",
    ]


def test_format_video_header():
    video = yt.Video("dQw4w9WgXcQ", INFO, [yt.Segment(0, "Hi.")], "en", "auto-generated")
    header, transcript = yt.format_video(video)
    assert header.startswith("# The 12 principles of animation")
    for line in ["- Channel: Motion Studio", "- Published: 2025-03-14", "- Duration: 12:34",
                 "- Stats: 1,234,567 views, 45,678 likes", "- 1:00 Squash and stretch",
                 "- Transcript: auto-generated captions, language en"]:
        assert line in header
    assert transcript == "### Intro\n\n[0:00] Hi."


@pytest.fixture
def fake_youtube(monkeypatch):
    calls = []

    async def fake_get_video(video_id, *, lang="en", transcript=True):
        calls.append(video_id)
        segs = [yt.Segment(0, "Welcome."), yt.Segment(61, "Squash it.")] if transcript else []
        return yt.Video(video_id, INFO, segs, "en" if segs else None, "auto-generated" if segs else None)

    monkeypatch.setattr(yt, "get_video", fake_get_video)
    return calls


async def test_youtube_tool_output_and_cache(tmp_path, fake_youtube):
    cache = Cache(tmp_path / "c.db")
    out = await youtube("https://youtu.be/dQw4w9WgXcQ", cache=cache)
    assert "## Transcript" in out and "[1:01] Squash it." in out
    await youtube("dQw4w9WgXcQ", cache=cache)
    assert fake_youtube == ["dQw4w9WgXcQ"]
    details = await youtube("dQw4w9WgXcQ", cache=cache, transcript=False)
    assert "## Transcript" not in details and len(fake_youtube) == 2


async def test_scrape_routes_video_links_to_youtube(fake_youtube):
    out = await scrape("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert out.startswith("# The 12 principles of animation") and fake_youtube


async def test_scrape_treats_channel_pages_as_web_pages(monkeypatch, fake_youtube):
    from scrape_mcp.fetch import FetchResult

    async def fake_fetch(url, **_):
        return FetchResult(url, url, 200, "text/html", b"<html><title>Channel</title><p>About us</p></html>"), None

    monkeypatch.setattr(scrape_module, "fetch_http", fake_fetch)
    await scrape("https://www.youtube.com/@MotionStudio")
    assert fake_youtube == []


async def test_youtube_bot_check_is_reported_as_blocked(monkeypatch):
    async def blocked(video_id, **_):
        raise yt.YouTubeBlockedError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(yt, "get_video", blocked)
    with pytest.raises(BlockedError, match="bot check"):
        await youtube("dQw4w9WgXcQ")


async def test_get_video_falls_back_to_transcript_api(monkeypatch):
    monkeypatch.setattr(yt, "_extract_info", lambda vid: dict(INFO, automatic_captions={}))
    monkeypatch.setattr(yt, "_fallback_transcript", lambda vid, lang: ([yt.Segment(0, "From fallback.")], "en", "manual"))
    video = await yt.get_video("dQw4w9WgXcQ")
    assert video.segments[0].text == "From fallback." and video.transcript_kind == "manual"


def test_extract_info_maps_bot_check_error(monkeypatch):
    from yt_dlp.utils import DownloadError

    class FakeYDL:
        def __init__(self, opts):
            assert opts["skip_download"]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            raise DownloadError("ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm you're not a bot.")

    monkeypatch.setattr("yt_dlp.YoutubeDL", FakeYDL)
    with pytest.raises(yt.YouTubeBlockedError, match="not a bot"):
        yt._extract_info("dQw4w9WgXcQ")

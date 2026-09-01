"""YouTube search and audio resolution via yt-dlp (fallback when Invidious is unavailable)."""

from __future__ import annotations

import logging
import re
from typing import Any

import yt_dlp

from invidious_client import InvidiousError, search_videos

logger = logging.getLogger(__name__)

SEARCH_LIMIT = 15

YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "format": "bestaudio/best",
    "skip_download": True,
}


def parse_search_query(query: str) -> tuple[str, str | None]:
    """Split 'Artist - Song' into artist name and optional song hint."""
    if " - " in query:
        artist, song = query.split(" - ", 1)
        return artist.strip(), song.strip() or None
    return query.strip(), None


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.lower())


def _invidious_track(video: dict[str, Any]) -> dict[str, Any]:
    thumbnails = video.get("videoThumbnails") or []
    thumbnail = thumbnails[0].get("url", "") if thumbnails else ""
    return {
        "video_id": video["videoId"],
        "title": video.get("title", "Unknown"),
        "artist": video.get("author", "Unknown Artist"),
        "duration": int(video.get("lengthSeconds") or 0),
        "thumbnail": thumbnail,
        "audio_url": f"/api/stream?video_id={video['videoId']}",
    }


def _ytdlp_track(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "video_id": entry["id"],
        "title": entry.get("title", "Unknown"),
        "artist": entry.get("uploader") or entry.get("channel", "Unknown Artist"),
        "duration": int(entry.get("duration") or 0),
        "thumbnail": entry.get("thumbnail", ""),
        "audio_url": f"/api/stream?video_id={entry['id']}",
    }


def _search_ytdlp(query: str, limit: int = SEARCH_LIMIT) -> list[dict[str, Any]]:
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

    entries = [e for e in (result.get("entries") or []) if e]
    if not entries:
        raise InvidiousError(f"No videos found for '{query}'")

    return [_ytdlp_track(entry) for entry in entries]


def _pick_start_index(tracks: list[dict[str, Any]], song_hint: str | None) -> int:
    if not song_hint:
        return 0

    hint = _normalize_title(song_hint)
    for index, track in enumerate(tracks):
        title = _normalize_title(track["title"])
        if hint in title or title in hint:
            return index
    return 0


def search_tracks(query: str, limit: int = SEARCH_LIMIT) -> dict[str, Any]:
    """Search for an artist's songs and return a selectable track list."""
    artist, song_hint = parse_search_query(query)
    search_query = artist

    try:
        _, videos = search_videos(search_query, limit=limit)
        tracks = [_invidious_track(video) for video in videos]
        source = "invidious"
    except InvidiousError:
        logger.info("Invidious unavailable, falling back to yt-dlp for %r", search_query)
        tracks = _search_ytdlp(search_query, limit=limit)
        source = "youtube"

    if not tracks:
        raise InvidiousError(f"No videos found for '{artist}'")

    display_artist = tracks[0]["artist"]
    start_index = _pick_start_index(tracks, song_hint)

    return {
        "artist": display_artist,
        "query": query,
        "source": source,
        "start_index": start_index,
        "tracks": tracks,
    }


def get_stream_for_video(video_id: str) -> tuple[str, str]:
    """Return (audio_url, mime_type) for a YouTube video ID."""
    from invidious_client import get_audio_stream

    try:
        _, audio_url, _ = get_audio_stream(video_id)
        return audio_url, "audio/webm"
    except InvidiousError:
        return _get_ytdlp_audio_url(video_id)


def _get_ytdlp_audio_url(video_id: str) -> tuple[str, str]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)

    audio_url = info.get("url")
    if not audio_url:
        raise InvidiousError(f"Could not resolve audio stream for video {video_id}")

    mime = info.get("ext", "webm")
    return audio_url, mime

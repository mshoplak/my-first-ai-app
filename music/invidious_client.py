"""Invidious API client for YouTube search and audio stream resolution."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

INSTANCE_LIST_URL = "https://api.invidious.io/instances.json?sort_by=health"
REQUEST_TIMEOUT = 12
USER_AGENT = "ShoplakMusicPlayer/1.0"

# Fallback instances if the public list is unreachable.
STATIC_INSTANCES = [
    "https://invidious.f5.si",
    "https://invidious.tiekoetter.com",
    "https://yt.chocolatemoo53.com",
    "https://inv.nadeko.net",
]


class InvidiousError(Exception):
    """Raised when Invidious search or stream resolution fails."""


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


def _get_instances() -> list[str]:
    try:
        response = requests.get(INSTANCE_LIST_URL, timeout=8)
        response.raise_for_status()
        instances = []
        for entry in response.json():
            uri = entry[1].get("uri")
            if uri and entry[1].get("type") == "https":
                instances.append(uri.rstrip("/"))
        if instances:
            return instances
    except Exception as exc:
        logger.warning("Could not fetch Invidious instance list: %s", exc)
    return STATIC_INSTANCES


def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    with _session() as session:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()


def search_videos(query: str, limit: int = 15) -> tuple[str, list[dict[str, Any]]]:
    """Search Invidious and return up to *limit* video results."""
    last_error: Exception | None = None

    for instance in _get_instances():
        try:
            results = _get_json(
                f"{instance}/api/v1/search",
                params={"q": query, "type": "video"},
            )
            videos = [
                item
                for item in results
                if item.get("type") == "video" and item.get("videoId")
            ][:limit]
            if videos:
                return instance, videos
        except Exception as exc:
            logger.warning("Search failed on %s: %s", instance, exc)
            last_error = exc

    raise InvidiousError(
        f"No videos found for '{query}'"
        + (f" ({last_error})" if last_error else "")
    )


def search_video(query: str) -> tuple[str, dict[str, Any]]:
    """Search Invidious for the first matching video result."""
    instance, videos = search_videos(query, limit=1)
    return instance, videos[0]


def _is_audio_only(fmt: dict[str, Any]) -> bool:
    mime = fmt.get("type", "").lower()
    if "audio" not in mime:
        return False
    if "video" in mime and "audio" not in mime.split(";")[0]:
        return False
    return True


def _pick_best_audio_url(formats: list[dict[str, Any]]) -> str | None:
    audio_formats = [f for f in formats if _is_audio_only(f) and f.get("url")]
    if not audio_formats:
        return None

    audio_formats.sort(key=lambda f: int(f.get("bitrate") or 0), reverse=True)
    return audio_formats[0]["url"]


def get_audio_stream(
    video_id: str, preferred_instance: str | None = None
) -> tuple[str, str, dict[str, Any]]:
    """Resolve the best audio-only stream URL for a video (proxied via Invidious)."""
    instances = []
    if preferred_instance:
        instances.append(preferred_instance)
    instances.extend(i for i in _get_instances() if i != preferred_instance)

    last_error: Exception | None = None

    for instance in instances:
        try:
            data = _get_json(
                f"{instance}/api/v1/videos/{video_id}",
                params={"local": "true"},
            )
            audio_url = _pick_best_audio_url(data.get("adaptiveFormats", []))
            if not audio_url:
                audio_url = _pick_best_audio_url(data.get("formatStreams", []))
            if audio_url:
                return instance, audio_url, data
        except Exception as exc:
            logger.warning("Stream lookup failed on %s: %s", instance, exc)
            last_error = exc

    raise InvidiousError(
        f"Could not resolve audio stream for video {video_id}"
        + (f" ({last_error})" if last_error else "")
    )

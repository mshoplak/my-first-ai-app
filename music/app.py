"""Flask music player backed by Invidious/YouTube search."""

from __future__ import annotations

import logging

import requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from invidious_client import InvidiousError
from resolver import get_stream_for_video, search_tracks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

MIME_MAP = {
    "webm": "audio/webm",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Search query is required."}), 400

    try:
        return jsonify(search_tracks(query))
    except InvidiousError as exc:
        logger.info("Search failed for %r: %s", query, exc)
        return jsonify({"error": str(exc)}), 404
    except Exception:
        logger.exception("Unexpected error during search for %r", query)
        return jsonify({"error": "An unexpected error occurred."}), 500


@app.route("/api/stream")
def stream_audio():
    video_id = request.args.get("video_id", "").strip()
    if not video_id:
        return jsonify({"error": "video_id is required."}), 400

    try:
        audio_url, mime_hint = get_stream_for_video(video_id)
    except InvidiousError as exc:
        return jsonify({"error": str(exc)}), 404

    content_type = MIME_MAP.get(mime_hint, mime_hint)
    if not content_type.startswith("audio/"):
        content_type = "audio/webm"

    headers = {}
    if range_header := request.headers.get("Range"):
        headers["Range"] = range_header

    try:
        upstream = requests.get(audio_url, headers=headers, stream=True, timeout=30)
    except requests.RequestException as exc:
        logger.error("Upstream stream error for %s: %s", video_id, exc)
        return jsonify({"error": "Failed to fetch audio stream."}), 502

    excluded = {"content-encoding", "transfer-encoding", "connection"}
    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in excluded
    }

    if "Content-Type" not in response_headers:
        response_headers["Content-Type"] = content_type

    response_headers["Accept-Ranges"] = "bytes"

    @stream_with_context
    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return Response(
        generate(),
        status=upstream.status_code,
        headers=response_headers,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)

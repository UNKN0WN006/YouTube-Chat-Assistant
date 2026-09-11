from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

from .config import YOUTUBE_API_KEY


VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass
class TranscriptSegment:
    text: str
    start: float
    duration: float


def parse_video_id(value: str) -> str:
    """
    Accept common YouTube URL formats or a bare 11-character video id.
    """

    value = value.strip()

    if VIDEO_ID_RE.fullmatch(value):
        return value

    parsed = urlparse(
        value if "://" in value else f"https://{value}"
    )

    host = parsed.netloc.lower().replace("www.", "")

    candidate = ""

    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]

    elif host in {
        "youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    }:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]

        elif parsed.path.startswith(
            (
                "/shorts/",
                "/embed/",
                "/live/",
            )
        ):
            parts = parsed.path.strip("/").split("/")

            if len(parts) > 1:
                candidate = parts[1]

    if not VIDEO_ID_RE.fullmatch(candidate):
        raise ValueError(
            "That does not look like a valid YouTube video URL or id."
        )

    return candidate


def fetch_transcript(
    video_id: str,
) -> tuple[list[TranscriptSegment], str]:
    """
    Fetch captions and convert them into timestamp-preserving segments.
    """

    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()

    try:
        transcript = api.fetch(
            video_id,
            languages=[
                "en",
                "hi",
                "bn",
            ],
        )

    except Exception:
        # Prefer familiar languages first, then fall back to any available
        # caption track when none of those languages exists.
        transcript_list = api.list(video_id)

        first = next(
            iter(transcript_list),
            None,
        )

        if first is None:
            raise RuntimeError(
                "No usable transcript was found for this video."
            )

        transcript = first.fetch()

    segments = []

    for item in transcript:
        text = item.text.replace("\n", " ").strip()

        if not text:
            continue

        segments.append(
            TranscriptSegment(
                text=text,
                start=float(item.start),
                duration=float(item.duration),
            )
        )

    if not segments:
        raise RuntimeError(
            "The transcript is empty."
        )

    language = getattr(
        transcript,
        "language_code",
        "unknown",
    )

    return segments, language


async def fetch_video_metadata(
    video_id: str,
) -> dict:
    """
    Use the official YouTube Data API when configured.

    If no API key is available, fall back to YouTube's public oEmbed endpoint
    so basic title/channel/thumbnail information still works.
    """

    watch_url = (
        f"https://www.youtube.com/watch?v={video_id}"
    )

    fallback_thumbnail = (
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    )

    async with httpx.AsyncClient(
        timeout=8.0,
        follow_redirects=True,
    ) as client:

        if YOUTUBE_API_KEY:
            try:
                response = await client.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={
                        "part": "snippet,contentDetails",
                        "id": video_id,
                        "key": YOUTUBE_API_KEY,
                    },
                )

                response.raise_for_status()

                items = response.json().get(
                    "items",
                    [],
                )

                if items:
                    snippet = items[0].get(
                        "snippet",
                        {},
                    )

                    thumbnails = snippet.get(
                        "thumbnails",
                        {},
                    )

                    thumbnail = (
                        thumbnails.get("high", {}).get("url")
                        or thumbnails.get("medium", {}).get("url")
                        or thumbnails.get("default", {}).get("url")
                        or fallback_thumbnail
                    )

                    return {
                        "title": snippet.get(
                            "title",
                            "YouTube video",
                        ),
                        "channel": snippet.get(
                            "channelTitle",
                            "",
                        ),
                        "thumbnail": thumbnail,
                    }

            except httpx.HTTPError:
                # Metadata failure should not block transcript/RAG functionality.
                pass

        try:
            response = await client.get(
                "https://www.youtube.com/oembed",
                params={
                    "url": watch_url,
                    "format": "json",
                },
            )

            response.raise_for_status()

            data = response.json()

            return {
                "title": data.get(
                    "title",
                    "YouTube video",
                ),
                "channel": data.get(
                    "author_name",
                    "",
                ),
                "thumbnail": data.get(
                    "thumbnail_url",
                    fallback_thumbnail,
                ),
            }

        except httpx.HTTPError:
            # Basic fallback keeps video loading usable even if metadata fails.
            return {
                "title": "YouTube video",
                "channel": "",
                "thumbnail": fallback_thumbnail,
            }
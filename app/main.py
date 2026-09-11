from __future__ import annotations

import logging

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .brand import brand_logo_data, brand_state, save_logo
from .config import STATIC_DIR
from .llm import answer_question
from .models import ChatRequest, LoadVideoRequest
from .rag import stamp, store
from .youtube_service import (
    fetch_transcript,
    fetch_video_metadata,
    parse_video_id,
)


logger = logging.getLogger("youtube-assistant")


app = FastAPI(
    title="YouTube Assistant",
    version="2.1.0",
)


# Standalone development uses localhost. The regex also allows the optional
# Chrome extension to talk to the same backend during local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_origin_regex=r"^chrome-extension://.*$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Creating the directory here lets API routes still start even if the
# frontend has not been copied into the project yet.
STATIC_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)


@app.get("/")
def home():
    index_file = STATIC_DIR / "index.html"

    if not index_file.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Frontend files are missing. "
                "Copy the static/ directory into the project first."
            ),
        )

    return FileResponse(index_file)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service": "youtube-assistant",
        "version": "2.1.0",
    }


# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------


@app.get("/api/brand")
def get_brand():
    return brand_state()


@app.get("/api/brand/logo-data")
def get_brand_logo_data():
    try:
        return brand_logo_data()

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.post("/api/brand/logo")
async def change_logo(
    file: UploadFile = File(...),
):
    try:
        return await save_logo(file)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# YouTube video loading
# ---------------------------------------------------------------------------


def _transcript_error(
    video_id: str,
    exc: Exception,
) -> HTTPException:
    """
    Convert transcript-library failures into useful API responses.

    We use the exception name instead of importing private error classes from
    youtube-transcript-api, which keeps this layer less coupled to the package.
    """

    error_name = type(exc).__name__

    logger.warning(
        "Transcript request failed: video=%s error=%s details=%s",
        video_id,
        error_name,
        exc,
    )

    if error_name in {
        "RequestBlocked",
        "IpBlocked",
    }:
        return HTTPException(
            status_code=503,
            detail=(
                "YouTube blocked transcript requests from this server. "
                "This commonly happens when the backend is running from a "
                "cloud environment such as GitHub Codespaces. "
                "Run the backend locally or configure a supported proxy."
            ),
        )

    if error_name == "TranscriptsDisabled":
        return HTTPException(
            status_code=422,
            detail=(
                "Captions are disabled for this video."
            ),
        )

    if error_name == "NoTranscriptFound":
        return HTTPException(
            status_code=422,
            detail=(
                "The video is available, but no usable transcript "
                "track was found."
            ),
        )

    if error_name == "VideoUnavailable":
        return HTTPException(
            status_code=404,
            detail=(
                "This YouTube video is unavailable, private, "
                "or restricted."
            ),
        )

    if error_name in {
        "AgeRestricted",
        "VideoUnplayable",
    }:
        return HTTPException(
            status_code=422,
            detail=(
                "YouTube is not exposing a transcript for this "
                "restricted video."
            ),
        )

    return HTTPException(
        status_code=502,
        detail=(
            f"Transcript request failed: {error_name}. "
            "Check the backend terminal for details."
        ),
    )


@app.post("/api/video/load")
async def load_video(
    request: LoadVideoRequest,
):
    # URL parsing is intentionally separate from transcript retrieval so the
    # frontend can distinguish an invalid link from a YouTube/network failure.
    try:
        video_id = parse_video_id(
            request.url_or_id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    try:
        # youtube-transcript-api is synchronous, so move its network work off
        # the main async event loop.
        segments, language = await run_in_threadpool(
            fetch_transcript,
            video_id,
        )

    except Exception as exc:
        raise _transcript_error(
            video_id,
            exc,
        ) from exc

    try:
        # Embedding generation can be CPU-heavy and may download the model on
        # the first request, so it also runs outside the main event loop.
        chunk_count = await run_in_threadpool(
            store.add_video,
            video_id,
            segments,
        )

    except Exception as exc:
        logger.exception(
            "Could not build RAG index for video %s",
            video_id,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "The transcript loaded, but the assistant could not "
                "build its search index."
            ),
        ) from exc

    try:
        metadata = await fetch_video_metadata(
            video_id,
        )

    except Exception as exc:
        # Metadata is useful for the UI, but it should never prevent RAG from
        # working when the transcript was fetched successfully.
        logger.warning(
            "Metadata request failed: video=%s error=%s",
            video_id,
            type(exc).__name__,
        )

        metadata = {
            "title": "YouTube video",
            "channel": "",
            "thumbnail": (
                f"https://i.ytimg.com/vi/"
                f"{video_id}/hqdefault.jpg"
            ),
        }

    duration = (
        segments[-1].start
        + segments[-1].duration
    )

    return {
        "ok": True,
        "video_id": video_id,
        "language": language,
        "chunks": chunk_count,
        "duration": duration,
        **metadata,
    }


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


@app.get(
    "/api/video/{video_id}/transcript"
)
def get_transcript(
    video_id: str,
):
    if video_id not in store.segments:
        raise HTTPException(
            status_code=404,
            detail=(
                "Load the video before requesting its transcript."
            ),
        )

    segments = store.segments[
        video_id
    ]

    return {
        "video_id": video_id,
        "segments": [
            {
                "text": segment.text,
                "start": segment.start,
                "duration": segment.duration,
                "stamp": stamp(
                    segment.start
                ),
            }
            for segment in segments
        ],
    }


# ---------------------------------------------------------------------------
# Video chat
# ---------------------------------------------------------------------------


@app.post("/api/chat")
def chat(
    request: ChatRequest,
):
    if not store.has_video(
        request.video_id
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Load the video before asking questions."
            ),
        )

    focus_time = (
        request.current_time
        if request.focus_current
        else None
    )

    try:
        matches = store.retrieve(
            request.video_id,
            request.question,
            current_time=focus_time,
        )

    except Exception as exc:
        logger.exception(
            "Retrieval failed for video %s",
            request.video_id,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "The assistant could not search the video transcript."
            ),
        ) from exc

    history = [
        turn.model_dump()
        for turn in request.history
    ]

    try:
        answer = answer_question(
            request.question,
            matches,
            history,
        )

    except Exception as exc:
        logger.exception(
            "Language model request failed"
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "The language model request failed. "
                "Check HF_TOKEN and HF_MODEL."
            ),
        ) from exc

    sources = [
        {
            "start": match.chunk.start,
            "end": match.chunk.end,
            "stamp": stamp(
                match.chunk.start
            ),
            "preview": (
                match.chunk.text[:180]
            ),
            "score": round(
                match.score,
                4,
            ),
        }
        for match in matches[:4]
    ]

    return {
        "ok": True,
        "answer": answer,
        "sources": sources,
    }
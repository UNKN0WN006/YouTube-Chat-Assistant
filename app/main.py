from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .brand import brand_logo_data, brand_state, save_logo
from .config import STATIC_DIR
from .llm import answer_question
from .models import ChatRequest, LoadVideoRequest
from .rag import stamp, store
from .youtube_service import fetch_transcript, fetch_video_metadata, parse_video_id


app = FastAPI(title="YouTube Assistant", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "service": "youtube-assistant"}


@app.get("/api/brand")
def get_brand():
    return brand_state()


@app.get("/api/brand/logo-data")
def get_brand_logo_data():
    try:
        return brand_logo_data()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/brand/logo")
async def change_logo(file: UploadFile = File(...)):
    try:
        return await save_logo(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/video/load")
async def load_video(request: LoadVideoRequest):
    try:
        video_id = parse_video_id(request.url_or_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        segments, language = fetch_transcript(video_id)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "I could not load captions for this video. "
                "Try another public video with captions enabled."
            ),
        ) from exc

    chunk_count = store.add_video(video_id, segments)

    try:
        metadata = await fetch_video_metadata(video_id)
    except Exception:
        metadata = {
            "title": "YouTube video",
            "channel": "",
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        }

    duration = segments[-1].start + segments[-1].duration
    return {
        "ok": True,
        "video_id": video_id,
        "language": language,
        "chunks": chunk_count,
        "duration": duration,
        **metadata,
    }


@app.get("/api/video/{video_id}/transcript")
def get_transcript(video_id: str):
    if video_id not in store.segments:
        raise HTTPException(status_code=404, detail="Load the video first.")

    return {
        "video_id": video_id,
        "segments": [
            {
                "text": segment.text,
                "start": segment.start,
                "duration": segment.duration,
                "stamp": stamp(segment.start),
            }
            for segment in store.segments[video_id]
        ],
    }


@app.post("/api/chat")
def chat(request: ChatRequest):
    if not store.has_video(request.video_id):
        raise HTTPException(status_code=404, detail="Load the video first.")

    focus_time = request.current_time if request.focus_current else None
    matches = store.retrieve(
        request.video_id,
        request.question,
        current_time=focus_time,
    )

    history = [turn.model_dump() for turn in request.history]

    try:
        answer = answer_question(request.question, matches, history)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The language model request failed. Check HF_TOKEN/HF_MODEL.",
        ) from exc

    sources = [
        {
            "start": match.chunk.start,
            "end": match.chunk.end,
            "stamp": stamp(match.chunk.start),
            "preview": match.chunk.text[:180],
            "score": round(match.score, 4),
        }
        for match in matches[:4]
    ]

    return {"ok": True, "answer": answer, "sources": sources}

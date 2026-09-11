from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from typing import Any

from .config import EMBEDDING_MODEL
from .youtube_service import TranscriptSegment

@dataclass
class Chunk:
    text: str
    start: float
    end: float

@dataclass
class Match:
    chunk: Chunk
    score: float

def stamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def make_chunks(
    segments: list[TranscriptSegment],
    max_chars: int = 1500,
    overlap_segments: int = 2,
) -> list[Chunk]:
    """Group neighboring caption lines while preserving a useful time range."""
    chunks: list[Chunk] = []
    i = 0

    while i < len(segments):
        batch: list[TranscriptSegment] = []
        size = 0
        j = i

        while j < len(segments):
            next_text = segments[j].text
            if batch and size + len(next_text) + 1 > max_chars:
                break
            batch.append(segments[j])
            size += len(next_text) + 1
            j += 1

        first = batch[0]
        last = batch[-1]
        chunks.append(
            Chunk(
                text=" ".join(item.text for item in batch),
                start=first.start,
                end=last.start + last.duration,
            )
        )

        if j >= len(segments):
            break
        i = max(i + 1, j - overlap_segments)

    return chunks


class VideoIndex:
    def __init__(self, model: Any, chunks: list[Chunk]):
        self.chunks = chunks
        # Normalized vectors let a dot product behave like cosine similarity.
        self.embeddings = model.encode(
            [chunk.text for chunk in chunks],
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    def search(
        self,
        model: Any,
        question: str,
        top_k: int = 5,
        focus_time: float | None = None,
    ) -> list[Match]:
        query = model.encode(
            [question],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]

        scores = self.embeddings @ query

        if focus_time is not None:
            # Keep semantic relevance dominant, but gently prefer context near playback.
            centers = np.array([(c.start + c.end) / 2 for c in self.chunks])
            distance = np.abs(centers - focus_time)
            time_bonus = np.exp(-distance / 90.0) * 0.25
            scores = scores + time_bonus

        indices = np.argsort(scores)[::-1][:top_k]
        return [Match(self.chunks[i], float(scores[i])) for i in indices]


class RagStore:
    def __init__(self):
        self.model: Any | None = None
        self.indexes: dict[str, VideoIndex] = {}
        self.segments: dict[str, list[TranscriptSegment]] = {}

    def _embedding_model(self) -> Any:
        if self.model is None:
            # Load the embedding model only when the first video is indexed.
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(EMBEDDING_MODEL)
        return self.model

    def add_video(self, video_id: str, segments: list[TranscriptSegment]) -> int:
        chunks = make_chunks(segments)
        self.indexes[video_id] = VideoIndex(self._embedding_model(), chunks)
        self.segments[video_id] = segments
        return len(chunks)

    def has_video(self, video_id: str) -> bool:
        return video_id in self.indexes

    def retrieve(
        self,
        video_id: str,
        question: str,
        current_time: float | None = None,
    ) -> list[Match]:
        index = self.indexes[video_id]
        return index.search(
            self._embedding_model(),
            question,
            top_k=5,
            focus_time=current_time,
        )

store = RagStore()

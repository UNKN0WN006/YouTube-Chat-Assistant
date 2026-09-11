from pydantic import BaseModel, Field


class LoadVideoRequest(BaseModel):
    url_or_id: str = Field(min_length=3, max_length=500)


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    video_id: str
    question: str = Field(min_length=1, max_length=2000)
    current_time: float | None = None
    focus_current: bool = False
    history: list[ChatTurn] = Field(default_factory=list)

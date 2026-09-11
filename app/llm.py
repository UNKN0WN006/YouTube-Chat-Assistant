from __future__ import annotations

from huggingface_hub import InferenceClient

from .config import HF_MODEL, HF_TOKEN
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .rag import Match, stamp

def _fallback_answer(matches: list[Match]) -> str:
    """Useful demo mode when no Hugging Face token has been configured."""
    if not matches:
        return "I could not find a relevant part of the transcript."

    best = matches[:3]
    lines = [
        "No LLM token is configured yet, so here are the most relevant transcript parts:",
        "",
    ]
    for match in best:
        text = match.chunk.text
        if len(text) > 280:
            text = text[:277].rstrip() + "..."
        lines.append(f"[{stamp(match.chunk.start)}] {text}")
    return "\n\n".join(lines)


def answer_question(question: str, matches: list[Match], history: list[dict]) -> str:
    if not HF_TOKEN:
        return _fallback_answer(matches)

    client = InferenceClient(provider="auto", api_key=HF_TOKEN)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-4:]:
        if turn.get("role") in {"user", "assistant"} and turn.get("content"):
            messages.append(
                {"role": turn["role"], "content": turn["content"][:2500]}
            )

    messages.append(
        {
            "role": "user",
            "content": build_user_prompt(question, matches),
        }
    )

    response = client.chat.completions.create(
        model=HF_MODEL,
        messages=messages,
        max_tokens=500,
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()

from .rag import Match, stamp

SYSTEM_PROMPT = """You are a YouTube study assistant.
Use only the transcript evidence supplied to you.
If the transcript does not support an answer, say that clearly.
Prefer a direct answer first, then a short explanation.
When a timestamp is useful, cite it in square brackets like [03:18].
Do not invent quotes, facts, speakers, or timestamps.
""".strip()


def build_context(matches: list[Match]) -> str:
    blocks = []
    for match in matches:
        blocks.append(
            f"[{stamp(match.chunk.start)} - {stamp(match.chunk.end)}]\n"
            f"{match.chunk.text}"
        )
    return "\n\n".join(blocks)


def build_user_prompt(question: str, matches: list[Match]) -> str:
    return f"""Transcript evidence:
{build_context(matches)}

Question: {question}

Answer from the evidence above only.""".strip()

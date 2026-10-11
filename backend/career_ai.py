from __future__ import annotations

import json
from typing import Any

from backend.ai import AIProviderError, MentorAIConfig, MENTOR_PROVIDERS


_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "feedback": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "improvements": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "feedback", "strengths", "improvements"],
}


def _parse_feedback(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith(fence):
            lines = lines[1:]
        if lines and lines[-1].strip() == fence:
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise AIProviderError("The career feedback model returned invalid JSON.")
        try:
            parsed, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            raise AIProviderError("The career feedback model returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise AIProviderError("The career feedback model returned an invalid structure.")

    score = parsed.get("score", 0)
    try:
        score = max(0, min(100, int(score)))
    except (TypeError, ValueError):
        score = 0
    feedback = str(parsed.get("feedback") or "").strip()
    strengths = [str(item).strip() for item in (parsed.get("strengths") or []) if str(item).strip()]
    improvements = [str(item).strip() for item in (parsed.get("improvements") or []) if str(item).strip()]
    if not feedback:
        raise AIProviderError("The career feedback model returned no feedback text.")
    return {
        "score": score,
        "feedback": feedback,
        "strengths": strengths[:5],
        "improvements": improvements[:5],
    }


def generate_interview_feedback(
    *,
    question: str,
    answer: str,
    rubric: list[str],
    question_type: str,
) -> dict[str, Any]:
    """Evaluate an interview answer through the shared hardened AI provider layer."""
    config = MentorAIConfig.from_env()
    provider = MENTOR_PROVIDERS[config.provider]

    system = (
        "You are CodeMentor AI's career interview evaluator. "
        "Evaluate the candidate's answer, not their grammar alone. "
        "Reward correctness, structure, concrete evidence, trade-off reasoning, and role relevance. "
        "Return JSON only with score (0-100), feedback, strengths, improvements."
    )
    user = {
        "question_type": question_type,
        "question": question,
        "candidate_answer": answer,
        "evaluation_rubric": rubric,
    }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]

    raw = provider.complete(
        model=config.model,
        messages=messages,
        response_schema=_JSON_SCHEMA,
        config=config,
    )
    return _parse_feedback(raw)


def heuristic_interview_feedback(*, question: str, answer: str, rubric: list[str], question_type: str) -> dict[str, Any]:
    """Deterministic fallback so interview mode remains usable without a model."""
    normalized = answer.casefold()
    rubric_hits = [item for item in rubric if item.casefold() in normalized]
    sentences = [chunk.strip() for chunk in answer.replace("!", ".").replace("?", ".").split(".") if chunk.strip()]
    score = 20
    score += min(45, len(rubric_hits) * 9)
    score += 15 if len(answer) >= 180 else 7 if len(answer) >= 80 else 0
    score += 10 if len(sentences) >= 3 else 0
    score = min(100, score)

    strengths: list[str] = []
    if rubric_hits:
        strengths.append("You addressed key evaluation points: " + ", ".join(rubric_hits[:3]) + ".")
    if len(answer) >= 180:
        strengths.append("The answer has enough detail to support a substantive interview discussion.")
    if question_type == "behavioral" and any(term in normalized for term in ("i did", "i built", "i led", "i learned")):
        strengths.append("You used first-person ownership language rather than describing the situation passively.")

    improvements = []
    if not rubric_hits:
        improvements.append("Address the question's core concepts explicitly and connect them to your reasoning.")
    if len(answer) < 120:
        improvements.append("Add one concrete example, decision or result instead of stopping at a high-level statement.")
    if question_type == "behavioral" and not any(term in normalized for term in ("result", "impact", "outcome")):
        improvements.append("Close with the measurable outcome or what changed because of your actions.")
    if question_type == "technical" and not any(term in normalized for term in ("because", "trade-off", "complexity", "latency", "correct")):
        improvements.append("Explain why your approach works and name the main trade-off or complexity.")
    if not improvements:
        improvements.append("Tighten the answer into a clear structure: approach, evidence, trade-off, result.")

    return {
        "score": score,
        "feedback": (
            f"Your answer covers {len(rubric_hits)} of {len(rubric)} rubric signals. "
            "Use the improvement points to make the response more evidence-based and interview-ready."
        ),
        "strengths": strengths[:5] or ["You attempted the question directly."],
        "improvements": improvements[:5],
    }

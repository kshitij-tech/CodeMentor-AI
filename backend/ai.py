from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

GEMINI_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"

class AIProviderError(RuntimeError):
    pass

def _extract_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()
    chunks: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    text = "\n".join(chunks).strip()
    if not text:
        raise AIProviderError("The AI provider returned no text.")
    return text

def mentor_response(*, problem: dict[str, Any], language: str, code: str, execution: dict[str, Any] | None, action: str, question: str | None, hint_level: int) -> str:
    api_key = os.getenv("AI_API_KEY", "").strip()
    if not api_key:
        raise AIProviderError("AI_API_KEY is not configured. Add your provider API key to the backend environment.")
    model = os.getenv("AI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    constraints = "\n".join("- " + str(x) for x in (problem.get("constraints") or []))
    execution_text = json.dumps(execution or {"status": "not_run", "results": []}, indent=2)
    context = """
PROBLEM
Title: {title}
Difficulty: {difficulty}
Topics: {topics}
Description: {description}
Constraints:
{constraints}
Examples:
{examples}

LANGUAGE
{language}

USER CODE
```
{code}
```

EXECUTION RESULT
{execution_text}

REQUEST TYPE
{action}

HINT LEVEL
{hint_level}

USER QUESTION
{question}
""".format(
        title=problem["title"],
        difficulty=problem["difficulty"],
        topics=", ".join(problem.get("topics") or []),
        description=problem["description"],
        constraints=constraints,
        examples=json.dumps(problem.get("examples") or [], indent=2),
        language=language,
        code=code,
        execution_text=execution_text,
        action=action,
        hint_level=hint_level,
        question=question or "(none)",
    )

    instructions = """
You are CodeMentor AI, a patient coding-interview mentor.

Ground every diagnosis in the supplied problem, user code, and execution result.
The execution engine is the authority for correctness. Never claim that code is correct or incorrect solely because you reasoned about it when an execution result is available.
When execution says Accepted, do not invent a hidden failing case.
When execution says Wrong Answer, Runtime Error, or Time Limit Exceeded, explain the evidence and likely cause.
For hints, do not reveal a complete solution. Respect the requested hint level:
1 = concept, 2 = direction, 3 = edge case, 4 = implementation guidance.
For complexity requests, state time and space complexity of the user's current approach when inferable, and distinguish inference from measured runtime.
For debugging, point to the relevant code behavior and a concrete next step, but do not silently rewrite the solution.
Be concise and educational.
""".strip()

    body = {
        "systemInstruction": {
            "parts": [{"text": instructions}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": context.strip()}],
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 700,
        },
    }

    request = urllib.request.Request(
        GEMINI_GENERATE_URL.format(model=model),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise AIProviderError("AI provider request failed ({}): {}".format(exc.code, detail)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AIProviderError("Unable to reach the AI provider.") from exc
    candidates = payload.get("candidates") or []
    if not candidates:
        raise AIProviderError("Gemini returned no candidate response.")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    texts = [part.get("text", "") for part in parts if part.get("text")]
    answer = "\n".join(texts).strip()
    if not answer:
        raise AIProviderError("Gemini returned an empty response.")
    return answer

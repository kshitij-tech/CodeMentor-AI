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

def _parse_mentor_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIProviderError("The mentor returned invalid structured output.") from exc

    if not isinstance(parsed, dict) or not isinstance(parsed.get("answer"), str):
        raise AIProviderError("The mentor returned an invalid response structure.")

    error_line = parsed.get("error_line")
    if error_line is not None:
        try:
            error_line = int(error_line)
        except (TypeError, ValueError):
            error_line = None
        if error_line is not None and error_line < 1:
            error_line = None

    patch = parsed.get("patch")
    if patch is not None:
        if not isinstance(patch, dict):
            patch = None
        else:
            try:
                start_line = int(patch.get("start_line"))
                end_line = int(patch.get("end_line"))
                replacement = str(patch.get("replacement", ""))
                if (
                    start_line < 1
                    or end_line < start_line
                    or end_line - start_line + 1 > 8
                    or len(replacement) > 1600
                ):
                    patch = None
                else:
                    patch = {
                        "start_line": start_line,
                        "end_line": end_line,
                        "replacement": replacement,
                    }
            except (TypeError, ValueError):
                patch = None

    return {
        "answer": parsed["answer"].strip(),
        "error_line": error_line,
        "patch": patch,
    }


def mentor_response(*, problem: dict[str, Any], language: str, code: str, execution: dict[str, Any] | None, action: str, question: str | None, hint_level: int) -> dict[str, Any]:
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("AI_API_KEY") or "").strip()
    if not api_key:
        raise AIProviderError("GEMINI_API_KEY is not configured. Add your Gemini API key to the backend environment.")
    model = os.getenv("AI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    model_aliases = {
        "2.5 flash": "gemini-2.5-flash",
        "gemini 2.5 flash": "gemini-2.5-flash",
        "gemini-2.5-flash": "gemini-2.5-flash",
        "gemini 2.5 flash lite": "gemini-2.5-flash-lite",
        "2.5 flash lite": "gemini-2.5-flash-lite",
        "gemini 2.5 pro": "gemini-2.5-pro",
        "2.5 pro": "gemini-2.5-pro",
    }
    model = model_aliases.get(model.lower(), model)
    if " " in model:
        raise AIProviderError(
            "Invalid AI_MODEL value. Use a Gemini model id such as 'gemini-2.5-flash'."
        )
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
Return JSON only with exactly these fields:
answer: a clean plain-text conversational response with no Markdown.
error_line: the 1-based line number in the user code that is most directly responsible for the error, or null if no specific line can be identified.
patch: null unless the request type is modify and a small local code change would help. When present, patch must contain start_line, end_line, and replacement. The replacement must be only the minimal lines needed to demonstrate or fix the issue, not a complete solution.

The mentor must prioritize teaching. Do not solve the entire problem for the user. Explain what to inspect and what concept to apply. Only produce a patch when the user explicitly asks for a code modification or the request type is modify. Even then, keep it minimal and tell the user to understand and try the change themselves before applying it.
Never silently rewrite the user code. The UI will require explicit user action before a patch is applied.
Keep the answer concise, educational, and conversational.
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
            "maxOutputTokens": 900,
            "responseMimeType": "application/json",
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
    result = _parse_mentor_response(answer)
    if action != "modify":
        result["patch"] = None
    return result

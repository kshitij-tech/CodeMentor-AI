from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

GEMINI_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_FALLBACK_MODEL = "gemini-2.5-flash-lite"

class AIProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable

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

    # Gemini can occasionally wrap otherwise valid JSON in a Markdown fence.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    parsed: Any = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Be tolerant of harmless prose before/after the JSON object.
        object_start = text.find("{")
        if object_start >= 0:
            try:
                parsed, _ = json.JSONDecoder().raw_decode(text[object_start:])
            except json.JSONDecodeError as exc:
                raise AIProviderError("The mentor returned invalid structured output.") from exc
        else:
            raise AIProviderError("The mentor returned invalid structured output.")

    if not isinstance(parsed, dict):
        raise AIProviderError("The mentor returned an invalid response structure.")

    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise AIProviderError("The mentor response is missing a valid 'answer' field.")

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
        "answer": answer.strip(),
        "error_line": error_line,
        "patch": patch,
    }
def _normalize_model(model: str) -> str:
    model_aliases = {
        "2.5 flash": "gemini-2.5-flash",
        "gemini 2.5 flash": "gemini-2.5-flash",
        "gemini-2.5-flash": "gemini-2.5-flash",
        "gemini 2.5 flash lite": "gemini-2.5-flash-lite",
        "2.5 flash lite": "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
        "gemini 2.5 pro": "gemini-2.5-pro",
        "2.5 pro": "gemini-2.5-pro",
        "gemini-2.5-pro": "gemini-2.5-pro",
    }
    normalized = model.strip() or DEFAULT_MODEL
    normalized = model_aliases.get(normalized.lower(), normalized)
    if " " in normalized:
        raise AIProviderError(
            "Invalid AI_MODEL value. Use a Gemini model id such as 'gemini-2.5-flash'."
        )
    return normalized

def _request_gemini(*, model: str, api_key: str, body: dict[str, Any], max_retries: int) -> dict[str, Any]:
    last_error: str | None = None
    for attempt in range(max_retries + 1):
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
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1200]
            last_error = "AI provider request failed ({}): {}".format(exc.code, detail)
            if exc.code not in {500, 502, 503, 504}:
                raise AIProviderError(last_error) from exc
            if attempt >= max_retries:
                raise AIProviderError(last_error, retryable=True) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = "Unable to reach the AI provider."
            if attempt >= max_retries:
                raise AIProviderError(last_error, retryable=True) from exc
        time.sleep(min(8.0, 2 ** attempt))
    raise AIProviderError(last_error or "AI provider request failed after retries.")

def mentor_response(*, problem: dict[str, Any], language: str, code: str, execution: dict[str, Any] | None, action: str, question: str | None, hint_level: int, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("AI_API_KEY") or "").strip()
    if not api_key:
        raise AIProviderError("GEMINI_API_KEY is not configured. Add your Gemini API key to the backend environment.")
    model = _normalize_model(os.getenv("AI_MODEL", DEFAULT_MODEL))
    fallback_model = _normalize_model(os.getenv("AI_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL))

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

CONVERSATION HISTORY
{history_text}

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
        history_text=json.dumps(history or [], ensure_ascii=False, indent=2),
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

A previous conversation may be provided. Use it to maintain continuity and avoid asking for information the user already supplied. Treat the current request and current code as authoritative over older messages.
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
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "answer": {
                        "type": "STRING",
                        "description": "The concise plain-text mentor response.",
                    },
                    "error_line": {
                        "type": ["INTEGER", "NULL"],
                        "description": "The 1-based user-code line most directly responsible for an observed error, or null.",
                    },
                    "patch": {
                        "type": ["OBJECT", "NULL"],
                        "description": "A small optional code patch. Use null unless the request explicitly asks for a modification.",
                        "properties": {
                            "start_line": {"type": "INTEGER"},
                            "end_line": {"type": "INTEGER"},
                            "replacement": {"type": "STRING"},
                        },
                        "required": ["start_line", "end_line", "replacement"],
                        "additionalProperties": False,
                    },
                },
                "required": ["answer", "error_line", "patch"],
                "additionalProperties": False,
            },
        },
    }

    try:
        payload = _request_gemini(
            model=model,
            api_key=api_key,
            body=body,
            max_retries=2,
        )
    except AIProviderError as primary_error:
        if not primary_error.retryable or fallback_model == model:
            raise
        try:
            payload = _request_gemini(
                model=fallback_model,
                api_key=api_key,
                body=body,
                max_retries=1,
            )
        except AIProviderError:
            raise primary_error

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

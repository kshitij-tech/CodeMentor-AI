from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
LMSTUDIO_CHAT_URL = "http://localhost:1234/v1/chat/completions"
MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "qwen3:4b"
DEFAULT_LMSTUDIO_MODEL = "mistralai/ministral-3-3b"
DEFAULT_FALLBACK_MODEL = ""

class AIProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code

def _strip_visible_thinking(text: str) -> str:
    """Remove reasoning blocks some local models may include in message content."""
    cleaned = text.strip()

    while True:
        lower = cleaned.lower()
        start = lower.find("<think>")
        if start < 0:
            break
        end = lower.find("</think>", start + len("<think>"))
        if end < 0:
            # Do not leak an unclosed reasoning block into the UI.
            cleaned = cleaned[:start].rstrip()
            break
        cleaned = (cleaned[:start] + cleaned[end + len("</think>"):]).strip()

    return cleaned


def _extract_message_text(payload: dict[str, Any], provider: str) -> str:
    if provider == "ollama":
        message = payload.get("message") or {}
    else:
        choices = payload.get("choices") or []
        if not choices:
            raise AIProviderError(f"{provider.capitalize()} returned no candidate response.")
        message = choices[0].get("message") or {}

    # Ollama may return reasoning in a separate thinking field.
    # Only content is shown to the user.
    content = message.get("content")

    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        text = "\n".join(chunks).strip()
    else:
        text = ""

    text = _strip_visible_thinking(text)
    if not text:
        raise AIProviderError(f"{provider.capitalize()} returned an empty response.")
    return text

def _parse_mentor_response(raw: str) -> dict[str, Any]:
    text = raw.strip()

    # Mistral can occasionally wrap otherwise valid JSON in a Markdown fence.
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
    if error_line in (0, "0", "", "null"):
        error_line = None
    if error_line is not None:
        try:
            error_line = int(error_line)
        except (TypeError, ValueError):
            error_line = None
        if error_line is not None and error_line < 1:
            error_line = None

    patch = parsed.get("patch")
    if patch in ({}, None):
        patch = None
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
def _normalize_provider(provider: str) -> str:
    normalized = (provider or DEFAULT_PROVIDER).strip().lower()
    if normalized in {"ollama", "local"}:
        return "ollama"
    if normalized in {"lmstudio", "lm-studio", "local_openai"}:
        return "lmstudio"
    if normalized == "mistral":
        return "mistral"
    raise AIProviderError("Invalid AI_PROVIDER value. Use 'ollama', 'lmstudio', or 'mistral'.")


def _normalize_model(model: str, provider: str) -> str:
    normalized = (model or "").strip()
    if normalized:
        return normalized
    if provider == "ollama":
        return DEFAULT_MODEL
    if provider == "lmstudio":
        return DEFAULT_LMSTUDIO_MODEL
    return "mistral-small-latest"


def _ollama_url() -> str:
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
    if base.endswith("/api"):
        return base + "/chat"
    return base + "/api/chat"


def _request_ollama(
    *,
    model: str,
    body: dict[str, Any],
    max_retries: int,
) -> dict[str, Any]:
    last_error: str | None = None
    url = _ollama_url()

    for attempt in range(max_retries + 1):
        request_body = {
            "model": model,
            "messages": body["messages"],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.2,
                "num_predict": max(
                    128,
                    int(os.getenv("OLLAMA_NUM_PREDICT", "400")),
                ),
            },
        }
        if body.get("format") is not None:
            request_body["format"] = body["format"]

        request = urllib.request.Request(
            url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            timeout_seconds = max(
                15,
                float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60")),
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1200]
            retryable = exc.code in {429, 500, 502, 503, 504}
            if exc.code == 404:
                raise AIProviderError(
                    f"Ollama model '{model}' was not found. Run: ollama pull {model}",
                    status_code=404,
                ) from exc

            last_error = f"Ollama request failed (HTTP {exc.code}): {detail}"
            if not retryable or attempt >= max_retries:
                raise AIProviderError(
                    last_error,
                    retryable=retryable,
                    status_code=exc.code,
                ) from exc

            time.sleep(min(8.0, (2 ** attempt) + random.uniform(0.0, 1.0)))
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = (
                f"Cannot reach Ollama at {url}. "
                "Make sure Ollama is installed and running."
            )
            if attempt >= max_retries:
                raise AIProviderError(last_error, retryable=True) from exc
            time.sleep(min(8.0, (2 ** attempt) + random.uniform(0.0, 1.0)))
        except json.JSONDecodeError as exc:
            raise AIProviderError("Ollama returned an unreadable HTTP response.") from exc

    raise AIProviderError(last_error or "Ollama request failed after retries.")



def _lmstudio_url() -> str:
    base = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234").strip().rstrip("/")
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _request_lmstudio(
    *,
    model: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    url = _lmstudio_url()
    request_body = {
        "model": model,
        "messages": body["messages"],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": max(
            128,
            int(os.getenv("LMSTUDIO_MAX_TOKENS", "400")),
        ),
        "response_format": {"type": "json_object"},
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        if exc.code == 404:
            raise AIProviderError(
                f"LM Studio model '{model}' was not found. "
                "Check the model identifier shown by LM Studio.",
                status_code=404,
            ) from exc
        raise AIProviderError(
            f"LM Studio request failed (HTTP {exc.code}): {detail}",
            retryable=exc.code in {429, 500, 502, 503, 504},
            status_code=exc.code,
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AIProviderError(
            f"Cannot reach LM Studio at {url}. "
            "Start the LM Studio local server and load a model.",
            retryable=True,
        ) from exc
    except json.JSONDecodeError as exc:
        raise AIProviderError("LM Studio returned an unreadable HTTP response.") from exc


def _request_mistral(
    *,
    model: str,
    api_key: str,
    body: dict[str, Any],
    max_retries: int,
) -> dict[str, Any]:
    last_error: str | None = None

    for attempt in range(max_retries + 1):
        request = urllib.request.Request(
            MISTRAL_CHAT_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1200]
            retryable = exc.code in {429, 500, 502, 503, 504}

            if exc.code in {401, 403}:
                last_error = (
                    "Mistral rejected the API key or workspace permissions "
                    f"(HTTP {exc.code}). Check MISTRAL_API_KEY and your Mistral workspace."
                )
            elif exc.code == 404:
                last_error = f"Mistral model '{model}' was not found or is unavailable (HTTP 404)."
            elif exc.code == 400:
                last_error = (
                    "Mistral rejected the mentor request (HTTP 400). "
                    f"Provider detail: {detail}"
                )
            else:
                last_error = f"Mistral API request failed ({exc.code}): {detail}"

            if not retryable or attempt >= max_retries:
                raise AIProviderError(
                    last_error,
                    retryable=retryable,
                    status_code=exc.code,
                ) from exc

            retry_after = exc.headers.get("Retry-After")
            try:
                wait_seconds = float(retry_after) if retry_after else 0.0
            except (TypeError, ValueError):
                wait_seconds = 0.0
            if wait_seconds <= 0:
                wait_seconds = min(30.0, (2 ** attempt) + random.uniform(0.0, 1.0))
            time.sleep(wait_seconds)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = "Unable to reach the Mistral API."
            if attempt >= max_retries:
                raise AIProviderError(last_error, retryable=True) from exc
            time.sleep(min(8.0, (2 ** attempt) + random.uniform(0.0, 1.0)))
        except json.JSONDecodeError as exc:
            raise AIProviderError("Mistral returned an unreadable HTTP response.") from exc

    raise AIProviderError(last_error or "Mistral API request failed after retries.")



def mentor_response(*, problem: dict[str, Any], language: str, code: str, execution: dict[str, Any] | None, action: str, question: str | None, hint_level: int, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    provider = _normalize_provider(os.getenv("AI_PROVIDER", DEFAULT_PROVIDER))
    model = _normalize_model(os.getenv("AI_MODEL", DEFAULT_MODEL), provider)

    constraints = "\n".join("- " + str(x) for x in (problem.get("constraints") or []))
    description = str(problem.get("description") or "")
    if len(description) > 7000:
        description = description[:7000] + "\n[description truncated]"

    examples = json.dumps(problem.get("examples") or [], ensure_ascii=False)
    if len(examples) > 3500:
        examples = examples[:3500] + "\n[examples truncated]"

    if len(constraints) > 2500:
        constraints = constraints[:2500] + "\n[constraints truncated]"

    code_text = str(code or "")
    if len(code_text) > 18000:
        code_text = code_text[:18000] + "\n# [code truncated for mentor context]"

    execution_text = json.dumps(
        execution or {"status": "not_run", "results": []},
        ensure_ascii=False,
    )
    if len(execution_text) > 5000:
        execution_text = execution_text[:5000] + "\n[execution output truncated]"

    compact_history = []
    for item in (history or [])[-8:]:
        compact_history.append({
            "role": item.get("role", ""),
            "content": str(item.get("content", ""))[:1200],
        })
    history_text = json.dumps(compact_history, ensure_ascii=False)

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
        description=description,
        constraints=constraints,
        examples=examples,
        language=language,
        code=code_text,
        execution_text=execution_text,
        history_text=history_text,
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

    response_schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "error_line": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "patch": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {
                            "start_line": {"type": "integer"},
                            "end_line": {"type": "integer"},
                            "replacement": {"type": "string"},
                        },
                        "required": ["start_line", "end_line", "replacement"],
                    },
                    {"type": "null"},
                ],
            },
        },
        "required": ["answer", "error_line", "patch"],
    }

    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": context.strip()},
    ]

    if provider == "ollama":
        request_body = {
            "messages": messages,
            # Use Ollama's generic JSON mode rather than a complex schema.
            # This is more compatible across local model versions.
            "format": "json",
        }
        try:
            payload = _request_ollama(
                model=model,
                body=request_body,
                max_retries=0,
            )
        except AIProviderError as primary_error:
            fallback_provider = _normalize_provider(
                os.getenv("AI_FALLBACK_PROVIDER", "none")
            ) if os.getenv("AI_FALLBACK_PROVIDER", "none").strip().lower() not in {"none", ""} else "none"
            fallback_model = os.getenv("AI_FALLBACK_MODEL", "").strip()
            fallback_key = os.getenv("MISTRAL_API_KEY", "").strip()

            if (
                fallback_provider == "mistral"
                and fallback_model
                and fallback_key
            ):
                try:
                    payload = _request_mistral(
                        model=fallback_model,
                        api_key=fallback_key,
                        body={
                            "model": fallback_model,
                            "messages": messages,
                            "max_tokens": 600,
                            "response_format": {"type": "json_object"},
                        },
                        max_retries=1,
                    )
                    provider = "mistral"
                except AIProviderError:
                    raise primary_error
            else:
                raise
    elif provider == "lmstudio":
        payload = _request_lmstudio(
            model=model,
            body={"messages": messages},
        )
    elif provider == "mistral":
        api_key = os.getenv("MISTRAL_API_KEY", "").strip()
        if not api_key:
            raise AIProviderError(
                "MISTRAL_API_KEY is not configured. Set it in backend/.env "
                "or switch AI_PROVIDER to 'ollama'."
            )
        request_body = {
            "model": model,
            "messages": messages,
            "max_tokens": 600,
            "response_format": {"type": "json_object"},
        }
        payload = _request_mistral(
            model=model,
            api_key=api_key,
            body=request_body,
            max_retries=1,
        )

    answer = _extract_message_text(payload, provider)
    result = _parse_mentor_response(answer)
    if action != "modify":
        result["patch"] = None
    return result

# CodeMentor AI Mentor API

The AI Mentor endpoints preserve the existing frontend contract and add explicit chat-session creation. Authentication is unchanged.

POST /mentor/analyze

Primary practice-page mentor endpoint.

Request fields:
- problem_slug: existing problem slug
- language: language name
- code: current user code
- action: hint | debug | complexity | edge | question | modify
- question: optional user question
- hint_level: 1-4
- execution: optional execution result object
- session_id: optional existing practice-session id

Response fields remain compatible:
- session_id
- problem_slug
- action
- hint_level
- answer
- error_line
- patch
- message_id

error_line is a 1-based source line when execution evidence identifies one. Execution evidence takes precedence over model guesses.

POST /mentor/chat

Dashboard mentoring endpoint.

Request:
{
  "question": "How should I prepare for graph interviews?",
  "session_id": 12
}

Response:
{
  "session_id": 12,
  "answer": "...",
  "error_line": null,
  "patch": null,
  "message_id": 99
}

POST /mentor/sessions

Creates a new independent mentor conversation.

Practice:
{
  "scope": "practice",
  "problem_slug": "two-sum",
  "title": "Two Sum debugging"
}

Dashboard:
{
  "scope": "dashboard",
  "title": "Interview planning"
}

Practice sessions require a problem_slug. Dashboard sessions cannot be attached to a problem.

GET /mentor/sessions

Lists the current user's sessions. Optional scope is dashboard or practice; optional problem_slug narrows practice sessions.

GET /mentor/sessions/{session_id}

Returns the session metadata and persisted messages. Sessions are owner-scoped.

DELETE /mentor/sessions/{session_id}

Deletes the session and its messages. It is also owner-scoped.

Provider configuration

The default provider is Ollama.

Supported environment variables:
- AI_PROVIDER=ollama | lmstudio | mistral
- AI_MODEL=provider-specific-model
- AI_TIMEOUT_SECONDS=25
- AI_MAX_RETRIES=0
- AI_NUM_PREDICT=450
- OLLAMA_BASE_URL=http://127.0.0.1:11434
- OLLAMA_KEEP_ALIVE=10m
- OLLAMA_NUM_CTX=8192
- AI_FALLBACK_PROVIDER=none | ollama | lmstudio | mistral
- AI_FALLBACK_MODEL=provider-specific-model
- MISTRAL_API_KEY=...

The shared backend/.env.example is intentionally unchanged to avoid a high-conflict shared-file edit.

Mentor behavior and safety

The mentor receives problem, user code, execution result, language, and recent conversation history as context. These sections are explicitly treated as untrusted data so problem text or code cannot override the mentor's system rules.

Hints are progressive and must not contain a full solution. Debugging uses execution evidence. Complexity analyzes the user's current approach. Edge-case mentoring focuses on adversarial inputs. Conceptual questions remain explanatory. Modify requests can return only a small local patch.

Ollama requests disable visible thinking, use structured JSON output, use deterministic low-temperature generation, keep the model warm when supported, and use a bounded timeout. Provider failures are classified so the optional fallback provider can take over.

Malformed model output is parsed defensively and may be repaired once with the same strict schema. Before a patch is returned, the application validates its source-line range, size, scope, and Python syntax when applicable.

The API never returns model reasoning or provider credentials.

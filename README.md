# CodeMentor AI

CodeMentor AI is an adaptive coding-practice platform that combines:

- personalized coding analytics
- an in-browser coding environment
- AI-assisted code diagnosis and mentoring
- adaptive problem recommendations
- interview and career preparation

## Current stage

The repository is being built incrementally. Each stage is manually tested before the next stage is added.

## Initial architecture

- `backend/` — FastAPI backend
- `frontend/` — web frontend, to be integrated from Stitch exports
- future services — database, code execution, AI agents, recommendations, and analytics

## Development approach

1. Build a small working capability.
2. Commit it to GitHub.
3. Run and verify it locally.
4. Only then continue to the next capability.

## Local AI Mentor setup

Create `backend/.env` and set your Mistral API key:

    MISTRAL_API_KEY=your-mistral-api-key
    AI_MODEL=mistral-small-latest
    AI_FALLBACK_MODEL=mistral-large-latest

The backend loads `backend/.env` from the repository path, so the API key is available even when Uvicorn is started from the project root. Restart the FastAPI server after changing the key.


## Problem catalogue quality

Phase 2 now has a shared catalogue normalization and audit layer:

    python -m backend.audit_catalog

Use --json for machine-readable output or --fail-on-issues to make the command return a failing exit code when quality issues or duplicate groups exist.

The catalogue layer normalizes supported difficulties to Easy, Medium, or Hard, canonicalizes common topic aliases, checks English/problem completeness, validates examples/tests/starter code, and detects duplicate records by external identity and problem content.

The canonical taxonomy is also exposed through:

    GET /problems/taxonomy


## Code execution sandbox

The execution service supports two modes during development:

    EXECUTION_SANDBOX=local

For production, set:

    EXECUTION_SANDBOX=docker
    EXECUTION_DOCKER_IMAGE=codementor-multi-runtime:latest

Build the multi-language runner image from the repository root:

    docker build -t codementor-multi-runtime:latest -f docker/multi-runtime/Dockerfile docker/multi-runtime

The runtime image includes Python, C++20, Java 17, JavaScript/Node.js, TypeScript, Go, and Rust. Standard stdin/stdout problems can use these runtimes; function-style execution remains Python-only for now.

Docker execution disables networking, drops Linux capabilities, uses a read-only workspace, applies CPU/memory/process limits, and removes the container after execution. Problem-specific limits are clamped to a global 10-second timeout and 1 GiB memory ceiling so imported problem metadata cannot request unbounded resources. The local runner remains available for development only; production configuration rejects unsandboxed execution.

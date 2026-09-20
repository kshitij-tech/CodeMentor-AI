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

Create `backend/.env` and set your Gemini API key:

    GEMINI_API_KEY=your-gemini-api-key
    AI_MODEL=gemini-2.5-flash
    AI_FALLBACK_MODEL=gemini-2.5-flash-lite

The backend loads `backend/.env` from the repository path, so the API key is available even when Uvicorn is started from the project root. Restart the FastAPI server after changing the key.


# CodeMentor AI - Testing & QA Report

## Scope

Testing, QA, reliability, and regression-prevention work for branch feature/testing-quality.

Baseline audited from commit f27f34a4082ec5a72788c385e6a1166b50e8f9a4 on main.

This branch adds QA infrastructure and tests only. Application behavior was not redesigned.

## Test matrix

| Area | Coverage |
| --- | --- |
| Authentication | Registration validation, normalized email, duplicate account, login, /auth/me, invalid token, deleted-user token |
| API integration | FastAPI routing/dependency behavior through a dependency-free ASGI client |
| Database | SQLite PRAGMAs, unique constraints, rollback, foreign-key cascades, concurrent writes, lock waiting |
| Problem catalogue | Authenticated catalogue list/topic/taxonomy/detail API contracts and filters |
| Execution | Syntax diagnostics, auth guard, rejection mapping, secret-output redaction, unsupported validator paths |
| AI Mentor | Model-unavailable 503s, user-message persistence, malformed structured responses, parser edge cases |
| Recommendations | Active-problem lock until solve and recommendation transition |
| Analytics | User scoping, streak counting, timezone fallback, runtime aggregation, hint counting |
| Workspace | Per-user and per-language isolation plus history scoping |
| Frontend | Local asset resolution, shared UI assets, Node JavaScript syntax checks |
| Docker | Dockerfile contract checks plus opt-in live multi-runtime smoke tests |
| Concurrency | Threaded SQLite writes and short writer-lock contention |
| Coverage | Coverage configuration and a 50% minimum quality-gate floor |
| Static quality | Ruff and mypy checks through the reusable quality gate |

## Existing baseline findings

The repository already contained focused unit tests for AI parsing, custom validators, execution helpers, problem catalogue behavior, problem-package normalization, stdio adaptation, and default output validation.

The existing CI workflow compiled the backend, ran unittest discovery, built the multi-runtime image, and ran Docker smoke tests.

## Known baseline CI failure

The latest baseline GitHub Actions run passed dependency installation, backend compilation, backend tests, Docker image build, and Python Docker smoke execution. The final multi-runtime smoke command failed because it attempted to create /runner/smoke.cpp.

The Dockerfile uses WORKDIR /workspace and USER 65532:65532 and does not provide /runner.

This branch does not modify that workflow or Dockerfile because they belong to other workstreams.

Required owner action:
- feature/devops-deployment should update .github/workflows/backend-check.yml to use an existing writable smoke-test path such as /tmp or a properly mounted workspace path.
- Alternatively, feature/code-execution could deliberately add a compatible /runner path to the image.

## Deliberately unchanged

No application implementation files were modified.

No existing team-owned test modules were modified. The new QA modules are isolated under backend/tests/test_qa_*.py and backend/tests/qa_support.py.

The high-conflict shared files and owned implementations remain unchanged, including:
- backend/database.py
- backend/models.py
- backend/schemas.py
- backend/main.py
- backend/routers/auth.py
- backend/routers/problems.py
- backend/routers/execution.py
- backend/routers/mentor.py
- backend/routers/recommendations.py
- backend/routers/analytics.py
- backend/routers/profile.py
- backend/routers/workspace.py
- backend/ai.py
- docker/multi-runtime/Dockerfile
- .github/workflows/backend-check.yml
- all page-specific frontend implementation files

## Commands

Primary suite:
python -m unittest discover -s backend/tests -p "test_*.py"

Quality gate:
python qa/quality_gate.py

Test dependencies:
python -m pip install -r backend/requirements-test.txt

Live Docker checks:
CODEMENTOR_DOCKER_IMAGE=codementor-multi-runtime:ci

## Quality-gate behavior

The reusable gate runs the full unittest suite, branch-aware coverage when coverage.py is installed, a 50% coverage floor, coverage.xml generation, backend/QA compilation, Ruff check and format validation for QA-owned files, and mypy against the QA suite.

Ruff and mypy remain optional when not installed locally. CI can make them required simply by installing backend/requirements-test.txt before invoking the quality gate.

## Limitations

Live external model-provider calls are not part of automated CI. Provider failure behavior is simulated at the API boundary.

Frontend tests validate syntax and static asset contracts but do not replace browser end-to-end testing with Playwright or Cypress.

The ASGI client is intentionally dependency-free and small. It verifies FastAPI routing, validation, and dependency behavior without adding an HTTP test client dependency.

The coverage floor is a regression guard, not a claim of exhaustive business-path coverage.

## Cross-team dependencies

1. feature/devops-deployment must wire the quality gate and test dependencies into .github/workflows/backend-check.yml.
2. feature/devops-deployment or feature/code-execution must resolve the existing /runner/smoke.cpp path mismatch.
3. A future browser E2E suite would benefit from an agreed browser-runner/dependency policy.

## QA conclusion

The testing-quality branch provides cross-workstream regression coverage for authentication, persistence, isolation, concurrency, AI failures, execution contracts, recommendations, analytics, frontend JavaScript, and Docker readiness without changing another team's application implementation.

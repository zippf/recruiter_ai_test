# Phase 0 Backend Baseline

Date: 2026-09-26
Branch: `feature/modularize`

## Scope

Phase 0 records current behavior before modularization. No production code has been moved or deleted.

## Current entrypoint

- Application: `backend/main.py`
- FastAPI title: `Kozker Recruiter AI Backend`
- FastAPI version: `1.0.0`
- Route inventory command: `python phase0_route_inventory.py`
- Current registered route count: 93, including documentation routes

## Baseline checks

Run from `backend/`:

```powershell
python -c "import main; print(main.app.title); print(len(main.app.routes))"
python -m unittest test_phase0_baseline.py
python -m unittest discover -s . -p "test*.py"
python phase0_route_inventory.py
```

The focused Phase 0 checks cover:

- Application import and metadata.
- Root response and correlation ID response header.
- Compatibility routes for scan/publish and application acceptance.
- Callback rejection when the callback authorization header is missing.

## Existing baseline finding

The existing test suite currently has one failure in `test_candidate_scoping_audit.py::test_get_user_org_id_resolution`. The test calls `get_user_org_id` directly without providing `x_user_email`, so the FastAPI `Header` default object reaches `get_current_user_id`, which calls `.strip()` on it.

This is recorded as a pre-existing baseline issue. It is outside the structural scope of Phase 0 and should be handled separately unless the migration owner approves including it.

## Configuration names observed in `main.py`

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_SERVICE_KEY`
- `USE_N8N`
- `N8N_GENERATE_JOBS_URL`
- `N8N_EXTRACT_SKILLS_URL`
- `N8N_MATCH_CANDIDATES_URL`
- `N8N_GENERATE_QUESTIONS_URL`
- `N8N_REGENERATE_JOBS_URL`
- `N8N_REFINE_QUESTION_URL`
- `CALLBACK_SECRET`
- `BACKEND_BASE_URL`
- `SERVICE_URL_BACKEND`
- `PUBLIC_BACKEND_URL`
- `FRONTEND_BASE_URL`
- `MATCH_THRESHOLD`
- `N8N_MATCH_TIMEOUT_SECONDS`
- `LINKEDIN_CLIENT_ID`
- `LINKEDIN_CLIENT_SECRET`
- `LINKEDIN_REDIRECT_URI`
- `N8N_WHATSAPP_WEBHOOK_URL`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`

Do not commit local `.env` files or secret values.

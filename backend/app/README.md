# Application Package

This package is the Phase 1 scaffold for the backend modularization.

`app.main.app` temporarily re-exports the FastAPI application from the legacy `main.py` entrypoint. The legacy entrypoint remains authoritative until behavior-preserving extraction phases move responsibilities into these packages.

Do not add new product behavior here during the migration. Each later phase should move one responsibility, run its validation gate, and preserve the existing API contract.

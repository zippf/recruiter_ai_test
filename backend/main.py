# =============================================================================
# KOZKER RECRUITER AI — BACKEND SERVER (main.py)
# =============================================================================
#
# WHAT IS THIS FILE, IN PLAIN ENGLISH?
# -------------------------------------
# This is the "brain" of the Recruiter AI web application. The website /
# mobile app that recruiters and hiring managers use (the "frontend") does
# NOT talk to the database directly. Instead, every button click, page
# load, and form submission sends a request over the internet to THIS
# program, which is written using a Python web framework called "FastAPI".
#
# This program then:
#   1. Checks who is asking (is this a logged-in recruiter? which company
#      do they belong to? are they allowed to see this data?).
#   2. Talks to the actual database (a hosted Postgres database service
#      called "Supabase") to read or write records — clients, job
#      requirements, job postings, candidates, applications, interview
#      questions, approvals, notifications, etc.
#   3. Sometimes calls out to AI automation tools (via a workflow-automation
#      service called "n8n") to do things like: write a job description,
#      pick out required skills, match candidates to a job, or generate
#      interview questions. If that AI service isn't configured, this file
#      has built-in "fallback" logic that fakes similar (simpler) results
#      itself so the product still works.
#   4. Sends emails and WhatsApp messages to candidates (e.g. "your
#      application was received", "you got the job", etc.).
#   5. Sends the final answer back to the frontend as JSON data.
#
# WHO IS THE AUDIENCE OF THIS FILE?
# -------------------------------------
# Recruiters, hiring managers, and candidates use the *product* — they never
# see this code. This file is read by software developers who maintain the
# platform. The comments added throughout this file are written so that a
# brand-new/junior ("fresher") developer — or even a non-technical person
# curious about how things work — can follow along.
#
# KEY BUILDING BLOCKS YOU WILL SEE REPEATED THROUGHOUT THIS FILE:
# -------------------------------------
#   - "@app.get(...)", "@app.post(...)", "@app.put(...)", "@app.patch(...)",
#     "@app.delete(...)"  → these mark the start of an "API endpoint": a
#     specific URL + HTTP verb combination that the frontend can call.
#     e.g. @app.get("/api/v1/candidates") means: "when the frontend asks
#     for a LIST of candidates using an HTTP GET request to this URL, run
#     the Python function written directly underneath this line."
#   - "async def function_name(...)"  → the actual code that runs for that
#     endpoint. "async" just means this function is allowed to pause and
#     wait (e.g. while talking to the database) without freezing the whole
#     server for other users.
#   - "class SomethingModel(BaseModel):"  → these are NOT endpoints. They
#     describe the *shape* of data going in or out (this is called a
#     "Pydantic model" / "schema"). FastAPI automatically checks that
#     incoming JSON data matches this shape, and rejects it with a clear
#     error if it doesn't. Think of it as a form with labeled fields.
#   - "db.table("some_table").select(...)/.insert(...)/.update(...)/
#     .delete(...)"  → these lines are talking to the Supabase (Postgres)
#     database. ".select" = read rows, ".insert" = create a new row,
#     ".update" = change existing row(s), ".delete" = remove row(s).
#   - "background_tasks.add_task(...)"  → schedules a function to run
#     AFTER the current request has already answered the user, so the user
#     doesn't have to sit and wait for slow work (like AI generation or
#     sending emails) to finish.
#   - "Depends(get_supabase)" / "Depends(get_current_user_id)" → FastAPI's
#     "Dependency Injection": before your endpoint function even runs,
#     FastAPI automatically runs these small helper functions first and
#     hands you their result as a ready-to-use argument (e.g. a database
#     connection, or the ID of whoever is logged in).
#   - try / except blocks  → "try to do this risky thing (e.g. call the
#     database or an external website); if anything goes wrong, don't crash
#     the whole server — log the error and handle it gracefully instead."
#
# MAJOR FEATURE AREAS COVERED IN THIS FILE (in roughly the order they
# appear):
#   1. Server setup: logging, error handling, CORS (cross-origin) rules.
#   2. Authentication & permission helpers (who is logged in, what
#      organization/company do they belong to, what are they allowed to
#      see or do).
#   3. Utility helpers: resume text extraction (PDF/DOCX), Google Drive
#      file downloads, ID "obfuscation" (hiding real database IDs in
#      public URLs), sending emails, sending WhatsApp messages.
#   4. Pydantic data models ("Models" section) — the shape of every piece
#      of data the API accepts or returns.
#   5. Core recruiting CRUD endpoints: Clients → Requirements ("mandates")
#      → Job Openings → Candidates → Applications → Screening Questions.
#   6. AI-generation workflows (job description writing, skill extraction,
#      candidate-to-job matching, screening question generation) — each
#      with a "dispatch to n8n" path and a "local fallback" path.
#   7. Inbound "callback" endpoints — this is where the n8n AI automation
#      calls BACK into this server once it has finished generating
#      content, so the server can save the AI's output to the database.
#   8. LinkedIn integration (OAuth login + posting jobs to LinkedIn).
#   9. Password reset via one-time-passcode (OTP).
#  10. Multi-stage "Approval Workflows" system (a chain of people who must
#      sign off on something, one stage at a time, with notifications).
#
# A NOTE ON THESE COMMENTS:
# -------------------------------------
# Every comment in this file was added purely as documentation. Not a
# single line of the original executable code was changed, reordered, or
# removed — only explanatory comment lines were inserted above existing
# code so the program behaves 100% identically to before.
# =============================================================================

import os
from datetime import datetime, timezone, timedelta
import asyncio
import io
import json
import logging
import re
import uuid
import base64
from typing import List, Dict, Any, Optional, Set, Tuple, Iterable
from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, BackgroundTasks, Header, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client, Client, ClientOptions
from postgrest.exceptions import APIError
import httpx
import jwt
import time

# -----------------------------------------------------------------------
# ENVIRONMENT VARIABLES
# -----------------------------------------------------------------------
# "Environment variables" are settings (like passwords, URLs, and secret
# keys) that live OUTSIDE the code, usually in a hidden ".env" file or in
# the hosting platform's settings screen. We never want to hard-code
# secrets (like database passwords) directly into the code, because this
# code file might be shared, viewed, or stored in version control (Git).
# The block below looks in a couple of likely folders for a ".env" file
# and loads whatever settings it finds into memory so the rest of this
# file can read them with os.getenv("SOME_NAME").
# Load environment variables from multiple possible locations
base_dir = os.path.dirname(os.path.abspath(__file__))
env_file_backend = os.path.join(base_dir, ".env")
if os.path.exists(env_file_backend):
    load_dotenv(dotenv_path=env_file_backend, override=True)
env_file_root = os.path.join(os.path.dirname(base_dir), ".env")
if os.path.exists(env_file_root):
    load_dotenv(dotenv_path=env_file_root, override=True)
load_dotenv(override=True)

# -----------------------------------------------------------------------
# REQUEST TRACKING (CONTEXT VARIABLES)
# -----------------------------------------------------------------------
# A "ContextVar" is a way to store a small piece of information (like
# "which request is currently being handled" or "which user is making
# this request") that is automatically kept separate for every
# simultaneous request the server is handling. This lets our logging code
# below tag every log line with the correct request ID and user, even
# though many users can be using the app at the exact same time.
from contextvars import ContextVar

# Context variables for tracking requests & users across execution context
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")
user_email_ctx: ContextVar[str] = ContextVar("user_email", default="anonymous")

# -----------------------------------------------------------------------
# STRUCTURED (JSON) LOGGING
# -----------------------------------------------------------------------
# Instead of printing plain text messages, this custom "formatter" makes
# every log line come out as a single line of JSON (e.g.
# {"timestamp": "...", "level": "INFO", "message": "..."}). This is much
# easier for automated log-monitoring tools to search and filter later.
# Structured JSON Log Formatter
# Defines HOW each log message should be formatted before being printed.
class JSONLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_object = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": correlation_id_ctx.get(),
            "user_email": user_email_ctx.get(),
            "message": record.getMessage()
        }
        if record.exc_info:
            log_object["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_object)

# Create (or reuse) a logger named "backend", set it to record INFO-level
# messages and above, remove any old/duplicate output handlers, and attach
# our custom JSON formatter (defined just above) as the one and only
# output handler. From this point on, calling logger.info(...) /
# logger.error(...) anywhere in this file will produce a JSON log line.
logger = logging.getLogger("backend")
logger.setLevel(logging.INFO)
for h in logger.handlers[:]:
    logger.removeHandler(h)
handler = logging.StreamHandler()
handler.setFormatter(JSONLogFormatter())
logger.addHandler(handler)

# -----------------------------------------------------------------------
# APPLICATION CONFIGURATION (read once at startup from environment vars)
# -----------------------------------------------------------------------
# SUPABASE_URL / SUPABASE_KEY / SUPABASE_SERVICE_ROLE_KEY:
#   Connection details for the Supabase (hosted Postgres) database.
#   The "service role key" is a powerful, admin-level key that bypasses
#   Supabase's row-level security rules — it should only be used for
#   trusted, server-side operations (never sent to a browser).
# USE_N8N + the N8N_*_URL variables:
#   n8n is a workflow-automation tool used to run AI tasks (like writing
#   job descriptions). USE_N8N switches whether this backend tries to
#   call out to n8n for AI work, or instead uses its own simplified
#   built-in ("local fallback") logic to produce similar results.
# CALLBACK_SECRET:
#   A shared secret password. When n8n finishes an AI task and calls back
#   into this server to deliver the results, it must present this secret
#   so we know the request is genuinely from our own trusted automation
#   and not from a random stranger on the internet.
# BACKEND_BASE_URL / PUBLIC_BACKEND_URL / FRONTEND_BASE_URL:
#   The web addresses of this backend server and of the frontend website,
#   used for building links (e.g. in emails) and for telling n8n where to
#   send its callback results.
# MATCH_THRESHOLD:
#   The minimum "match score" (out of 100) a candidate needs to be
#   considered a real match for a job opening.
# LINKEDIN_*:
#   Credentials used for the "Sign in / connect with LinkedIn" feature and
#   for posting job openings to a company's LinkedIn page.
# Read config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")

USE_N8N = os.getenv("USE_N8N", "False").lower() in ("true", "1", "yes")
N8N_GENERATE_JOBS_URL = os.getenv("N8N_GENERATE_JOBS_URL")
N8N_EXTRACT_SKILLS_URL = os.getenv("N8N_EXTRACT_SKILLS_URL")
N8N_MATCH_CANDIDATES_URL = os.getenv("N8N_MATCH_CANDIDATES_URL")
N8N_GENERATE_QUESTIONS_URL = os.getenv("N8N_GENERATE_QUESTIONS_URL")
N8N_REGENERATE_JOBS_URL = os.getenv("N8N_REGENERATE_JOBS_URL")
N8N_REFINE_QUESTION_URL = os.getenv("N8N_REFINE_QUESTION_URL")
CALLBACK_SECRET = os.getenv("CALLBACK_SECRET")

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")
PUBLIC_BACKEND_URL = (os.getenv("SERVICE_URL_BACKEND") or os.getenv("PUBLIC_BACKEND_URL") or BACKEND_BASE_URL).rstrip("/")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "30.0"))

LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", f"{BACKEND_BASE_URL}/api/v1/auth/linkedin/callback")

# -----------------------------------------------------------------------
# SIMPLE IN-MEMORY (RAM-ONLY) FALLBACK STORAGE
# -----------------------------------------------------------------------
# These two dictionaries live only in this running program's memory (RAM).
# They are used as a temporary safety net in case a write to the real
# database fails for some reason (see e.g. candidate query handling
# further down) or for tracking short-lived password-reset codes.
# IMPORTANT: anything stored here is LOST if the server restarts, and is
# NOT shared between multiple copies of this server if more than one is
# running (as would happen with multiple deployment instances).
# Global backup in-memory storage for candidate queries fallback
in_memory_queries: Dict[str, List[Dict[str, Any]]] = {}

# Global memory cache for pending password updates & verification OTPs
password_otps: Dict[str, Dict[str, Any]] = {}

# -----------------------------------------------------------------------
# CREATE THE FASTAPI APPLICATION
# -----------------------------------------------------------------------
# This single "app" object is the heart of the whole web server. Every
# "@app.get/post/put/patch/delete(...)" decorator you'll see below is
# registering one more URL route on this same app.
# Initialize FastAPI
app = FastAPI(title="Kozker Recruiter AI Backend", version="1.0.0")

# Noise filter for non-essential HTTP paths
# A list of noisy, low-value URL paths we don't want cluttering the logs
# (health checks, browser favicon requests, API documentation pages, etc.)
NOISY_PATHS = {"/docs", "/redoc", "/openapi.json", "/favicon.ico", "/health", "/metrics"}

# -----------------------------------------------------------------------
# MIDDLEWARE #1: Correlation ID + basic performance logging
# -----------------------------------------------------------------------
# "Middleware" is code that runs on EVERY single request, both before and
# after the actual endpoint function handles it — like a security guard
# and a stopwatch standing at the front door of the server.
# This particular middleware:
#   1. Generates (or reuses) a unique "correlation ID" for the request, so
#      that all log lines related to one single request can be grouped
#      together later, even in a busy server handling many requests at
#      once.
#   2. Times how long the request took to process.
#   3. Logs a summary line once the request is done (unless it's one of
#      the "noisy" paths defined above, like /health).
#   4. Puts the correlation ID into the response headers so the frontend
#      (or a support engineer) can quote it back if something goes wrong.
# Correlation ID & Observability Middleware
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    corr_id = request.headers.get("x-correlation-id") or request.headers.get("x-request-id") or f"corr_{uuid.uuid4().hex[:12]}"
    user_email = request.headers.get("x-user-email") or "anonymous"

    token_corr = correlation_id_ctx.set(corr_id)
    token_user = user_email_ctx.set(user_email)

    start_time = time.time()
    try:
        response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)
        
        # Suppress log noise for OPTIONS preflight, docs, and health checks
        is_noisy = request.method == "OPTIONS" or request.url.path in NOISY_PATHS
        if not is_noisy:
            logger.info(json.dumps({
                "event": "http_request_complete",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms
            }))
        
        response.headers["X-Correlation-ID"] = corr_id
        return response
    except Exception as exc:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        logger.error(json.dumps({
            "event": "http_request_error",
            "method": request.method,
            "path": request.url.path,
            "duration_ms": duration_ms,
            "error_detail": str(exc)
        }), exc_info=True)
        raise exc
    finally:
        correlation_id_ctx.reset(token_corr)
        user_email_ctx.reset(token_user)

# -----------------------------------------------------------------------
# CORS (Cross-Origin Resource Sharing) CONFIGURATION
# -----------------------------------------------------------------------
# Web browsers block a website running on one address (e.g.
# https://app.kozker.com) from calling an API running on a different
# address (e.g. this backend) UNLESS that API explicitly says "it's okay,
# I trust requests from you." This CORS middleware is exactly that
# permission list. Because "allow_origin_regex" here matches basically any
# http/https address, this backend is configured to accept requests from
# any frontend origin (a very permissive setup, common in early-stage
# products but worth tightening later for production security).
# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost",
        "http://127.0.0.1",
        "http://kozker.localhost",
        "http://api.localhost",
        "https://localhost",
        "https://kozker.localhost",
        "https://api.localhost"
    ],
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------
# CUSTOM ERROR HANDLER: Supabase/Postgres errors ("APIError")
# -----------------------------------------------------------------------
# Whenever any endpoint below causes the Supabase database library to
# raise an "APIError" (e.g. a bad query, missing column, etc.), FastAPI
# will route that error to this function instead of crashing. It logs the
# real error, but returns a friendly, generic response to the frontend so
# users don't see a scary raw database error message.
# Special case: if the error looks like it's just about a database column
# that doesn't exist yet (a common issue when the database schema hasn't
# caught up with new code), this pretends things worked so the user isn't
# blocked (this is a defensive/pragmatic workaround, not a "correct" fix).
@app.exception_handler(APIError)
async def postgrest_api_error_handler(request: Request, exc: APIError):
    err_str = f"{getattr(exc, 'message', '')} {str(exc)} {repr(exc)}"
    logger.error(f"Postgrest APIError on {request.method} {request.url.path}: {err_str}")
    if "Could not find the" in err_str or "PGRST204" in err_str or "schema cache" in err_str:
        logger.warning(f"Gracefully handling missing schema column error on {request.url.path}: {err_str}")
        return JSONResponse(
            status_code=200,
            content={"status": "published", "message": "Form configuration saved successfully"}
        )
    return JSONResponse(
        status_code=400,
        content={"detail": str(getattr(exc, 'message', exc))}
    )

# -----------------------------------------------------------------------
# CUSTOM ERROR HANDLER: catch-all for any other unexpected error
# -----------------------------------------------------------------------
# This is the final safety net. If ANY endpoint anywhere in this file
# throws an error that nothing else has handled, this function catches it,
# writes the full error + stack trace to the logs (exc_info=True), and
# returns a generic HTTP 500 "Internal Server Error" response instead of
# letting the whole server crash.
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, (StarletteHTTPException, RequestValidationError)):
        raise exc
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"}
    )

# -----------------------------------------------------------------------
# MIDDLEWARE #2: plain-text request logging to a local file
# -----------------------------------------------------------------------
# In addition to the JSON logs above, this middleware also appends a
# simple one-line summary of every request (method, path, whether an
# Authorization header was present, response status, and how long it
# took) to a local file called "requests.log". This is a very basic,
# old-school style of debugging/audit log kept alongside the newer JSON
# logging system.
@app.middleware("http")
async def log_requests(request: Request, call_next):
    import time
    start_time = time.time()
    path = request.url.path
    method = request.method
    headers = dict(request.headers)
    auth_header = headers.get("authorization", "")
    has_auth = f"Yes ({auth_header[:25]}...)" if auth_header else "No"
    
    response = await call_next(request)
    process_time = time.time() - start_time
    
    with open("requests.log", "a") as f:
        f.write(f"[{method}] {path} | Auth: {has_auth} | Status: {response.status_code} | Time: {process_time:.4f}s\n")
        
    return response



# --- MOUNT ROUTERS ---
from app.api.v1.auth import router as auth_router
from app.api.v1.clients import router as clients_router
from app.api.v1.requirements import router as requirements_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.candidates import router as candidates_router
from app.api.v1.applications import router as applications_router
from app.api.v1.approvals import router as approvals_router
from app.api.v1.linkedin import router as linkedin_router
from app.api.v1.chat import router as chat_router
from app.api.v1.telemetry import router as telemetry_router
from app.api.v1.callbacks import router as callbacks_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.activity import router as activity_router
from app.api.v1.activity_log import router as activity_log_router
from app.api.v1.chatbot import router as chatbot_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.members import router as members_router
from app.api.v1.org import router as org_router
from app.api.v1.profile import router as profile_router
from app.api.v1.queries import router as queries_router
from app.api.v1.questions import router as questions_router
from app.api.v1.roles import router as roles_router

app.include_router(auth_router)
app.include_router(clients_router)
app.include_router(requirements_router)
app.include_router(jobs_router)
app.include_router(candidates_router)
app.include_router(applications_router)
app.include_router(approvals_router)
app.include_router(linkedin_router)
app.include_router(chat_router)
app.include_router(telemetry_router)
app.include_router(callbacks_router)
app.include_router(notifications_router)
app.include_router(activity_router)
app.include_router(activity_log_router)
app.include_router(chatbot_router)
app.include_router(conversations_router)
app.include_router(integrations_router)
app.include_router(members_router)
app.include_router(org_router)
app.include_router(profile_router)
app.include_router(queries_router)
app.include_router(questions_router)
app.include_router(roles_router)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Kozker Recruiter AI FastAPI middleware is running."}

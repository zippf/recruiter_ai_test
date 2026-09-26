# Kozker Recruiter AI — Developer Onboarding & Execution Guide

Welcome to the **Kozker Recruiter AI** engineering team! This document serves as the complete step-by-step onboarding guide to set up your local development environment, configure all required environment variables, and run the application services.

---

## 1. System Architecture Overview

Kozker Recruiter AI consists of three core applications running alongside Supabase (Database, Auth, Storage) and n8n / Claude AI services:

```
+-----------------------------------------------------------------------+
|                              SYSTEM PORT MAP                           |
+---------------------+-------------------+-----------------------------+
| Application         | Port / URL        | Tech Stack                  |
+---------------------+-------------------+-----------------------------+
| Recruiter Frontend  | http://localhost:3000 | Next.js 16 (React 19)       |
| Admin Console       | http://localhost:3001 | Next.js 16 (React 19)       |
| FastAPI Backend     | http://localhost:8000 | Python 3.11+ / FastAPI      |
| Backend API Docs    | http://localhost:8000/docs | Swagger UI               |
+---------------------+-------------------+-----------------------------+
```

---

## 2. Prerequisites & Tools

Ensure the following tools are installed on your machine before proceeding:

- **Git**: [git-scm.com](https://git-scm.com/)
- **Node.js**: `v18.x` or `v20.x` (with `npm` v9+)
- **Python**: `v3.11` or higher
- **Docker Desktop**: Required if running services via Docker Compose ([docker.com](https://www.docker.com/))

---

## 3. Environment Variables & Placement Guide

The application uses environment variable files located at specific paths in the repository.

### File Placement Summary

1. **Root `.env`** -> `/.env` *(Primary environment file shared by backend, frontend, and Docker)*
2. **Admin Console `.env`** -> `/admin-console/.env` *(Environment file specific to the Admin Console application)*
3. **Backend `.env`** *(Optional)* -> `/backend/.env` *(Copy of root `.env` for native Python execution)*
4. **Frontend `.env`** *(Optional)* -> `/frontend/.env` *(Copy of root `.env` for native Next.js execution)*

---

### A. Root Environment File (`/.env`)

Create or update the `.env` file in the project **root directory** (`e:\Kozker_Recruiter_AI_New\.env`):

```ini
# =====================================================================
# SUPABASE DATABASE & AUTHENTICATION
# =====================================================================
NEXT_PUBLIC_SUPABASE_URL=https://covhcpsyliesrgkjxhai.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=sb_publishable_V69YOpwZKjrT1BT8k609nQ_MBzXV80b
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_V69YOpwZKjrT1BT8k609nQ_MBzXV80b
SUPABASE_URL=https://covhcpsyliesrgkjxhai.supabase.co
SUPABASE_KEY=sb_publishable_V69YOpwZKjrT1BT8k609nQ_MBzXV80b
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key_here

# Supabase OAuth 2.1 & OIDC Discovery Endpoints
NEXT_PUBLIC_SUPABASE_OAUTH_AUTHORIZE_URL=https://covhcpsyliesrgkjxhai.supabase.co/auth/v1/oauth/authorize
NEXT_PUBLIC_SUPABASE_OAUTH_TOKEN_URL=https://covhcpsyliesrgkjxhai.supabase.co/auth/v1/oauth/token
NEXT_PUBLIC_SUPABASE_JWKS_URL=https://covhcpsyliesrgkjxhai.supabase.co/auth/v1/.well-known/jwks.json
NEXT_PUBLIC_SUPABASE_OIDC_DISCOVERY_URL=https://covhcpsyliesrgkjxhai.supabase.co/auth/v1/.well-known/openid-configuration

# =====================================================================
# SERVICE URLS & BASE DOMAINS
# =====================================================================
SERVICE_URL_BACKEND=https://api.recruiter.kozker.com
SERVICE_FQDN_BACKEND=api.recruiter.kozker.com
NEXT_PUBLIC_API_URL=/api/v1
SERVICE_URL_FRONTEND=http://localhost:3000
BACKEND_BASE_URL=http://localhost:8000
FRONTEND_BASE_URL=http://localhost:3000
SERVICE_FQDN_FRONTEND=localhost

# =====================================================================
# LLM & AI INTEGRATIONS
# =====================================================================
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# =====================================================================
# N8N WORKFLOW AUTOMATION WEBHOOKS
# =====================================================================
USE_N8N=true
N8N_API_KEY=your_n8n_api_key_here
N8N_GENERATE_JOBS_URL=https://n8n.srv832341.hstgr.cloud/webhook/ats-generate-job-openings
N8N_EXTRACT_SKILLS_URL=https://n8n.srv832341.hstgr.cloud/webhook/ats-extract-weighted-skills
N8N_MATCH_CANDIDATES_URL=https://n8n.srv832341.hstgr.cloud/webhook/ats-score-candidates
N8N_GENERATE_QUESTIONS_URL=https://n8n.srv832341.hstgr.cloud/webhook/ats-screening-questions
N8N_REGENERATE_JOBS_URL=https://n8n.srv832341.hstgr.cloud/webhook/ats-regenerate-job-opening
N8N_REFINE_QUESTION_URL=https://n8n.srv832341.hstgr.cloud/webhook/ats-refine-question
CALLBACK_SECRET=kozker_callback_secret_token
MATCH_THRESHOLD=30

# =====================================================================
# LINKEDIN OAUTH INTEGRATION
# =====================================================================
LINKEDIN_CLIENT_ID=86d8qlz6udaqnd
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret_here
LINKEDIN_REDIRECT_URI=https://api.recruiter.kozker.com/api/v1/auth/linkedin/callback

# =====================================================================
# SMTP EMAIL NOTIFICATION SERVER
# =====================================================================
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=kozklawtailscale@gmail.com
SMTP_PASSWORD=your_smtp_app_password_here
SMTP_FROM=kozklawtailscale@gmail.com
```

---

### B. Admin Console Environment File (`/admin-console/.env`)

Create or update the `.env` file in the `/admin-console` directory (`e:\Kozker_Recruiter_AI_New\admin-console\.env`):

```ini
# Supabase Configuration
NEXT_PUBLIC_SUPABASE_URL=https://covhcpsyliesrgkjxhai.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=sb_publishable_V69YOpwZKjrT1BT8k609nQ_MBzXV80b
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_V69YOpwZKjrT1BT8k609nQ_MBzXV80b
SUPABASE_URL=https://covhcpsyliesrgkjxhai.supabase.co
SUPABASE_KEY=sb_publishable_V69YOpwZKjrT1BT8k609nQ_MBzXV80b
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key_here

# Supabase OAuth 2.1 & OIDC Discovery Endpoints
NEXT_PUBLIC_SUPABASE_OAUTH_AUTHORIZE_URL=https://covhcpsyliesrgkjxhai.supabase.co/auth/v1/oauth/authorize
NEXT_PUBLIC_SUPABASE_OAUTH_TOKEN_URL=https://covhcpsyliesrgkjxhai.supabase.co/auth/v1/oauth/token
NEXT_PUBLIC_SUPABASE_JWKS_URL=https://covhcpsyliesrgkjxhai.supabase.co/auth/v1/.well-known/jwks.json
NEXT_PUBLIC_SUPABASE_OIDC_DISCOVERY_URL=https://covhcpsyliesrgkjxhai.supabase.co/auth/v1/.well-known/openid-configuration

# Developer Access Secret Key
DEV_ADMIN_KEY=a7f9b8c2d1e0456789abcde0123456789abcdef0123456789abcdef0123456789

# Navigation & Security URLs
ADMIN_CONSOLE_URL=http://localhost:3001
RECRUITER_APP_URL=http://localhost:3000
CLIENT_PORTAL_URL=https://client.kozker.ai
JWT_SECRET=super-secret-shared-key-change-in-production
COOKIE_DOMAIN=localhost
```

---

## 4. Execution Step-by-Step Instructions

You can run the application using either **Option A (Docker Compose - Recommended)** or **Option B (Native Local Execution)**.

---

### OPTION A: Docker Execution (Recommended for Full Stack)

Docker Compose builds and starts all three containers (`backend`, `frontend`, `admin-console`) with configured environment files.

1. **Open terminal** in the repository root directory.
2. **Build and start the containers**:
   ```bash
   docker-compose up --build
   ```
   *(Or using modern docker syntax: `docker compose up --build`)*

3. **Verify running services**:
   - Recruiter Panel: `http://localhost:3000`
   - Admin Console: `http://localhost:3001`
   - FastAPI Backend API: `http://localhost:8000`
   - FastAPI Interactive API Docs: `http://localhost:8000/docs`

---

### OPTION B: Native Local Execution (Recommended for Active Development)

Running services natively allows for quick hot-reloading during feature development.

#### Step 1: Start Backend (FastAPI - Python)

1. Open a terminal and navigate to `backend`:
   ```bash
   cd backend
   ```
2. Create and activate Python Virtual Environment:
   - **Windows (PowerShell)**:
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```
   - **Linux / macOS**:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```
3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy root `.env` to backend folder (if not using environment inheritance):
   ```bash
   cp ../.env .env
   ```
5. Start the FastAPI server:
   ```bash
   python main.py
   ```
   *The backend server will start at `http://localhost:8000`.*

---

#### Step 2: Start Recruiter Frontend (Next.js - Port 3000)

1. Open a second terminal window and navigate to `frontend`:
   ```bash
   cd frontend
   ```
2. Install npm packages:
   ```bash
   npm install
   ```
3. Copy root `.env` to frontend folder:
   ```bash
   cp ../.env .env
   ```
4. Run the Next.js development server:
   ```bash
   npm run dev
   ```
   *Access the Recruiter Panel at `http://localhost:3000`.*

---

#### Step 3: Start Admin Console (Next.js - Port 3001)

1. Open a third terminal window and navigate to `admin-console`:
   ```bash
   cd admin-console
   ```
2. Install npm packages:
   ```bash
   npm install
   ```
3. Verify `admin-console/.env` is in place.
4. Run the development server:
   ```bash
   npm run dev
   ```
   *Access the Admin Console at `http://localhost:3001`.*

---

## 5. Team Protocols & Conventions

### Database Schema Updates & Supabase Migrations
Whenever your feature or bugfix involves a database schema change, table creation, column modification, or new migration script (`supabase/migrations/`):

- Follow the **End-to-End Schema Validation & Relational Join Protocol**.
- Always explicitly output a highlighted **🚨 SUPABASE MIGRATION REQUIRED** section when proposing PRs or updates.
- Apply SQL schema modifications via the Supabase SQL Editor using standard SQL files (`schema.sql` or targeted migration files).

---

## 6. Verification Checklist

To confirm your installation was successful:

- [ ] Open `http://localhost:8000/` -> Should return JSON status `{ "status": "online", ... }`
- [ ] Open `http://localhost:8000/docs` -> FastAPI Swagger UI should load interactive endpoint documentation.
- [ ] Open `http://localhost:3000` -> Login / Dashboard page should display the Kozker Recruiter UI.
- [ ] Open `http://localhost:3001` -> Admin Console login page should load.

---

## 7. Troubleshooting Common Issues

| Issue | Cause | Solution |
|---|---|---|
| **Port 8000/3000/3001 in use** | Another process is holding the port | Run `netstat -ano \| findstr :8000` (Windows) or `lsof -i :8000` (Mac/Linux) and terminate the process. |
| **`python main.py` ModuleNotFound** | Dependencies not installed in active venv | Ensure virtual environment is activated (`venv\Scripts\activate`) before running `pip install -r requirements.txt`. |
| **Supabase Auth Error** | Invalid or expired keys in `.env` | Double check `NEXT_PUBLIC_SUPABASE_URL` and keys in root `.env` and `admin-console/.env`. |

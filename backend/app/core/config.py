import os

from dotenv import load_dotenv


base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_file_backend = os.path.join(base_dir, ".env")
env_file_root = os.path.join(os.path.dirname(base_dir), ".env")

if os.path.exists(env_file_backend):
    load_dotenv(dotenv_path=env_file_backend, override=True)
if os.path.exists(env_file_root):
    load_dotenv(dotenv_path=env_file_root, override=True)
load_dotenv(override=True)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv(
    "SUPABASE_SERVICE_KEY"
)

USE_N8N = os.getenv("USE_N8N", "False").lower() in ("true", "1", "yes")
N8N_GENERATE_JOBS_URL = os.getenv("N8N_GENERATE_JOBS_URL")
N8N_EXTRACT_SKILLS_URL = os.getenv("N8N_EXTRACT_SKILLS_URL")
N8N_MATCH_CANDIDATES_URL = os.getenv("N8N_MATCH_CANDIDATES_URL")
N8N_GENERATE_QUESTIONS_URL = os.getenv("N8N_GENERATE_QUESTIONS_URL")
N8N_REGENERATE_JOBS_URL = os.getenv("N8N_REGENERATE_JOBS_URL")
N8N_REFINE_QUESTION_URL = os.getenv("N8N_REFINE_QUESTION_URL")
N8N_MATCH_TIMEOUT_SECONDS = int(os.getenv("N8N_MATCH_TIMEOUT_SECONDS", "300"))
CALLBACK_SECRET = os.getenv("CALLBACK_SECRET")

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")
PUBLIC_BACKEND_URL = (
    os.getenv("SERVICE_URL_BACKEND")
    or os.getenv("PUBLIC_BACKEND_URL")
    or BACKEND_BASE_URL
).rstrip("/")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "30.0"))

LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
LINKEDIN_REDIRECT_URI = os.getenv(
    "LINKEDIN_REDIRECT_URI", f"{BACKEND_BASE_URL}/api/v1/auth/linkedin/callback"
)

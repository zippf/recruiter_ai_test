from fastapi import APIRouter

from . import (
    activity,
    applications,
    approvals,
    auth,
    callbacks,
    candidates,
    clients,
    jobs,
    linkedin,
    notifications,
    requirements,
    telemetry,
    queries,
    chat,
    org,
    profile,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(clients.router, prefix="/clients", tags=["clients"])
api_router.include_router(requirements.router, prefix="/requirements", tags=["requirements"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(candidates.router, prefix="/candidates", tags=["candidates"])
api_router.include_router(applications.router, prefix="/applications", tags=["applications"])
api_router.include_router(callbacks.router, prefix="/callbacks", tags=["callbacks"])
api_router.include_router(linkedin.router, prefix="/linkedin", tags=["linkedin"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["approvals"])

api_router.include_router(activity.router, prefix="/activity_log", tags=["activity"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
api_router.include_router(queries.router, prefix="/queries", tags=["queries"])
api_router.include_router(chat.router, prefix="/chatbot", tags=["chatbot"])
api_router.include_router(org.router, prefix="/org", tags=["org"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])

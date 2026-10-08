from fastapi import APIRouter, Depends, HTTPException, Header, Request, Body, BackgroundTasks, Query, UploadFile, File
from typing import *
from supabase import Client
import json
import time
from datetime import datetime, timezone, timedelta

from app.api.dependencies import get_supabase, get_current_user_id, get_admin_supabase_client, get_user_org_id, get_safe_supabase_client
from app.core.logging import logger
from app.schemas.common import *
from app.security.tenant_access import get_recruiter_owner_ids
from app.security.authorization import deobfuscate_id
from app.services.notification_service import create_system_notification, log_activity_event
from app.services.query_service import in_memory_queries

router = APIRouter()



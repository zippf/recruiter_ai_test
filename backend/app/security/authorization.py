"""
Authorization helpers.

Contains shared ID-obfuscation utilities (obfuscate_id / deobfuscate_id)
and the approval-action dispatcher that synchronizes status changes across
domain entities.

Extracted from main_commented (1).py lines 861–922.
"""
import base64
import uuid
from typing import Optional, List

from supabase import Client

from app.core.logging import logger


# ---------------------------------------------------------------------------
# ID obfuscation helpers
# ---------------------------------------------------------------------------

def obfuscate_id(raw_id: str) -> str:
    """
    Convert a real UUID into a short, URL-safe obfuscated string.

    e.g. '3fa85f64-...' -> 'rec_O6hfZFcX...'

    This is obfuscation for tidiness in public URLs, NOT encryption.
    """
    if not raw_id:
        return ""
    try:
        u = uuid.UUID(raw_id)
        encoded = base64.urlsafe_b64encode(u.bytes).decode("utf-8").rstrip("=")
        return f"rec_{encoded}"
    except Exception:
        return raw_id


def deobfuscate_id(obfuscated_id: str) -> str:
    """
    Convert an obfuscated 'rec_...' string back to the original UUID.

    Passes real UUIDs through unchanged so the same function works
    whether the caller supplies an obfuscated or a plain UUID.
    """
    if not obfuscated_id:
        return ""
    clean_id = obfuscated_id
    if clean_id.startswith("rec_"):
        clean_id = clean_id[4:]
    try:
        padding = "=" * (4 - len(clean_id) % 4)
        bytes_data = base64.urlsafe_b64decode(clean_id + padding)
        return str(uuid.UUID(bytes=bytes_data))
    except Exception:
        return obfuscated_id


# ---------------------------------------------------------------------------
# Approval action dispatcher
# ---------------------------------------------------------------------------

def process_approval_action(
    db: Client, entity_type: str, entity_id: str, action: str = "approve"
) -> None:
    """
    Synchronize a simple approve/reject action to the correct domain table.

    Used by the older single-step approval mechanism. The newer multi-stage
    pipeline system handles its own state transitions separately.
    """
    if action == "approve":
        if entity_type in ("job", "job_opening", "job_openings"):
            from datetime import datetime

            db.table("job_openings").update(
                {"status": "published", "published_at": datetime.utcnow().isoformat()}
            ).eq("id", entity_id).execute()
        elif entity_type in ("requirement", "mandate", "requirements"):
            db.table("requirements").update({"status": "approved"}).eq(
                "id", entity_id
            ).execute()
        elif entity_type in ("application", "candidate_application", "applications"):
            db.table("applications").update({"stage": "approved"}).eq(
                "id", entity_id
            ).execute()


def user_can_manage_pipelines(db: Client, user_id: Optional[str], user_email: Optional[str], pipeline_creator_id: Optional[str] = None) -> bool:
    clean_email = user_email.strip().lower() if user_email else None
    
    if user_id and not user_id.startswith("user_"):
        m_res = db.table("members").select("is_primary_admin, id").eq("id", user_id).execute()
        if m_res.data and m_res.data[0].get("is_primary_admin"):
            return True
                
    if clean_email:
        m_res = db.table("members").select("is_primary_admin, id").ilike("email", clean_email).execute()
        if m_res.data and m_res.data[0].get("is_primary_admin"):
            return True

    user_role_ids = set()
    if clean_email:
        m_res = db.table("members").select("id").ilike("email", clean_email).execute()
        if m_res.data:
            mem = m_res.data[0]
            mr_res = db.table("member_roles").select("role_id").eq("member_id", mem["id"]).execute()
            for mr in (mr_res.data or []):
                if mr.get("role_id"):
                    user_role_ids.add(mr["role_id"])

    if user_id and not user_id.startswith("user_"):
        mr_res = db.table("member_roles").select("role_id").eq("member_id", user_id).execute()
        for mr in (mr_res.data or []):
            if mr.get("role_id"):
                user_role_ids.add(mr["role_id"])
        
    for r_id in user_role_ids:
        rp_res = db.table("role_permissions").select("*").eq("role_id", r_id).execute()
        if rp_res.data:
            rp = rp_res.data[0]
            if rp.get("recruiter_pipelines") or rp.get("administrator"):
                return True
                
    return False

# ENDPOINT: DELETE /api/v1/approvals/pipelines/{id} — permanently delete a
# pipeline and all of its stages/approvers/logs/rejection records.


def get_stage_approver_emails(db: Client, stage_id: str) -> List[str]:
    apprs_res = db.table("approval_stage_approvers").select("member_id, role_id").eq("stage_id", stage_id).execute()
    apprs = apprs_res.data or []
    emails = set()
    
    for a in apprs:
        m_id = a.get("member_id")
        r_id = a.get("role_id")
        
        if m_id:
            m_res = db.table("members").select("email").eq("id", m_id).execute()
            if m_res.data and m_res.data[0].get("email"):
                emails.add(m_res.data[0]["email"].strip().lower())
                
        if r_id:
            mr_res = db.table("member_roles").select("members(email)").eq("role_id", r_id).execute()
            for mr in (mr_res.data or []):
                mem = mr.get("members") or {}
                if isinstance(mem, dict) and mem.get("email"):
                    emails.add(mem["email"].strip().lower())
                elif isinstance(mem, list) and len(mem) > 0 and mem[0].get("email"):
                    emails.add(mem[0]["email"].strip().lower())
                    
    return list(emails)

# HELPER: user_can_approve_stage — permission check: is this specific
# logged-in user (by id or email) allowed to approve/reject this
# particular pipeline stage?


def user_can_approve_stage(db: Client, stage_id: str, user_id: Optional[str], user_email: Optional[str]) -> bool:
    clean_email = user_email.strip().lower() if user_email else None
    
    if user_id and not user_id.startswith("user_"):
        m_res = db.table("members").select("is_primary_admin").eq("id", user_id).execute()
        if m_res.data and m_res.data[0].get("is_primary_admin"):
            return True
    if clean_email:
        m_res = db.table("members").select("is_primary_admin").ilike("email", clean_email).execute()
        if m_res.data and m_res.data[0].get("is_primary_admin"):
            return True
            
    approver_emails = get_stage_approver_emails(db, stage_id)
    if not approver_emails:
        return True
        
    if clean_email and clean_email in approver_emails:
        return True
        
    return False

# Shape of the data needed to manually trigger an approval-related
# notification email.


# HELPER: dispatch_approval_notifications — sends a formatted HTML
# notification email to a list of approver email addresses (e.g. "a stage
# is now waiting on your approval"), and also creates matching in-app
# notification rows so approvers see it in both places.

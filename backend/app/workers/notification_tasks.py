"""
Notification background tasks.

Background functions for sending WhatsApp notifications via n8n webhook
and for dispatching approval workflow email notifications.

Extracted from main_commented (1).py lines 2425–2507.
"""
import os
import re
from typing import Dict, Optional

import httpx

from app.core.logging import logger
from app.integrations.supabase_client import get_admin_supabase_client


def send_whatsapp_notification_sync(
    phone: str,
    message: str,
    candidate_name: str,
    job_title: str,
    event_type: str,
) -> bool:
    """
    Send a WhatsApp message via the n8n WhatsApp webhook (synchronous).

    Strips non-digit characters from phone number before sending.
    Returns True on success, False on failure.

    Extracted from main_commented (1).py line 2425.
    """
    cleaned_phone = re.sub(r"[^\d]", "", phone)
    if not cleaned_phone:
        logger.warning(f"No valid digits found in phone number: '{phone}' — skipping WhatsApp.")
        return False

    url = os.getenv(
        "N8N_WHATSAPP_WEBHOOK_URL",
        "https://n8n.srv832341.hstgr.cloud/webhook/57c713ae-2169-4f8a-999d-f939a52f0a82",
    )
    payload = {
        "phone": cleaned_phone,
        "number": cleaned_phone,
        "message": message,
        "text": message,
        "candidate_name": candidate_name,
        "job_title": job_title,
        "event_type": event_type,
    }

    logger.info(f"Sending WhatsApp notification to {cleaned_phone} via n8n webhook")
    try:
        with httpx.Client() as client:
            res = client.post(url, json=payload, timeout=20.0)
            if res.status_code in (200, 201, 202, 204):
                logger.info(f"WhatsApp notification sent for {candidate_name} (status {res.status_code})")
                return True
            logger.error(f"WhatsApp notification failed. Status: {res.status_code}, Response: {res.text}")
            return False
    except Exception as exc:
        logger.error(f"Error sending WhatsApp notification: {exc}")
        return False


def trigger_whatsapp_notification_background(
    jwt_token: str,
    candidate_id: str,
    job_opening_id: str,
    event_type: str,
    extra_data: Optional[Dict] = None,
) -> None:
    """
    Resolve candidate/job info and send a WhatsApp notification message.

    Builds a context-appropriate message text based on `event_type`.
    Skipped entirely if the candidate has no phone number on file.

    Extracted from main_commented (1).py line 2462.
    """
    logger.info(
        f"[WHATSAPP] trigger_whatsapp_notification_background invoked for "
        f"candidate={candidate_id}, job={job_opening_id}, event={event_type}"
    )
    db = get_admin_supabase_client()
    try:
        cand_res = (
            db.table("candidates").select("full_name, phone").eq("id", candidate_id).execute()
        )
        logger.info(f"[WHATSAPP] candidate lookup results: {cand_res.data}")
        if not cand_res.data:
            logger.warning(f"Candidate {candidate_id} not found, skipping WhatsApp notification.")
            return

        cand = cand_res.data[0]
        phone = cand.get("phone")
        full_name = cand.get("full_name") or "Candidate"

        if not phone:
            logger.info(f"Candidate '{full_name}' has no phone number — skipping WhatsApp notification.")
            return

        job_title = "Active Job Opening"
        try:
            job_res = (
                db.table("job_openings").select("title").eq("id", job_opening_id).execute()
            )
            if job_res.data:
                job_title = job_res.data[0].get("title") or "Active Job Opening"
        except Exception as exc:
            logger.error(f"Failed to fetch job title for WhatsApp notification: {exc}")

        # Build event-specific message
        if event_type == "application_submitted":
            message = (
                f"Hello {full_name}, your application for the '{job_title}' role has been "
                f"successfully submitted! We will review it shortly. Thank you."
            )
        elif event_type == "application_accepted":
            message = (
                f"Hello {full_name}, great news! Your application for the '{job_title}' role has "
                f"been accepted. We will contact you regarding the next steps."
            )
        elif event_type == "application_rejected":
            message = (
                f"Hello {full_name}, thank you for your interest in the '{job_title}' role. "
                f"Unfortunately, we have decided to proceed with other candidates at this time."
            )
        elif event_type == "stage_updated":
            stage = (extra_data or {}).get("stage") or "next stage"
            status = (extra_data or {}).get("status") or ""
            status_text = f" ({status})" if status else ""
            message = (
                f"Hello {full_name}, your application status for the '{job_title}' role has been "
                f"updated to: {stage}{status_text}."
            )
        else:
            message = (
                f"Hello {full_name}, there is an update regarding your application for the "
                f"'{job_title}' role."
            )

        send_whatsapp_notification_sync(phone, message, full_name, job_title, event_type)
    except Exception as exc:
        logger.error(f"Error in trigger_whatsapp_notification_background: {exc}")

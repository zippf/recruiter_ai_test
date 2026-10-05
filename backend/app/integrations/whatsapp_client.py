import os
import re

import httpx

from app.core.logging import logger


def send_whatsapp_notification(
    phone: str, message: str, candidate_name: str, job_title: str, event_type: str
):
    cleaned_phone = re.sub(r"[^\d]", "", phone)
    if not cleaned_phone:
        logger.warning(
            f"No valid digits found in phone number: '{phone}' for WhatsApp notification."
        )
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
            response = client.post(url, json=payload, timeout=20.0)
            if response.status_code in (200, 201, 202, 204):
                logger.info(
                    f"WhatsApp notification sent successfully for {candidate_name} "
                    f"(status: {response.status_code})"
                )
                return True
            logger.error(
                f"Failed to send WhatsApp notification. Status: {response.status_code}, "
                f"Response: {response.text}"
            )
            return False
    except Exception as exc:
        logger.error(f"Error sending WhatsApp notification: {exc}")
        return False

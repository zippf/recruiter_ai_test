"""
Notification service.

Handles creating in-app system notifications and the audit activity_log.

Extracted from main_commented (1).py lines 1007–1067.
"""
from typing import Optional, List, Optional

import jwt
from supabase import Client

from app.core.logging import logger


def create_system_notification(
    db: Client,
    recruiter_id: Optional[str],
    title: str,
    message: str,
    type: str,
    metadata: Optional[dict] = None,
) -> None:
    """
    Insert a notification row for a recruiter.

    If recruiter_id is missing, attempts to resolve it from the DB client's
    Authorization header, then falls back to the first profile in the table.
    """
    if not recruiter_id and db and hasattr(db, "options") and db.options and hasattr(db.options, "headers"):
        auth_header = db.options.headers.get("Authorization") or db.options.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            if token and not token.endswith(".key") and token.startswith("eyJ"):
                try:
                    payload = jwt.decode(token, options={"verify_signature": False})
                    recruiter_id = payload.get("sub")
                except Exception as jwt_err:
                    logger.debug(
                        f"Failed to decode Authorization header in create_system_notification: {jwt_err}"
                    )

    if not recruiter_id:
        try:
            p_res = db.table("profiles").select("id").limit(1).execute()
            if p_res.data:
                recruiter_id = p_res.data[0].get("id")
                logger.info(f"Fallback recruiter ID resolved from profiles table: {recruiter_id}")
        except Exception as pe:
            logger.warning(f"Failed to lookup fallback profile: {pe}")

    if not recruiter_id:
        logger.warning(f"Could not insert notification '{title}' because recruiter_id is empty")
        return

    try:
        db.table("notifications").insert(
            {
                "recruiter_id": recruiter_id,
                "title": title,
                "message": message,
                "type": type,
                "metadata": metadata or {},
            }
        ).execute()
        logger.info(f"System notification created: '{title}' for user {recruiter_id}")
    except Exception as exc:
        logger.error(f"Failed to insert notification: {exc}")


def log_activity_event(
    db: Client,
    action: str,
    entity_type: str,
    entity_id: str,
    actor_name: str = "Recruiter",
    actor_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Write a row to activity_log — the permanent audit trail of all platform actions.

    Distinct from notifications: activity_log is historical; notifications
    are real-time user alerts.
    """
    try:
        payload = {
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_name": actor_name,
            "metadata": metadata or {},
        }
        if actor_id:
            payload["actor_id"] = actor_id
        if organization_id:
            payload["organization_id"] = organization_id
        db.table("activity_log").insert(payload).execute()
        logger.info(f"Activity logged: {action} on {entity_type} {entity_id}")
    except Exception as exc:
        logger.error(f"Failed to log activity: {exc}")


def dispatch_approval_notifications(
    db: Client,
    recipient_emails: List[str],
    title: str,
    message: str,
    html_body: str,
    pipeline_id: Optional[str] = None
):
    if not recipient_emails:
        return

    for email in recipient_emails:
        clean_email = email.strip().lower()
        if not clean_email or "@" not in clean_email:
            continue

        try:
            send_email(
                to_email=clean_email,
                subject=f"[Kozker Approvals] {title}",
                html_body=html_body,
                sender_name="Kozker Approval Operations"
            )
        except Exception as e:
            logger.error(f"Failed to send approval email to {clean_email}: {e}")

        try:
            p_res = db.table("profiles").select("id").ilike("email", clean_email).execute()
            if p_res.data and p_res.data[0].get("id"):
                profile_id = p_res.data[0]["id"]
                db.table("notifications").insert({
                    "recruiter_id": profile_id,
                    "title": title,
                    "message": message,
                    "type": "job_generation",
                    "is_read": False,
                    "metadata": {"pipeline_id": pipeline_id, "recipient_email": clean_email} if pipeline_id else {}
                }).execute()
        except Exception as ne:
            logger.error(f"Failed to create in-app notification for {clean_email}: {ne}")



def send_email(to_email: str, subject: str, html_body: str, reply_to: Optional[str] = None, sender_name: Optional[str] = None):
    import smtplib
    import os
    import re
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import datetime
    
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "noreply@kozker.ai")
    
    # Log to console & requests.log for local audit
    log_msg = f"\n========================================\n[EMAIL DISPATCH] To: {to_email}\nSubject: {subject}\nReply-To: {reply_to}\nSender-Name: {sender_name}\nBody:\n{html_body}\n========================================\n"
    logger.info(log_msg)
    
    try:
        with open("requests.log", "a") as f:
            f.write(f"[{datetime.utcnow().isoformat()}] EMAIL To: {to_email} | Subject: {subject} | Reply-To: {reply_to}\n{html_body}\n\n")
    except Exception as le:
        logger.error(f"Failed to write email to requests.log: {le}")
        
    if not (smtp_host and smtp_port and smtp_user and smtp_pass):
        raise ValueError("SMTP configuration variables (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD) are missing or inactive on the server.")
        
    if smtp_host and smtp_port and smtp_user and smtp_pass:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            if sender_name:
                msg["From"] = f"{sender_name} <{smtp_from}>"
            else:
                msg["From"] = smtp_from
            msg["To"] = to_email
            if reply_to:
                msg["Reply-To"] = reply_to
            
            text_body = re.sub('<[^<]+?>', '', html_body)
            
            part1 = MIMEText(text_body, "plain")
            part2 = MIMEText(html_body, "html")
            
            msg.attach(part1)
            msg.attach(part2)
            
            port = int(smtp_port)
            if port == 465:
                server = smtplib.SMTP_SSL(smtp_host, port)
            else:
                server = smtplib.SMTP(smtp_host, port)
                server.starttls()
                
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, to_email, msg.as_string())
            server.quit()
            logger.info(f"Email successfully sent via SMTP to {to_email}")
        except Exception as e:
            logger.error(f"Failed to send email via SMTP to {to_email}: {e}")
            raise e
    else:
        logger.info(f"SMTP is not configured. Email to {to_email} was logged to console and requests.log.")
        raise Exception("SMTP mail configuration parameters (SMTP_HOST, SMTP_PORT, etc.) are missing from the server environment.")

def send_application_confirmation_email(to_email: str, full_name: str, job_title: str, client_name: str, application_id: str, form_responses: dict):
    subject = f"Application Received: {job_title} at {client_name}"
    html_body = f"<p>Dear {full_name},</p><p>Your application for <strong>{job_title}</strong> at <strong>{client_name}</strong> has been received successfully.</p><p>Application ID: {application_id}</p>"
    try:
        send_email(to_email=to_email, subject=subject, html_body=html_body)
    except Exception as e:
        logger.error(f"Error sending confirmation email to {to_email}: {e}")

# =============================================================================
# CANDIDATE QUERIES — public Q&A widget on job posting pages
# =============================================================================
# Lets a candidate ask a question about a job posting without needing to
# log in, get an instant auto-generated answer, and lets recruiters review
# / manually answer / resolve those questions afterward.

# ENDPOINT: POST /api/v1/jobs/{job_id}/queries — a candidate submits a
# question; this looks up the job, generates an automatic answer (see
# generate_candidate_query_response above), saves it, and notifies the
# recruiter. If saving to the database fails for any reason, it falls back
# to keeping the query in the in-memory dictionary so nothing is silently
# lost.
# 10. Candidate queries endpoints

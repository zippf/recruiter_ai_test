import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.logging import logger


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    reply_to: Optional[str] = None,
    sender_name: Optional[str] = None,
):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "noreply@kozker.ai")

    log_msg = (
        f"\n========================================\n[EMAIL DISPATCH] To: {to_email}\n"
        f"Subject: {subject}\nReply-To: {reply_to}\nSender-Name: {sender_name}\n"
        f"Body:\n{html_body}\n========================================\n"
    )
    logger.info(log_msg)
    try:
        with open("requests.log", "a") as log_file:
            log_file.write(
                f"[{datetime.utcnow().isoformat()}] EMAIL To: {to_email} | "
                f"Subject: {subject} | Reply-To: {reply_to}\n{html_body}\n\n"
            )
    except Exception as exc:
        logger.error(f"Failed to write email to requests.log: {exc}")

    if not (smtp_host and smtp_port and smtp_user and smtp_pass):
        raise ValueError(
            "SMTP configuration variables (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD) are missing or inactive on the server."
        )

    try:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"{sender_name} <{smtp_from}>" if sender_name else smtp_from
        message["To"] = to_email
        if reply_to:
            message["Reply-To"] = reply_to
        message.attach(MIMEText(re.sub("<[^<]+?>", "", html_body), "plain"))
        message.attach(MIMEText(html_body, "html"))

        port = int(smtp_port)
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_host, port)
        else:
            server = smtplib.SMTP(smtp_host, port)
            server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_from, to_email, message.as_string())
        server.quit()
        logger.info(f"Email successfully sent via SMTP to {to_email}")
    except Exception as exc:
        logger.error(f"Failed to send email via SMTP to {to_email}: {exc}")
        raise

"""
Google Drive integration client.

Provides helpers for detecting Google Drive URLs and converting them into
direct-download links that the server can fetch without browser authentication.

Extracted from main_commented (1).py lines 1133–1151.
"""
import re


def is_google_drive_url(url: str) -> bool:
    """Return True if the URL is a Google Drive share link."""
    if not url:
        return False
    return "drive.google.com" in url


def get_drive_download_url(url: str) -> str:
    """
    Convert a Google Drive share URL into a direct-download URL.

    Handles both /file/d/<ID>/view and ?id=<ID> URL formats.
    Returns the original URL unchanged if no known pattern is found.
    """
    # Standard /file/d/<ID>/view structure
    match_d = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
    if match_d:
        file_id = match_d.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    # Query-parameter structure id=<ID>
    match_id = re.search(r"id=([a-zA-Z0-9_-]+)", url)
    if match_id:
        file_id = match_id.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    return url

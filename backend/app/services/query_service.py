"""
Query service.

Handles the candidate Q&A / public query feature: generating AI-like rule-based
responses to candidate questions about a job, and persisting them.

Extracted from main_commented (1).py line 3630.
"""
import re
from typing import Any, Dict, List, Optional

from supabase import Client

from app.core.logging import logger

# In-memory store for candidate queries, mapped by job_id
in_memory_queries: Dict[str, List[Dict[str, Any]]] = {}

def generate_candidate_query_response(job: Dict[str, Any], query_text: str) -> str:
    """
    Generate a context-aware response to a candidate's query about a job.

    Uses a rule-based approach with keyword matching against job fields.
    Preserves the exact logic from the monolith (line 3630).
    """
    query = query_text.lower()
    title = job.get("title") or "this role"

    # 1. Salary query
    if any(k in query for k in ["salary", "pay", "compensation", "package", "lpa", "ctc", "remuneration", "money"]):
        sal = job.get("salary_range")
        if sal and sal.strip():
            return f"The salary range for the {title} position is {sal}."
        return f"The salary range for the {title} position is not explicitly specified. We have forwarded your question to the hiring team."

    # 2. Experience query
    if any(k in query for k in ["experience", "years", "yrs", "how long", "mid", "senior", "junior"]):
        quals = job.get("qualifications") or []
        exp_mentions = [q for q in quals if "year" in q.lower() or "experience" in q.lower()]
        if exp_mentions:
            return f"Regarding experience requirements for {title}: " + " ".join(exp_mentions)
        return "Please review the preferred qualifications. Typically, relevant industry experience in similar roles is preferred. We have alerted the recruiter to clarify this for you."

    # 3. Location / Remote query
    if any(k in query for k in ["location", "remote", "wfh", "office", "hybrid", "city", "where"]):
        desc = job.get("description", "")
        loc_match = re.search(r"(remote|hybrid|office|on-site|location)", desc, re.IGNORECASE)
        if loc_match:
            return f"Regarding location: The role description mentions '{loc_match.group(0)}'. Please review the full job description details on this page."
        return "This role's location / work model (remote/hybrid/on-site) is not explicitly listed. We have forwarded this query to the hiring team."

    # 4. Responsibilities query
    if any(k in query for k in ["responsibility", "responsibilities", "duties", "duty", "do", "task", "day to day", "role"]):
        resps = job.get("responsibilities") or []
        if resps:
            bullets = "\n".join([f"- {r}" for r in resps[:4]])
            return f"Key responsibilities for this role include:\n{bullets}"
        return "Responsibilities for this role include delivering on the goals outlined in the job description. The recruiter has been notified of your inquiry."

    # 5. Skills / Tech stack query
    if any(k in query for k in ["skill", "skills", "tech", "technology", "technologies", "language", "framework", "database"]):
        keywords = job.get("keywords") or []
        quals = job.get("qualifications") or []
        skills_mentioned = [q for q in quals if any(kw.lower() in q.lower() for kw in keywords)]
        tech_list = ", ".join(keywords) if keywords else ""
        resp = ""
        if tech_list:
            resp += f"The key technologies and skills mentioned for this role are: {tech_list}. "
        if skills_mentioned:
            resp += "\nPreferred qualifications: " + " ".join(skills_mentioned[:2])
        if resp:
            return resp.strip()
        return "The required skills are detailed in the job opening description and qualifications. We have forwarded your tech stack query to the team."

    # 6. Qualifications query
    if any(k in query for k in ["qualification", "qualifications", "require", "requirements", "degree", "education", "background"]):
        quals = job.get("qualifications") or []
        if quals:
            bullets = "\n".join([f"- {q}" for q in quals[:4]])
            return f"Preferred qualifications for this role:\n{bullets}"
        return "The qualifications for this position are listed in the details panel. We have notified the hiring team of your question."

    # 7. Generic fallback
    client = job.get("client_name")
    client_str = f" with {client}" if client else ""
    return f"Thank you for your question regarding the {title} position{client_str}. We have recorded your query and forwarded it to our hiring team for review."

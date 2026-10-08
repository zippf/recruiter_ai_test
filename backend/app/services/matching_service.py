"""
Matching service.

Contains the local-fallback candidate-to-job matching logic used when the
n8n AI matching workflow is disabled (USE_N8N=False).

Extracted from main_commented (1).py lines 4483–4596.
"""
from typing import Any, Dict, List, Optional, Tuple

from supabase import Client

from app.core.logging import logger


def evaluate_candidate_matching_with_history(
    db: Client,
    cand_id: str,
    job_id: str,
    approved_skills: list,
    cand_skills: list,
    cand_raw_text: str,
) -> Tuple[float, str, List[str], List[str]]:
    """
    Score a candidate against a job's approved skills, then adjust the score
    using the candidate's historical performance across other applications.

    Returns (matched_score, match_reason, strengths, skill_gaps).

    Preserves the exact algorithm from the monolith (line 4483).
    """
    # 1. Base skill match — start at 45 and add/subtract per skill.
    matched_score = 45.0
    strengths: List[str] = []
    skill_gaps: List[str] = []

    for sk in approved_skills:
        if not sk:
            continue
        if isinstance(sk, str):
            sk_name = sk.lower()
            sk_weight = 10.0
        elif isinstance(sk, dict):
            sk_name = (sk.get("skill_name") or sk.get("name") or "").lower()
            if not sk_name:
                continue
            try:
                sk_weight = float(sk.get("weight") if sk.get("weight") is not None else 10.0)
            except Exception:
                sk_weight = 10.0
        else:
            continue

        if sk_name in cand_skills or sk_name in cand_raw_text.lower():
            matched_score += sk_weight * 0.5
            strengths.append(sk.get("skill_name") if isinstance(sk, dict) else sk)
        else:
            skill_gaps.append(sk.get("skill_name") if isinstance(sk, dict) else sk)

    matched_score = min(matched_score, 100.0)

    # 2. Historical performance adjustment
    other_apps_res = (
        db.table("applications")
        .select("*, job_openings(title)")
        .eq("candidate_id", cand_id)
        .neq("job_opening_id", job_id)
        .execute()
    )
    other_apps = other_apps_res.data or []

    other_app_ids = [oa["id"] for oa in other_apps]
    other_stages: List[Dict[str, Any]] = []
    if other_app_ids:
        stages_res = (
            db.table("interview_stages")
            .select("*")
            .in_("application_id", other_app_ids)
            .execute()
        )
        other_stages = stages_res.data or []

    score_adjustment = 0.0
    perf_summaries: List[str] = []

    for app in other_apps:
        job_data = app.get("job_openings")
        if isinstance(job_data, list) and job_data:
            job_data = job_data[0]
        elif not isinstance(job_data, dict):
            job_data = {}
        job_title = job_data.get("title", "Other Job")
        app_stage = app.get("stage")
        app_status = app.get("stage_status")
        app_notes = app.get("stage_notes")
        app_stages = [stg for stg in other_stages if stg["application_id"] == app["id"]]

        if app_stage == "hired":
            score_adjustment += 12.0
            perf_summaries.append(f"Successfully Hired for '{job_title}'")
        elif app_stage == "rejected" or app_status == "failed":
            score_adjustment -= 10.0
            perf_summaries.append(f"Rejected/Failed for '{job_title}'")
        elif app_notes:
            perf_summaries.append(f"Applied to '{job_title}' (Notes: {app_notes})")

        for stg in app_stages:
            outcome = stg.get("outcome")
            notes = stg.get("notes")
            round_name = stg.get("stage_name", "interview")
            if outcome == "passed":
                score_adjustment += 3.0
            elif outcome == "failed":
                score_adjustment -= 6.0
                if notes:
                    perf_summaries.append(f"Failed {round_name} stage (Notes: {notes})")
                else:
                    perf_summaries.append(f"Failed {round_name} stage")
            elif outcome == "on_hold":
                score_adjustment += 1.0
                if notes:
                    perf_summaries.append(f"On hold in {round_name} stage (Notes: {notes})")
            elif notes:
                perf_summaries.append(f"{round_name} stage feedback: {notes}")

    matched_score += score_adjustment
    matched_score = max(min(matched_score, 100.0), 0.0)

    match_reason = (
        f"System scan matched skills: {', '.join(strengths)}. Missing: {', '.join(skill_gaps)}."
    )
    if perf_summaries:
        perf_text = " Previous Performance Considerations: " + "; ".join(perf_summaries) + "."
        match_reason += perf_text

    return matched_score, match_reason, strengths, skill_gaps

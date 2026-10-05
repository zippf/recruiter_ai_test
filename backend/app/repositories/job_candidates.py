from supabase import Client


def find_job_requirement(db: Client, job_id: str):
    return db.table("job_openings").select("requirement_id").eq("id", job_id).execute()


def find_requirement_owner(db: Client, requirement_id: str):
    return (
        db.table("requirements").select("created_by").eq("id", requirement_id).execute()
    )


def list_ranked_candidates(db: Client, job_id: str):
    return (
        db.table("job_candidates")
        .select("*, candidates(*), applications(*)")
        .eq("job_opening_id", job_id)
        .order("created_at", desc=True)
        .execute()
    )


def find_application_for_candidate_job(db: Client, candidate_id: str, job_id: str):
    return (
        db.table("applications")
        .select("*")
        .eq("candidate_id", candidate_id)
        .eq("job_opening_id", job_id)
        .execute()
    )


def link_job_candidate_application(db: Client, row_id: str, application_id: str):
    return (
        db.table("job_candidates")
        .update({"application_id": application_id})
        .eq("id", row_id)
        .execute()
    )

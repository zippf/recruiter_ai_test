from supabase import Client


def insert_candidate_query(db: Client, payload: dict):
    return db.table("candidate_queries").insert(payload).execute()


def list_candidate_queries(db: Client, job_id: str, email: str | None = None):
    query = db.table("candidate_queries").select("*").eq("job_id", job_id)
    if email:
        query = query.eq("candidate_email", email.strip())
    return query.order("created_at", desc=True).execute()


def update_candidate_query(db: Client, query_id: str, is_resolved: bool):
    return (
        db.table("candidate_queries")
        .update({"is_resolved": is_resolved})
        .eq("id", query_id)
        .execute()
    )

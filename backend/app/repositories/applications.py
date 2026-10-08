from supabase import Client


_APPLICATION_DETAIL_COLUMNS = "*, candidates(*), job_openings(requirement_id)"


def find_application(db: Client, application_id: str):
    return (
        db.table("applications")
        .select(_APPLICATION_DETAIL_COLUMNS)
        .eq("id", application_id)
        .execute()
    )


def update_application_status(db: Client, application_id: str, status: str):
    return (
        db.table("applications")
        .update({"screening_status": status})
        .eq("id", application_id)
        .execute()
    )


def list_application_stages(db: Client, application_id: str):
    return (
        db.table("interview_stages")
        .select("*")
        .eq("application_id", application_id)
        .order("created_at", desc=False)
        .execute()
    )


def update_application_stage_record(
    db: Client, application_id: str, stage: str, stage_status: str, notes: str
):
    return (
        db.table("applications")
        .update({"stage": stage, "stage_status": stage_status, "stage_notes": notes})
        .eq("id", application_id)
        .execute()
    )


def list_stage_ids(db: Client, application_id: str):
    return (
        db.table("interview_stages")
        .select("id")
        .eq("application_id", application_id)
        .execute()
    )


def insert_interview_stage(db: Client, payload: dict):
    return db.table("interview_stages").insert(payload).execute()


def find_job_custom_stages(db: Client, job_id: str):
    return db.table("job_openings").select("custom_stages").eq("id", job_id).execute()


def find_application_questions(db: Client, application_id: str):
    return (
        db.table("applications")
        .select("screening_questions")
        .eq("id", application_id)
        .execute()
    )


def update_application_questions(
    db: Client, application_id: str, questions: list[dict]
):
    return (
        db.table("applications")
        .update({"screening_questions": questions})
        .eq("id", application_id)
        .execute()
    )


def find_application_containing_question(db: Client, question_id: str):
    filter_value = '[{"id": "' + question_id + '"}]'
    result = (
        db.table("applications")
        .select("*")
        .filter("screening_questions", "cs", filter_value)
        .execute()
    )
    return result if result.data else db.table("applications").select("*").execute()

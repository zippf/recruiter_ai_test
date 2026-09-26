


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "supabase_vault" WITH SCHEMA "vault";






CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA "extensions";






CREATE OR REPLACE FUNCTION "public"."check_stage_notes_on_failure"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    IF NEW.outcome = 'failed' AND (NEW.notes IS NULL OR TRIM(NEW.notes) = '') THEN
        RAISE EXCEPTION 'Failure notes are required when setting interview stage outcome to failed.';
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."check_stage_notes_on_failure"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."handle_candidate_deduplication"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.candidates WHERE email = NEW.email AND is_deleted = FALSE) THEN
        UPDATE public.candidates
        SET 
            full_name = NEW.full_name,
            phone = COALESCE(NEW.phone, phone),
            skills = COALESCE(NEW.skills, skills),
            experience_years = COALESCE(NEW.experience_years, experience_years),
            current_company = COALESCE(NEW.current_company, current_company),
            resume_url = COALESCE(NEW.resume_url, resume_url),
            parsed_resume_json = COALESCE(NEW.parsed_resume_json, parsed_resume_json),
            source = COALESCE(NEW.source, source),
            updated_at = timezone('utc'::text, now())
        WHERE email = NEW.email AND is_deleted = FALSE;
        
        RETURN NULL; -- Block insertion since we updated the existing row
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."handle_candidate_deduplication"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."handle_new_user"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
BEGIN
    INSERT INTO public.profiles (id, email, full_name, role, is_active, is_onboarded)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', ''),
        'recruiter',
        TRUE,
        FALSE
    )
    ON CONFLICT (id) DO UPDATE
    SET email = EXCLUDED.email,
        full_name = COALESCE(EXCLUDED.full_name, profiles.full_name);
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."handle_new_user"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."handle_update_timestamp"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."handle_update_timestamp"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."is_admin"() RETURNS boolean
    LANGUAGE "sql" SECURITY DEFINER
    AS $$
    SELECT COALESCE(
        EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin'),
        FALSE
    );
$$;


ALTER FUNCTION "public"."is_admin"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."is_manager"() RETURNS boolean
    LANGUAGE "sql" SECURITY DEFINER
    AS $$
    SELECT COALESCE(
        EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'manager'),
        FALSE
    );
$$;


ALTER FUNCTION "public"."is_manager"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."is_recruiter"() RETURNS boolean
    LANGUAGE "sql" SECURITY DEFINER
    AS $$
    SELECT COALESCE(
        EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'recruiter'),
        FALSE
    );
$$;


ALTER FUNCTION "public"."is_recruiter"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."log_record_changes"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
DECLARE
    current_org_id TEXT;
    current_actor_email TEXT;
    action_str TEXT;
BEGIN
    current_actor_email := current_setting('request.jwt.claims', true)::json->>'email';

    IF TG_OP = 'INSERT' THEN
        action_str := 'create';
        current_org_id := (to_jsonb(NEW)->>'organization_id');
    ELSIF TG_OP = 'UPDATE' THEN
        action_str := 'update';
        current_org_id := (to_jsonb(NEW)->>'organization_id');
    ELSIF TG_OP = 'DELETE' THEN
        action_str := 'delete';
        current_org_id := (to_jsonb(OLD)->>'organization_id');
    END IF;

    INSERT INTO public.audit_logs (
        organization_id,
        actor_email,
        actor_name,
        action_type,
        action_description,
        target_name,
        target_entity_type,
        target_entity_id,
        old_state,
        new_state
    ) VALUES (
        current_org_id,
        COALESCE(current_actor_email, 'system'),
        COALESCE(current_actor_email, 'system'),
        action_str,
        TG_OP || ' executed on table ' || TG_TABLE_NAME,
        COALESCE(to_jsonb(NEW)->>'id', to_jsonb(OLD)->>'id'),
        TG_TABLE_NAME,
        COALESCE(to_jsonb(NEW)->>'id', to_jsonb(OLD)->>'id'),
        CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) ELSE NULL END,
        CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) ELSE NULL END
    );

    RETURN COALESCE(NEW, OLD);
END;
$$;


ALTER FUNCTION "public"."log_record_changes"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."prune_activity_logs"("p_before_timestamp" timestamp with time zone, "p_organization_id" "text" DEFAULT NULL::"text") RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
DECLARE
    v_deleted_count INTEGER;
BEGIN
    IF p_organization_id IS NOT NULL AND p_organization_id <> '' THEN
        DELETE FROM public.activity_log
        WHERE created_at < p_before_timestamp
          AND (organization_id = p_organization_id OR organization_id IS NULL);
    ELSE
        DELETE FROM public.activity_log
        WHERE created_at < p_before_timestamp;
    END IF;
    
    GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
    RETURN v_deleted_count;
END;
$$;


ALTER FUNCTION "public"."prune_activity_logs"("p_before_timestamp" timestamp with time zone, "p_organization_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."upsert_linkedin_account"("p_user_id" "uuid", "p_linkedin_member_id" "text", "p_linkedin_access_token" "text", "p_linkedin_refresh_token" "text", "p_expires_at" timestamp with time zone) RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
BEGIN
    INSERT INTO public.linkedin_accounts (
        user_id,
        linkedin_member_id,
        linkedin_access_token,
        linkedin_refresh_token,
        expires_at,
        updated_at
    )
    VALUES (
        p_user_id,
        p_linkedin_member_id,
        p_linkedin_access_token,
        p_linkedin_refresh_token,
        p_expires_at,
        NOW()
    )
    ON CONFLICT (user_id)
    DO UPDATE SET
        linkedin_member_id = EXCLUDED.linkedin_member_id,
        linkedin_access_token = EXCLUDED.linkedin_access_token,
        linkedin_refresh_token = EXCLUDED.linkedin_refresh_token,
        expires_at = EXCLUDED.expires_at,
        updated_at = NOW();
END;
$$;


ALTER FUNCTION "public"."upsert_linkedin_account"("p_user_id" "uuid", "p_linkedin_member_id" "text", "p_linkedin_access_token" "text", "p_linkedin_refresh_token" "text", "p_expires_at" timestamp with time zone) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."validate_job_skills_weight"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_total_weight NUMERIC;
BEGIN
    -- Only run validation when a job opening's status is changed to 'confirmed' or 'published'
    IF NEW.status IN ('confirmed', 'published') THEN
        SELECT COALESCE(SUM((skill->>'weight')::NUMERIC), 0) INTO v_total_weight
        FROM public.job_opening_skills jos,
             jsonb_array_elements(jos.skills) AS skill
        WHERE jos.job_opening_id = NEW.id;
        
        -- Accept 1.0 (decimal) or 100 (percentage)
        IF v_total_weight != 1.0 AND v_total_weight != 100 THEN
            RAISE EXCEPTION 'Total skill weights for confirmed/published job opening must equal 100%% (current sum: %)', v_total_weight;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."validate_job_skills_weight"() OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."applications" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "candidate_id" "uuid" NOT NULL,
    "job_opening_id" "uuid" NOT NULL,
    "candidate_cv" "text",
    "fuzzy_score" numeric,
    "match_score" numeric,
    "match_reason" "text",
    "strengths" "text"[] DEFAULT '{}'::"text"[],
    "skill_gaps" "text"[] DEFAULT '{}'::"text"[],
    "screening_status" "text" DEFAULT 'pending'::"text",
    "stage" "text" DEFAULT 'screening'::"text",
    "stage_status" "text" DEFAULT 'pending'::"text",
    "stage_notes" "text",
    "priority" integer DEFAULT 0,
    "reviewed_by" "uuid",
    "reviewed_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "is_deleted" boolean DEFAULT false,
    "screening_questions" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    CONSTRAINT "applications_fuzzy_score_check" CHECK ((("fuzzy_score" >= (0)::numeric) AND ("fuzzy_score" <= (100)::numeric))),
    CONSTRAINT "applications_match_score_check" CHECK ((("match_score" >= (0)::numeric) AND ("match_score" <= (100)::numeric))),
    CONSTRAINT "applications_screening_status_check" CHECK (("screening_status" = ANY (ARRAY['pending'::"text", 'accepted'::"text", 'rejected'::"text", 'shortlisted'::"text"]))),
    CONSTRAINT "applications_stage_status_check" CHECK (("stage_status" = ANY (ARRAY['pending'::"text", 'in_progress'::"text", 'passed'::"text", 'failed'::"text", 'on_hold'::"text"])))
);


ALTER TABLE "public"."applications" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."active_applications" AS
 SELECT "id",
    "candidate_id",
    "job_opening_id",
    "candidate_cv",
    "fuzzy_score",
    "match_score",
    "match_reason",
    "strengths",
    "skill_gaps",
    "screening_status",
    "stage",
    "stage_status",
    "stage_notes",
    "priority",
    "reviewed_by",
    "reviewed_at",
    "created_at",
    "updated_at",
    "is_deleted"
   FROM "public"."applications"
  WHERE ("is_deleted" = false);


ALTER VIEW "public"."active_applications" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."candidates" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "full_name" "text" NOT NULL,
    "email" "text" NOT NULL,
    "phone" "text",
    "skills" "text"[] DEFAULT '{}'::"text"[],
    "experience_years" integer DEFAULT 0,
    "current_company" "text",
    "resume_url" "text",
    "parsed_resume_json" "jsonb",
    "source" "text",
    "uploaded_by" "uuid" DEFAULT "auth"."uid"(),
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "is_deleted" boolean DEFAULT false,
    "education" "text",
    "working_or_not" boolean DEFAULT true,
    "academic_details" "text",
    "achievements" "text",
    "job_id" "uuid",
    "organization_id" "text",
    CONSTRAINT "candidates_source_check" CHECK (("source" = ANY (ARRAY['csv'::"text", 'pdf'::"text", 'docx'::"text", 'manual'::"text"])))
);


ALTER TABLE "public"."candidates" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."active_candidates" AS
 SELECT "id",
    "full_name",
    "email",
    "phone",
    "skills",
    "experience_years",
    "current_company",
    "resume_url",
    "parsed_resume_json",
    "source",
    "uploaded_by",
    "created_at",
    "updated_at",
    "is_deleted"
   FROM "public"."candidates"
  WHERE ("is_deleted" = false);


ALTER VIEW "public"."active_candidates" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."clients" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "created_by" "uuid" DEFAULT "auth"."uid"(),
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "is_deleted" boolean DEFAULT false,
    "organization_id" "text"
);


ALTER TABLE "public"."clients" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."active_clients" AS
 SELECT "id",
    "name",
    "created_by",
    "created_at",
    "updated_at",
    "is_deleted"
   FROM "public"."clients"
  WHERE ("is_deleted" = false);


ALTER VIEW "public"."active_clients" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."job_openings" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "requirement_id" "uuid" NOT NULL,
    "post_index" integer DEFAULT 1,
    "title" "text",
    "description" "text",
    "responsibilities" "text"[] DEFAULT '{}'::"text"[],
    "qualifications" "text"[] DEFAULT '{}'::"text"[],
    "keywords" "text"[] DEFAULT '{}'::"text"[],
    "salary_range" "text",
    "status" "text" DEFAULT 'draft'::"text",
    "processing_status" "text" DEFAULT 'idle'::"text",
    "error_message" "text",
    "ai_generated" boolean DEFAULT true,
    "approved_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "published_at" timestamp with time zone,
    "is_deleted" boolean DEFAULT false,
    "custom_stages" "text"[] DEFAULT ARRAY['technical'::"text", 'hr'::"text", 'final'::"text"],
    "category" "text",
    "sub_category" "text",
    "candidate_view_settings" "jsonb" DEFAULT '{}'::"jsonb",
    "stage_notifications" "jsonb" DEFAULT '{}'::"jsonb",
    "organization_id" "text",
    CONSTRAINT "job_openings_category_check" CHECK (("category" = ANY (ARRAY['technical'::"text", 'non-technical'::"text"]))),
    CONSTRAINT "job_openings_processing_status_check" CHECK (("processing_status" = ANY (ARRAY['idle'::"text", 'generating'::"text", 'skill_approval'::"text", 'matching'::"text", 'questions_ready'::"text", 'ready'::"text", 'error'::"text"]))),
    CONSTRAINT "job_openings_status_check" CHECK (("status" = ANY (ARRAY['draft'::"text", 'confirmed'::"text", 'published'::"text", 'closed'::"text"])))
);


ALTER TABLE "public"."job_openings" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."active_job_openings" AS
 SELECT "id",
    "requirement_id",
    "post_index",
    "title",
    "description",
    "responsibilities",
    "qualifications",
    "keywords",
    "salary_range",
    "status",
    "processing_status",
    "error_message",
    "ai_generated",
    "approved_by",
    "created_at",
    "updated_at",
    "published_at",
    "is_deleted",
    "custom_stages",
    "category",
    "sub_category",
    "candidate_view_settings",
    "stage_notifications"
   FROM "public"."job_openings"
  WHERE ("is_deleted" = false);


ALTER VIEW "public"."active_job_openings" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."requirements" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "client_id" "uuid" NOT NULL,
    "title" "text" NOT NULL,
    "description" "text",
    "skills" "text"[] DEFAULT '{}'::"text"[],
    "experience_min" integer DEFAULT 0,
    "experience_max" integer DEFAULT 30,
    "budget_min" numeric DEFAULT 0,
    "budget_max" numeric DEFAULT 1000,
    "seniority" "text",
    "notes" "text",
    "num_posts_requested" integer DEFAULT 1,
    "status" "text" DEFAULT 'draft'::"text",
    "created_by" "uuid" DEFAULT "auth"."uid"(),
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "is_deleted" boolean DEFAULT false,
    "organization_id" "text",
    CONSTRAINT "requirements_num_posts_requested_check" CHECK ((("num_posts_requested" >= 1) AND ("num_posts_requested" <= 5))),
    CONSTRAINT "requirements_seniority_check" CHECK (("seniority" = ANY (ARRAY['junior'::"text", 'mid'::"text", 'senior'::"text", 'lead'::"text", 'any'::"text"]))),
    CONSTRAINT "requirements_status_check" CHECK (("status" = ANY (ARRAY['draft'::"text", 'generating'::"text", 'ready'::"text", 'archived'::"text"])))
);


ALTER TABLE "public"."requirements" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."active_requirements" AS
 SELECT "id",
    "client_id",
    "title",
    "description",
    "skills",
    "experience_min",
    "experience_max",
    "budget_min",
    "budget_max",
    "seniority",
    "notes",
    "num_posts_requested",
    "status",
    "created_by",
    "created_at",
    "updated_at",
    "is_deleted"
   FROM "public"."requirements"
  WHERE ("is_deleted" = false);


ALTER VIEW "public"."active_requirements" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."activity_log" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "actor_id" "uuid" DEFAULT "auth"."uid"(),
    "actor_name" "text",
    "action" "text" NOT NULL,
    "entity_type" "text" NOT NULL,
    "entity_id" "uuid",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "organization_id" "text"
);


ALTER TABLE "public"."activity_log" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."approval_logs" (
    "id" "text" DEFAULT ("gen_random_uuid"())::"text" NOT NULL,
    "pipeline_id" "text" NOT NULL,
    "stage_id" "text",
    "actor_id" "text",
    "actor_name" "text",
    "action" "text" NOT NULL,
    "notes" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."approval_logs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."approval_pipeline_access" (
    "id" "text" DEFAULT ("gen_random_uuid"())::"text" NOT NULL,
    "pipeline_id" "text" NOT NULL,
    "role_id" "text",
    "member_id" "text",
    "access_level" "text" DEFAULT 'view'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."approval_pipeline_access" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."approval_pipelines" (
    "id" "text" DEFAULT ("gen_random_uuid"())::"text" NOT NULL,
    "organization_id" "text" NOT NULL,
    "name" "text" NOT NULL,
    "description" "text",
    "is_template" boolean DEFAULT false,
    "entity_type" "text" DEFAULT 'custom'::"text" NOT NULL,
    "entity_id" "text",
    "custom_content" "jsonb",
    "created_by" "text",
    "current_stage_index" integer DEFAULT 0,
    "status" "text" DEFAULT 'draft'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."approval_pipelines" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."approval_rejection_checklists" (
    "id" "text" DEFAULT ("gen_random_uuid"())::"text" NOT NULL,
    "pipeline_id" "text" NOT NULL,
    "stage_id" "text" NOT NULL,
    "rejected_by" "text",
    "reasons" "jsonb" DEFAULT '[]'::"jsonb",
    "highlighted_fields" "jsonb" DEFAULT '[]'::"jsonb",
    "feedback_notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."approval_rejection_checklists" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."approval_stage_approvers" (
    "id" "text" DEFAULT ("gen_random_uuid"())::"text" NOT NULL,
    "stage_id" "text" NOT NULL,
    "role_id" "text",
    "member_id" "text",
    "has_approved" boolean DEFAULT false,
    "approved_at" timestamp with time zone,
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."approval_stage_approvers" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."approval_stages" (
    "id" "text" DEFAULT ("gen_random_uuid"())::"text" NOT NULL,
    "pipeline_id" "text" NOT NULL,
    "stage_index" integer DEFAULT 0 NOT NULL,
    "stage_name" "text" NOT NULL,
    "require_all_approvers" boolean DEFAULT false,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."approval_stages" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."audit_logs" (
    "id" character varying(36) DEFAULT "gen_random_uuid"() NOT NULL,
    "organization_id" character varying(36),
    "actor_id" character varying(36),
    "actor_name" character varying(255) NOT NULL,
    "action_description" character varying(255) NOT NULL,
    "target_name" character varying(255) NOT NULL,
    "action_type" character varying(50) NOT NULL,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "actor_email" "text",
    "target_entity_type" "text",
    "target_entity_id" "text",
    "old_state" "jsonb",
    "new_state" "jsonb",
    "correlation_id" "text"
);


ALTER TABLE "public"."audit_logs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."branches" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "organization_id" character varying(100) NOT NULL,
    "name" character varying(150) NOT NULL,
    "code" character varying(50) DEFAULT 'MAIN'::character varying,
    "location" character varying(200) DEFAULT 'HQ'::character varying,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."branches" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."candidate_queries" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "job_id" "uuid" NOT NULL,
    "candidate_email" "text" NOT NULL,
    "query_text" "text" NOT NULL,
    "ai_response" "text",
    "is_resolved" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "source" "text" DEFAULT 'apply_form'::"text",
    "sender" "text" DEFAULT 'candidate'::"text",
    "is_ended" boolean DEFAULT false,
    CONSTRAINT "candidate_queries_sender_check" CHECK (("sender" = ANY (ARRAY['candidate'::"text", 'recruiter'::"text", 'ai'::"text"]))),
    CONSTRAINT "candidate_queries_source_check" CHECK (("source" = ANY (ARRAY['apply_form'::"text", 'tracking_portal'::"text"])))
);


ALTER TABLE "public"."candidate_queries" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."job_candidates" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "job_opening_id" "uuid" NOT NULL,
    "candidate_id" "uuid" NOT NULL,
    "application_id" "uuid",
    "fuzzy_score" numeric NOT NULL,
    "rank_order" integer NOT NULL,
    "strengths" "text"[] DEFAULT '{}'::"text"[],
    "skill_gaps" "text"[] DEFAULT '{}'::"text"[],
    "ai_reasoning" "text",
    "status" "text" DEFAULT 'pending'::"text",
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "parsed_resume" "jsonb",
    CONSTRAINT "job_candidates_fuzzy_score_check" CHECK ((("fuzzy_score" >= (0)::numeric) AND ("fuzzy_score" <= (100)::numeric))),
    CONSTRAINT "job_candidates_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'accepted'::"text", 'rejected'::"text"])))
);


ALTER TABLE "public"."job_candidates" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."candidate_rankings_view" AS
 SELECT "jc"."id" AS "job_candidate_id",
    "jc"."rank_order" AS "candidate_rank",
    "jc"."fuzzy_score",
    "c"."id" AS "candidate_id",
    "c"."full_name" AS "candidate_name",
    "c"."email" AS "candidate_email",
    "c"."phone" AS "candidate_phone",
    "c"."experience_years",
    "c"."current_company",
    "c"."skills" AS "candidate_skills",
    "j"."id" AS "job_opening_id",
    "j"."title" AS "job_title",
    "j"."status" AS "job_status",
    "jc"."strengths",
    "jc"."skill_gaps",
    "jc"."ai_reasoning",
    "jc"."status" AS "candidate_job_status"
   FROM (("public"."job_candidates" "jc"
     JOIN "public"."candidates" "c" ON (("jc"."candidate_id" = "c"."id")))
     JOIN "public"."job_openings" "j" ON (("jc"."job_opening_id" = "j"."id")))
  WHERE (("c"."is_deleted" = false) AND ("j"."is_deleted" = false));


ALTER VIEW "public"."candidate_rankings_view" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."interview_assignments" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "job_candidate_id" "uuid",
    "interviewer_id" character varying(36),
    "round_name" character varying(150) DEFAULT 'Technical Round'::character varying NOT NULL,
    "scheduled_at" timestamp with time zone,
    "status" character varying(50) DEFAULT 'scheduled'::character varying,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."interview_assignments" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."interview_feedback" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "assignment_id" "uuid",
    "interviewer_id" character varying(36),
    "recommendation" character varying(50) NOT NULL,
    "ratings" "jsonb" DEFAULT '{}'::"jsonb",
    "notes" "text",
    "submitted_at" timestamp with time zone DEFAULT "now"(),
    "locked_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."interview_feedback" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."interview_stages" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "application_id" "uuid" NOT NULL,
    "job_candidate_id" "uuid",
    "stage_name" "text" NOT NULL,
    "stage_order" integer DEFAULT 1,
    "status" "text" DEFAULT 'scheduled'::"text",
    "outcome" "text" DEFAULT 'pending'::"text",
    "notes" "text",
    "scheduled_at" timestamp with time zone,
    "completed_at" timestamp with time zone,
    "updated_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    CONSTRAINT "interview_stages_outcome_check" CHECK (("outcome" = ANY (ARRAY['pending'::"text", 'passed'::"text", 'failed'::"text", 'on_hold'::"text"]))),
    CONSTRAINT "interview_stages_status_check" CHECK (("status" = ANY (ARRAY['scheduled'::"text", 'completed'::"text", 'cancelled'::"text"])))
);


ALTER TABLE "public"."interview_stages" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."job_opening_skills" (
    "job_opening_id" "uuid" NOT NULL,
    "skills" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL
);


ALTER TABLE "public"."job_opening_skills" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."linkedin_accounts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "linkedin_member_id" "text" NOT NULL,
    "linkedin_access_token" "text" NOT NULL,
    "linkedin_refresh_token" "text",
    "company_page_id" "text",
    "expires_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."linkedin_accounts" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."member_manager_assignments" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "member_id" character varying(36) NOT NULL,
    "role_id" character varying(36) NOT NULL,
    "manager_member_id" character varying(36),
    "branch_name" character varying(100) DEFAULT 'Main Branch'::character varying,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."member_manager_assignments" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."member_roles" (
    "member_id" character varying(36) NOT NULL,
    "role_id" character varying(36) NOT NULL
);


ALTER TABLE "public"."member_roles" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."members" (
    "id" character varying(36) DEFAULT "gen_random_uuid"() NOT NULL,
    "organization_id" character varying(36),
    "name" character varying(255) NOT NULL,
    "email" character varying(255) NOT NULL,
    "password_hash" character varying(255) NOT NULL,
    "avatar_initials" character varying(4) NOT NULL,
    "must_change_password" boolean DEFAULT true,
    "status" character varying(50) DEFAULT 'active'::character varying,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "terms_accepted" boolean DEFAULT false,
    "terms_accepted_at" timestamp with time zone,
    "invitation_sent_at" timestamp with time zone,
    "is_primary_admin" boolean DEFAULT false,
    "manager_member_id" character varying(36)
);


ALTER TABLE "public"."members" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."notifications" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "recruiter_id" "uuid" NOT NULL,
    "title" "text" NOT NULL,
    "message" "text" NOT NULL,
    "type" "text" NOT NULL,
    "is_read" boolean DEFAULT false NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    CONSTRAINT "notifications_type_check" CHECK (("type" = ANY (ARRAY['job_generation'::"text", 'candidate_matching'::"text", 'upload'::"text", 'error'::"text", 'screening_questions'::"text"])))
);


ALTER TABLE "public"."notifications" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."organizations" (
    "id" character varying(36) DEFAULT "gen_random_uuid"() NOT NULL,
    "name" character varying(255) NOT NULL,
    "operating_mode" character varying(50) DEFAULT 'internal'::character varying NOT NULL,
    "default_landing_portal" character varying(50) DEFAULT 'admin'::character varying NOT NULL,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "max_members_limit" integer DEFAULT 10,
    "max_roles_limit" integer DEFAULT 5,
    "can_manage_pipelines" boolean DEFAULT true,
    "can_view_audit_logs" boolean DEFAULT true
);


ALTER TABLE "public"."organizations" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."pending_approvals" (
    "id" character varying(36) DEFAULT "gen_random_uuid"() NOT NULL,
    "pipeline_id" character varying(36),
    "item_title" character varying(255) NOT NULL,
    "requestor_id" character varying(36),
    "current_stage_step" integer NOT NULL,
    "current_stage_title" character varying(255) NOT NULL,
    "required_role_id" character varying(36),
    "status" character varying(50) DEFAULT 'Pending Review'::character varying,
    "submitted_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."pending_approvals" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."pipeline_stages" (
    "id" character varying(36) DEFAULT "gen_random_uuid"() NOT NULL,
    "pipeline_id" character varying(36),
    "step_number" integer NOT NULL,
    "stage_title" character varying(255) NOT NULL,
    "required_role_id" character varying(36),
    "sla_hours" integer DEFAULT 24,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."pipeline_stages" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."profiles" (
    "id" "uuid" NOT NULL,
    "email" "text" NOT NULL,
    "full_name" "text",
    "avatar_url" "text",
    "role" "text" DEFAULT 'recruiter'::"text",
    "is_active" boolean DEFAULT true,
    "is_onboarded" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    CONSTRAINT "profiles_role_check" CHECK (("role" = ANY (ARRAY['admin'::"text", 'recruiter'::"text", 'manager'::"text", 'client'::"text"])))
);


ALTER TABLE "public"."profiles" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."recruiter_dashboard_view" AS
 SELECT ( SELECT "count"(*) AS "count"
           FROM "public"."job_openings"
          WHERE (("job_openings"."status" = 'published'::"text") AND ("job_openings"."is_deleted" = false))) AS "open_jobs",
    ( SELECT "count"(*) AS "count"
           FROM "public"."requirements"
          WHERE (("requirements"."status" = 'active'::"text") AND ("requirements"."is_deleted" = false))) AS "active_requirements",
    ( SELECT "count"(*) AS "count"
           FROM "public"."candidates"
          WHERE ("candidates"."is_deleted" = false)) AS "candidates_uploaded",
    ( SELECT "count"(*) AS "count"
           FROM "public"."applications"
          WHERE (("applications"."screening_status" = 'pending'::"text") AND ("applications"."is_deleted" = false))) AS "pending_reviews",
    ( SELECT "count"(*) AS "count"
           FROM "public"."applications"
          WHERE (("applications"."stage_status" = 'in_progress'::"text") AND ("applications"."is_deleted" = false))) AS "stages_in_progress";


ALTER VIEW "public"."recruiter_dashboard_view" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."role_permissions" (
    "role_id" character varying(36) NOT NULL,
    "administrator" boolean DEFAULT false,
    "audit_logs" boolean DEFAULT false,
    "manage_server" boolean DEFAULT false,
    "access_recruitment" boolean DEFAULT true,
    "recruiter_dashboard" boolean DEFAULT true,
    "recruiter_mandates" boolean DEFAULT true,
    "recruiter_jobs" boolean DEFAULT true,
    "recruiter_sourcing" boolean DEFAULT true,
    "recruiter_reports" boolean DEFAULT true,
    "recruiter_qna" boolean DEFAULT true,
    "recruiter_resumes" boolean DEFAULT true,
    "recruiter_stage_move" boolean DEFAULT true,
    "access_client" boolean DEFAULT false,
    "client_contracts" boolean DEFAULT false,
    "client_mandates" boolean DEFAULT false,
    "client_shortlists" boolean DEFAULT false,
    "access_employee" boolean DEFAULT false,
    "employee_directory" boolean DEFAULT false,
    "employee_org_chart" boolean DEFAULT false,
    "manage_jobs" boolean DEFAULT true,
    "view_resumes" boolean DEFAULT true,
    "edit_status" boolean DEFAULT true,
    "schedule_interviews" boolean DEFAULT true,
    "recruiter_stages" boolean DEFAULT true,
    "recruiter_pipelines" boolean DEFAULT true,
    "recruiter_notifications" boolean DEFAULT true,
    "team_monitoring" boolean DEFAULT false,
    "interviewer_workspace" boolean DEFAULT false
);


ALTER TABLE "public"."role_permissions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."roles" (
    "id" character varying(36) DEFAULT "gen_random_uuid"() NOT NULL,
    "organization_id" character varying(36),
    "parent_id" character varying(36),
    "name" character varying(255) NOT NULL,
    "level" character varying(50) DEFAULT 'position'::character varying NOT NULL,
    "color_hex" character varying(7) DEFAULT '#ff6e30'::character varying NOT NULL,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "branch_id" "uuid",
    "scope_type" character varying(50) DEFAULT 'organization'::character varying,
    "branch_name" character varying(100) DEFAULT 'Main Branch'::character varying,
    "is_managerial" boolean DEFAULT false,
    "supervised_by_role_id" character varying(36)
);


ALTER TABLE "public"."roles" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."rolling_updates" (
    "id" character varying(36) DEFAULT "gen_random_uuid"() NOT NULL,
    "version_tag" character varying(50) NOT NULL,
    "title" character varying(255) NOT NULL,
    "description" "text" NOT NULL,
    "category" character varying(100) DEFAULT 'Feature Release'::character varying NOT NULL,
    "priority" character varying(50) DEFAULT 'Normal'::character varying NOT NULL,
    "published_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."rolling_updates" OWNER TO "postgres";


ALTER TABLE ONLY "public"."activity_log"
    ADD CONSTRAINT "activity_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."applications"
    ADD CONSTRAINT "applications_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."approval_logs"
    ADD CONSTRAINT "approval_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."approval_pipeline_access"
    ADD CONSTRAINT "approval_pipeline_access_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."approval_pipelines"
    ADD CONSTRAINT "approval_pipelines_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."approval_rejection_checklists"
    ADD CONSTRAINT "approval_rejection_checklists_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."approval_stage_approvers"
    ADD CONSTRAINT "approval_stage_approvers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."approval_stages"
    ADD CONSTRAINT "approval_stages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."audit_logs"
    ADD CONSTRAINT "audit_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."branches"
    ADD CONSTRAINT "branches_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."candidate_queries"
    ADD CONSTRAINT "candidate_queries_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."candidates"
    ADD CONSTRAINT "candidates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."clients"
    ADD CONSTRAINT "clients_name_created_by_key" UNIQUE ("name", "created_by");



ALTER TABLE ONLY "public"."clients"
    ADD CONSTRAINT "clients_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."interview_assignments"
    ADD CONSTRAINT "interview_assignments_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."interview_feedback"
    ADD CONSTRAINT "interview_feedback_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."interview_stages"
    ADD CONSTRAINT "interview_stages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."job_candidates"
    ADD CONSTRAINT "job_candidates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."job_opening_skills"
    ADD CONSTRAINT "job_opening_skills_pkey" PRIMARY KEY ("job_opening_id");



ALTER TABLE ONLY "public"."job_openings"
    ADD CONSTRAINT "job_openings_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."linkedin_accounts"
    ADD CONSTRAINT "linkedin_accounts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."member_manager_assignments"
    ADD CONSTRAINT "member_manager_assignments_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."member_roles"
    ADD CONSTRAINT "member_roles_pkey" PRIMARY KEY ("member_id", "role_id");



ALTER TABLE ONLY "public"."members"
    ADD CONSTRAINT "members_email_key" UNIQUE ("email");



ALTER TABLE ONLY "public"."members"
    ADD CONSTRAINT "members_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notifications"
    ADD CONSTRAINT "notifications_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."organizations"
    ADD CONSTRAINT "organizations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pending_approvals"
    ADD CONSTRAINT "pending_approvals_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pipeline_stages"
    ADD CONSTRAINT "pipeline_stages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_email_key" UNIQUE ("email");



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."requirements"
    ADD CONSTRAINT "requirements_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."role_permissions"
    ADD CONSTRAINT "role_permissions_pkey" PRIMARY KEY ("role_id");



ALTER TABLE ONLY "public"."roles"
    ADD CONSTRAINT "roles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."rolling_updates"
    ADD CONSTRAINT "rolling_updates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."member_manager_assignments"
    ADD CONSTRAINT "unique_member_role_assignment" UNIQUE ("member_id", "role_id");



ALTER TABLE ONLY "public"."applications"
    ADD CONSTRAINT "uq_candidate_job_application" UNIQUE ("candidate_id", "job_opening_id");



ALTER TABLE ONLY "public"."job_candidates"
    ADD CONSTRAINT "uq_job_candidates_opening_candidate" UNIQUE ("job_opening_id", "candidate_id");



ALTER TABLE ONLY "public"."linkedin_accounts"
    ADD CONSTRAINT "uq_linkedin_user" UNIQUE ("user_id");



CREATE INDEX "idx_activity_log_action" ON "public"."activity_log" USING "btree" ("action");



CREATE INDEX "idx_activity_log_actor_id" ON "public"."activity_log" USING "btree" ("actor_id");



CREATE INDEX "idx_activity_log_created" ON "public"."activity_log" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_activity_log_created_at" ON "public"."activity_log" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_activity_log_entity" ON "public"."activity_log" USING "btree" ("entity_type", "entity_id");



CREATE INDEX "idx_activity_log_org_id" ON "public"."activity_log" USING "btree" ("organization_id");



CREATE INDEX "idx_applications_candidate" ON "public"."applications" USING "btree" ("candidate_id");



CREATE INDEX "idx_applications_is_deleted" ON "public"."applications" USING "btree" ("is_deleted");



CREATE INDEX "idx_applications_job" ON "public"."applications" USING "btree" ("job_opening_id");



CREATE INDEX "idx_applications_screening_status" ON "public"."applications" USING "btree" ("screening_status");



CREATE INDEX "idx_applications_stage" ON "public"."applications" USING "btree" ("stage");



CREATE INDEX "idx_approval_access_pipeline" ON "public"."approval_pipeline_access" USING "btree" ("pipeline_id");



CREATE INDEX "idx_approval_approvers_member" ON "public"."approval_stage_approvers" USING "btree" ("member_id");



CREATE INDEX "idx_approval_approvers_stage" ON "public"."approval_stage_approvers" USING "btree" ("stage_id");



CREATE INDEX "idx_approval_pipelines_org" ON "public"."approval_pipelines" USING "btree" ("organization_id");



CREATE INDEX "idx_approval_pipelines_status" ON "public"."approval_pipelines" USING "btree" ("status");



CREATE INDEX "idx_approval_stages_pipeline" ON "public"."approval_stages" USING "btree" ("pipeline_id");



CREATE INDEX "idx_branches_org_id" ON "public"."branches" USING "btree" ("organization_id");



CREATE INDEX "idx_candidate_queries_convo" ON "public"."candidate_queries" USING "btree" ("candidate_email", "job_id", "is_ended");



CREATE INDEX "idx_candidates_email" ON "public"."candidates" USING "btree" ("email");



CREATE INDEX "idx_candidates_is_deleted" ON "public"."candidates" USING "btree" ("is_deleted");



CREATE INDEX "idx_candidates_organization_id" ON "public"."candidates" USING "btree" ("organization_id") WHERE ("is_deleted" = false);



CREATE INDEX "idx_candidates_skills" ON "public"."candidates" USING "gin" ("skills");



CREATE INDEX "idx_clients_is_deleted" ON "public"."clients" USING "btree" ("is_deleted");



CREATE INDEX "idx_interview_stages_application" ON "public"."interview_stages" USING "btree" ("application_id");



CREATE INDEX "idx_job_candidates_fuzzy_score" ON "public"."job_candidates" USING "btree" ("fuzzy_score" DESC);



CREATE INDEX "idx_job_candidates_opening" ON "public"."job_candidates" USING "btree" ("job_opening_id");



CREATE INDEX "idx_job_candidates_rank" ON "public"."job_candidates" USING "btree" ("rank_order");



CREATE INDEX "idx_job_openings_is_deleted" ON "public"."job_openings" USING "btree" ("is_deleted");



CREATE INDEX "idx_job_openings_req" ON "public"."job_openings" USING "btree" ("requirement_id");



CREATE INDEX "idx_job_openings_status" ON "public"."job_openings" USING "btree" ("status");



CREATE INDEX "idx_members_email" ON "public"."members" USING "btree" ("email");



CREATE INDEX "idx_members_is_primary_admin" ON "public"."members" USING "btree" ("is_primary_admin");



CREATE INDEX "idx_members_manager_id" ON "public"."members" USING "btree" ("manager_member_id");



CREATE INDEX "idx_members_org_id" ON "public"."members" USING "btree" ("organization_id");



CREATE INDEX "idx_mma_manager_member_id" ON "public"."member_manager_assignments" USING "btree" ("manager_member_id");



CREATE INDEX "idx_mma_member_id" ON "public"."member_manager_assignments" USING "btree" ("member_id");



CREATE INDEX "idx_mma_role_id" ON "public"."member_manager_assignments" USING "btree" ("role_id");



CREATE INDEX "idx_notifications_recruiter_created" ON "public"."notifications" USING "btree" ("recruiter_id", "created_at" DESC);



CREATE INDEX "idx_profiles_email" ON "public"."profiles" USING "btree" ("email");



CREATE INDEX "idx_requirements_client" ON "public"."requirements" USING "btree" ("client_id");



CREATE INDEX "idx_requirements_is_deleted" ON "public"."requirements" USING "btree" ("is_deleted");



CREATE INDEX "idx_roles_branch_id" ON "public"."roles" USING "btree" ("branch_id");



CREATE INDEX "idx_roles_branch_name" ON "public"."roles" USING "btree" ("branch_name");



CREATE INDEX "idx_roles_is_managerial" ON "public"."roles" USING "btree" ("is_managerial");



CREATE INDEX "idx_roles_scope_type" ON "public"."roles" USING "btree" ("scope_type");



CREATE INDEX "idx_roles_supervised_by_role_id" ON "public"."roles" USING "btree" ("supervised_by_role_id");



CREATE UNIQUE INDEX "uq_candidates_email_job_id" ON "public"."candidates" USING "btree" ("email", "job_id") WHERE ("job_id" IS NOT NULL);



CREATE UNIQUE INDEX "uq_candidates_email_no_job" ON "public"."candidates" USING "btree" ("email") WHERE ("job_id" IS NULL);



CREATE OR REPLACE TRIGGER "audit_candidates_trigger" AFTER INSERT OR DELETE OR UPDATE ON "public"."candidates" FOR EACH ROW EXECUTE FUNCTION "public"."log_record_changes"();



CREATE OR REPLACE TRIGGER "audit_clients_trigger" AFTER INSERT OR DELETE OR UPDATE ON "public"."clients" FOR EACH ROW EXECUTE FUNCTION "public"."log_record_changes"();



CREATE OR REPLACE TRIGGER "audit_job_openings_trigger" AFTER INSERT OR DELETE OR UPDATE ON "public"."job_openings" FOR EACH ROW EXECUTE FUNCTION "public"."log_record_changes"();



CREATE OR REPLACE TRIGGER "audit_requirements_trigger" AFTER INSERT OR DELETE OR UPDATE ON "public"."requirements" FOR EACH ROW EXECUTE FUNCTION "public"."log_record_changes"();



CREATE OR REPLACE TRIGGER "set_timestamp_applications" BEFORE UPDATE ON "public"."applications" FOR EACH ROW EXECUTE FUNCTION "public"."handle_update_timestamp"();



CREATE OR REPLACE TRIGGER "set_timestamp_candidates" BEFORE UPDATE ON "public"."candidates" FOR EACH ROW EXECUTE FUNCTION "public"."handle_update_timestamp"();



CREATE OR REPLACE TRIGGER "set_timestamp_clients" BEFORE UPDATE ON "public"."clients" FOR EACH ROW EXECUTE FUNCTION "public"."handle_update_timestamp"();



CREATE OR REPLACE TRIGGER "set_timestamp_interview_stages" BEFORE UPDATE ON "public"."interview_stages" FOR EACH ROW EXECUTE FUNCTION "public"."handle_update_timestamp"();



CREATE OR REPLACE TRIGGER "set_timestamp_job_openings" BEFORE UPDATE ON "public"."job_openings" FOR EACH ROW EXECUTE FUNCTION "public"."handle_update_timestamp"();



CREATE OR REPLACE TRIGGER "set_timestamp_profiles" BEFORE UPDATE ON "public"."profiles" FOR EACH ROW EXECUTE FUNCTION "public"."handle_update_timestamp"();



CREATE OR REPLACE TRIGGER "set_timestamp_requirements" BEFORE UPDATE ON "public"."requirements" FOR EACH ROW EXECUTE FUNCTION "public"."handle_update_timestamp"();



CREATE OR REPLACE TRIGGER "trigger_candidate_deduplication" BEFORE INSERT ON "public"."candidates" FOR EACH ROW EXECUTE FUNCTION "public"."handle_candidate_deduplication"();



CREATE OR REPLACE TRIGGER "trigger_interview_stage_failure_check" BEFORE INSERT OR UPDATE ON "public"."interview_stages" FOR EACH ROW EXECUTE FUNCTION "public"."check_stage_notes_on_failure"();



CREATE OR REPLACE TRIGGER "trigger_validate_job_skills_weight" BEFORE UPDATE ON "public"."job_openings" FOR EACH ROW EXECUTE FUNCTION "public"."validate_job_skills_weight"();



ALTER TABLE ONLY "public"."activity_log"
    ADD CONSTRAINT "activity_log_actor_id_fkey" FOREIGN KEY ("actor_id") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."applications"
    ADD CONSTRAINT "applications_candidate_id_fkey" FOREIGN KEY ("candidate_id") REFERENCES "public"."candidates"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."applications"
    ADD CONSTRAINT "applications_job_opening_id_fkey" FOREIGN KEY ("job_opening_id") REFERENCES "public"."job_openings"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."applications"
    ADD CONSTRAINT "applications_reviewed_by_fkey" FOREIGN KEY ("reviewed_by") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."approval_logs"
    ADD CONSTRAINT "approval_logs_actor_id_fkey" FOREIGN KEY ("actor_id") REFERENCES "public"."members"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."approval_logs"
    ADD CONSTRAINT "approval_logs_pipeline_id_fkey" FOREIGN KEY ("pipeline_id") REFERENCES "public"."approval_pipelines"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."approval_logs"
    ADD CONSTRAINT "approval_logs_stage_id_fkey" FOREIGN KEY ("stage_id") REFERENCES "public"."approval_stages"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."approval_pipeline_access"
    ADD CONSTRAINT "approval_pipeline_access_member_id_fkey" FOREIGN KEY ("member_id") REFERENCES "public"."members"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."approval_pipeline_access"
    ADD CONSTRAINT "approval_pipeline_access_pipeline_id_fkey" FOREIGN KEY ("pipeline_id") REFERENCES "public"."approval_pipelines"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."approval_pipeline_access"
    ADD CONSTRAINT "approval_pipeline_access_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "public"."roles"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."approval_pipelines"
    ADD CONSTRAINT "approval_pipelines_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "public"."members"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."approval_pipelines"
    ADD CONSTRAINT "approval_pipelines_organization_id_fkey" FOREIGN KEY ("organization_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."approval_rejection_checklists"
    ADD CONSTRAINT "approval_rejection_checklists_pipeline_id_fkey" FOREIGN KEY ("pipeline_id") REFERENCES "public"."approval_pipelines"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."approval_rejection_checklists"
    ADD CONSTRAINT "approval_rejection_checklists_rejected_by_fkey" FOREIGN KEY ("rejected_by") REFERENCES "public"."members"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."approval_rejection_checklists"
    ADD CONSTRAINT "approval_rejection_checklists_stage_id_fkey" FOREIGN KEY ("stage_id") REFERENCES "public"."approval_stages"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."approval_stage_approvers"
    ADD CONSTRAINT "approval_stage_approvers_member_id_fkey" FOREIGN KEY ("member_id") REFERENCES "public"."members"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."approval_stage_approvers"
    ADD CONSTRAINT "approval_stage_approvers_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "public"."roles"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."approval_stage_approvers"
    ADD CONSTRAINT "approval_stage_approvers_stage_id_fkey" FOREIGN KEY ("stage_id") REFERENCES "public"."approval_stages"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."approval_stages"
    ADD CONSTRAINT "approval_stages_pipeline_id_fkey" FOREIGN KEY ("pipeline_id") REFERENCES "public"."approval_pipelines"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."audit_logs"
    ADD CONSTRAINT "audit_logs_actor_id_fkey" FOREIGN KEY ("actor_id") REFERENCES "public"."members"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."audit_logs"
    ADD CONSTRAINT "audit_logs_organization_id_fkey" FOREIGN KEY ("organization_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."branches"
    ADD CONSTRAINT "branches_organization_id_fkey" FOREIGN KEY ("organization_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."candidate_queries"
    ADD CONSTRAINT "candidate_queries_job_id_fkey" FOREIGN KEY ("job_id") REFERENCES "public"."job_openings"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."candidates"
    ADD CONSTRAINT "candidates_job_id_fkey" FOREIGN KEY ("job_id") REFERENCES "public"."job_openings"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."candidates"
    ADD CONSTRAINT "candidates_uploaded_by_fkey" FOREIGN KEY ("uploaded_by") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."clients"
    ADD CONSTRAINT "clients_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."interview_assignments"
    ADD CONSTRAINT "interview_assignments_interviewer_id_fkey" FOREIGN KEY ("interviewer_id") REFERENCES "public"."members"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."interview_assignments"
    ADD CONSTRAINT "interview_assignments_job_candidate_id_fkey" FOREIGN KEY ("job_candidate_id") REFERENCES "public"."job_candidates"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."interview_feedback"
    ADD CONSTRAINT "interview_feedback_assignment_id_fkey" FOREIGN KEY ("assignment_id") REFERENCES "public"."interview_assignments"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."interview_feedback"
    ADD CONSTRAINT "interview_feedback_interviewer_id_fkey" FOREIGN KEY ("interviewer_id") REFERENCES "public"."members"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."interview_stages"
    ADD CONSTRAINT "interview_stages_application_id_fkey" FOREIGN KEY ("application_id") REFERENCES "public"."applications"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."interview_stages"
    ADD CONSTRAINT "interview_stages_job_candidate_id_fkey" FOREIGN KEY ("job_candidate_id") REFERENCES "public"."job_candidates"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."interview_stages"
    ADD CONSTRAINT "interview_stages_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."job_candidates"
    ADD CONSTRAINT "job_candidates_application_id_fkey" FOREIGN KEY ("application_id") REFERENCES "public"."applications"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."job_candidates"
    ADD CONSTRAINT "job_candidates_candidate_id_fkey" FOREIGN KEY ("candidate_id") REFERENCES "public"."candidates"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."job_candidates"
    ADD CONSTRAINT "job_candidates_job_opening_id_fkey" FOREIGN KEY ("job_opening_id") REFERENCES "public"."job_openings"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."job_opening_skills"
    ADD CONSTRAINT "job_opening_skills_job_opening_id_fkey" FOREIGN KEY ("job_opening_id") REFERENCES "public"."job_openings"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."job_openings"
    ADD CONSTRAINT "job_openings_approved_by_fkey" FOREIGN KEY ("approved_by") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."job_openings"
    ADD CONSTRAINT "job_openings_requirement_id_fkey" FOREIGN KEY ("requirement_id") REFERENCES "public"."requirements"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."linkedin_accounts"
    ADD CONSTRAINT "linkedin_accounts_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."member_manager_assignments"
    ADD CONSTRAINT "member_manager_assignments_manager_member_id_fkey" FOREIGN KEY ("manager_member_id") REFERENCES "public"."members"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."member_manager_assignments"
    ADD CONSTRAINT "member_manager_assignments_member_id_fkey" FOREIGN KEY ("member_id") REFERENCES "public"."members"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."member_manager_assignments"
    ADD CONSTRAINT "member_manager_assignments_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "public"."roles"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."member_roles"
    ADD CONSTRAINT "member_roles_member_id_fkey" FOREIGN KEY ("member_id") REFERENCES "public"."members"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."member_roles"
    ADD CONSTRAINT "member_roles_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "public"."roles"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."members"
    ADD CONSTRAINT "members_manager_member_id_fkey" FOREIGN KEY ("manager_member_id") REFERENCES "public"."members"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."members"
    ADD CONSTRAINT "members_organization_id_fkey" FOREIGN KEY ("organization_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."notifications"
    ADD CONSTRAINT "notifications_recruiter_id_fkey" FOREIGN KEY ("recruiter_id") REFERENCES "public"."profiles"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."pending_approvals"
    ADD CONSTRAINT "pending_approvals_requestor_id_fkey" FOREIGN KEY ("requestor_id") REFERENCES "public"."members"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."pending_approvals"
    ADD CONSTRAINT "pending_approvals_required_role_id_fkey" FOREIGN KEY ("required_role_id") REFERENCES "public"."roles"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."pipeline_stages"
    ADD CONSTRAINT "pipeline_stages_required_role_id_fkey" FOREIGN KEY ("required_role_id") REFERENCES "public"."roles"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_id_fkey" FOREIGN KEY ("id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."requirements"
    ADD CONSTRAINT "requirements_client_id_fkey" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."requirements"
    ADD CONSTRAINT "requirements_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."role_permissions"
    ADD CONSTRAINT "role_permissions_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "public"."roles"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."roles"
    ADD CONSTRAINT "roles_branch_id_fkey" FOREIGN KEY ("branch_id") REFERENCES "public"."branches"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."roles"
    ADD CONSTRAINT "roles_organization_id_fkey" FOREIGN KEY ("organization_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."roles"
    ADD CONSTRAINT "roles_parent_id_fkey" FOREIGN KEY ("parent_id") REFERENCES "public"."roles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."roles"
    ADD CONSTRAINT "roles_supervised_by_role_id_fkey" FOREIGN KEY ("supervised_by_role_id") REFERENCES "public"."roles"("id") ON DELETE SET NULL;



CREATE POLICY "Allow admin full access profiles" ON "public"."profiles" TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "Allow admin to delete clients" ON "public"."clients" FOR DELETE USING ("public"."is_admin"());



CREATE POLICY "Allow admin to delete jobs" ON "public"."job_openings" FOR DELETE USING ("public"."is_admin"());



CREATE POLICY "Allow admin to delete requirements" ON "public"."requirements" FOR DELETE USING ("public"."is_admin"());



CREATE POLICY "Allow anonymous insert of candidates" ON "public"."candidates" FOR INSERT TO "anon" WITH CHECK (true);



CREATE POLICY "Allow anonymous read of candidates" ON "public"."candidates" FOR SELECT TO "anon" USING (true);



CREATE POLICY "Allow anonymous update of candidates" ON "public"."candidates" FOR UPDATE TO "anon" USING (true);



CREATE POLICY "Allow anonymous view active jobs" ON "public"."job_openings" FOR SELECT TO "anon" USING (("is_deleted" = false));



CREATE POLICY "Allow anonymous view candidate queries" ON "public"."candidate_queries" FOR SELECT TO "anon" USING (true);



CREATE POLICY "Allow anonymous view clients" ON "public"."clients" FOR SELECT TO "anon" USING (("is_deleted" = false));



CREATE POLICY "Allow anonymous view requirements" ON "public"."requirements" FOR SELECT TO "anon" USING (("is_deleted" = false));



CREATE POLICY "Allow insert candidate queries" ON "public"."candidate_queries" FOR INSERT WITH CHECK (true);



CREATE POLICY "Allow insert log" ON "public"."activity_log" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Allow insert/update for owner" ON "public"."linkedin_accounts" USING (("auth"."uid"() = "user_id"));



CREATE POLICY "Allow members read access to own org audit logs" ON "public"."audit_logs" FOR SELECT USING ((("organization_id")::"text" IN ( SELECT ("members"."organization_id")::"text" AS "organization_id"
   FROM "public"."members"
  WHERE ((("members"."id")::"text" = ("auth"."uid"())::"text") OR ("lower"(("members"."email")::"text") = "lower"(("auth"."jwt"() ->> 'email'::"text")))))));



CREATE POLICY "Allow modify applications" ON "public"."applications" TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM ("public"."job_openings" "j"
     JOIN "public"."requirements" "r" ON (("j"."requirement_id" = "r"."id")))
  WHERE (("j"."id" = "applications"."job_opening_id") AND ("r"."created_by" = "auth"."uid"())))) OR "public"."is_admin"()));



CREATE POLICY "Allow modify candidates" ON "public"."candidates" TO "authenticated" USING ((("auth"."uid"() = "uploaded_by") OR "public"."is_admin"()));



CREATE POLICY "Allow modify job candidates" ON "public"."job_candidates" TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM ("public"."job_openings" "j"
     JOIN "public"."requirements" "r" ON (("j"."requirement_id" = "r"."id")))
  WHERE (("j"."id" = "job_candidates"."job_opening_id") AND ("r"."created_by" = "auth"."uid"())))) OR "public"."is_admin"()));



CREATE POLICY "Allow modify notifications" ON "public"."notifications" TO "authenticated" USING ((("auth"."uid"() = "recruiter_id") OR "public"."is_admin"()));



CREATE POLICY "Allow modify skills" ON "public"."job_opening_skills" TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM ("public"."job_openings" "j"
     JOIN "public"."requirements" "r" ON (("j"."requirement_id" = "r"."id")))
  WHERE (("j"."id" = "job_opening_skills"."job_opening_id") AND ("r"."created_by" = "auth"."uid"())))) OR "public"."is_admin"()));



CREATE POLICY "Allow modify stages" ON "public"."interview_stages" TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM (("public"."applications" "a"
     JOIN "public"."job_openings" "j" ON (("a"."job_opening_id" = "j"."id")))
     JOIN "public"."requirements" "r" ON (("j"."requirement_id" = "r"."id")))
  WHERE (("a"."id" = "interview_stages"."application_id") AND ("r"."created_by" = "auth"."uid"())))) OR "public"."is_admin"()));



CREATE POLICY "Allow public read of profiles" ON "public"."profiles" FOR SELECT USING ((("auth"."uid"() = "id") OR "public"."is_admin"()));



CREATE POLICY "Allow recruiters to modify clients" ON "public"."clients" FOR INSERT WITH CHECK ((("auth"."uid"() = "created_by") OR "public"."is_admin"()));



CREATE POLICY "Allow recruiters to modify jobs" ON "public"."job_openings" FOR INSERT WITH CHECK (((EXISTS ( SELECT 1
   FROM "public"."requirements" "r"
  WHERE (("r"."id" = "job_openings"."requirement_id") AND ("r"."created_by" = "auth"."uid"())))) OR "public"."is_admin"()));



CREATE POLICY "Allow recruiters to modify requirements" ON "public"."requirements" FOR INSERT WITH CHECK ((("auth"."uid"() = "created_by") OR "public"."is_admin"()));



CREATE POLICY "Allow recruiters to update clients" ON "public"."clients" FOR UPDATE USING ((("auth"."uid"() = "created_by") OR "public"."is_admin"()));



CREATE POLICY "Allow recruiters to update jobs" ON "public"."job_openings" FOR UPDATE USING (((EXISTS ( SELECT 1
   FROM "public"."requirements" "r"
  WHERE (("r"."id" = "job_openings"."requirement_id") AND ("r"."created_by" = "auth"."uid"())))) OR "public"."is_admin"()));



CREATE POLICY "Allow recruiters to update requirements" ON "public"."requirements" FOR UPDATE USING ((("auth"."uid"() = "created_by") OR "public"."is_admin"()));



CREATE POLICY "Allow recruiters to view clients" ON "public"."clients" FOR SELECT TO "authenticated" USING ((("auth"."uid"() = "created_by") OR "public"."is_admin"()));



CREATE POLICY "Allow recruiters to view jobs" ON "public"."job_openings" FOR SELECT TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM "public"."requirements" "r"
  WHERE (("r"."id" = "job_openings"."requirement_id") AND ("r"."created_by" = "auth"."uid"())))) OR "public"."is_admin"()));



CREATE POLICY "Allow recruiters to view requirements" ON "public"."requirements" FOR SELECT TO "authenticated" USING ((("auth"."uid"() = "created_by") OR "public"."is_admin"()));



CREATE POLICY "Allow resolve candidate queries" ON "public"."candidate_queries" FOR UPDATE TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM ("public"."job_openings" "j"
     JOIN "public"."requirements" "r" ON (("j"."requirement_id" = "r"."id")))
  WHERE (("j"."id" = "candidate_queries"."job_id") AND ("r"."created_by" = "auth"."uid"())))));



CREATE POLICY "Allow select for owner" ON "public"."linkedin_accounts" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "Allow self-insert profiles" ON "public"."profiles" FOR INSERT WITH CHECK (("auth"."uid"() = "id"));



CREATE POLICY "Allow self-update profiles" ON "public"."profiles" FOR UPDATE USING (("auth"."uid"() = "id"));



CREATE POLICY "Allow service role full access to audit logs" ON "public"."audit_logs" USING (true) WITH CHECK (true);



CREATE POLICY "Allow view applications" ON "public"."applications" FOR SELECT TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM ("public"."job_openings" "j"
     JOIN "public"."requirements" "r" ON (("j"."requirement_id" = "r"."id")))
  WHERE (("j"."id" = "applications"."job_opening_id") AND ("r"."created_by" = "auth"."uid"())))) OR (EXISTS ( SELECT 1
   FROM "public"."candidates" "c"
  WHERE (("c"."id" = "applications"."candidate_id") AND ("c"."uploaded_by" = "auth"."uid"())))) OR "public"."is_admin"()));



CREATE POLICY "Allow view candidate queries" ON "public"."candidate_queries" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM ("public"."job_openings" "j"
     JOIN "public"."requirements" "r" ON (("j"."requirement_id" = "r"."id")))
  WHERE (("j"."id" = "candidate_queries"."job_id") AND ("r"."created_by" = "auth"."uid"())))));



CREATE POLICY "Allow view candidates" ON "public"."candidates" FOR SELECT TO "authenticated" USING ((("auth"."uid"() = "uploaded_by") OR "public"."is_admin"()));



CREATE POLICY "Allow view job candidates" ON "public"."job_candidates" FOR SELECT TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM ("public"."job_openings" "j"
     JOIN "public"."requirements" "r" ON (("j"."requirement_id" = "r"."id")))
  WHERE (("j"."id" = "job_candidates"."job_opening_id") AND ("r"."created_by" = "auth"."uid"())))) OR "public"."is_admin"()));



CREATE POLICY "Allow view log" ON "public"."activity_log" FOR SELECT TO "authenticated" USING ((("auth"."uid"() = "actor_id") OR "public"."is_admin"()));



CREATE POLICY "Allow view notifications" ON "public"."notifications" FOR SELECT TO "authenticated" USING ((("auth"."uid"() = "recruiter_id") OR "public"."is_admin"()));



CREATE POLICY "Allow view skills" ON "public"."job_opening_skills" FOR SELECT TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM ("public"."job_openings" "j"
     JOIN "public"."requirements" "r" ON (("j"."requirement_id" = "r"."id")))
  WHERE (("j"."id" = "job_opening_skills"."job_opening_id") AND ("r"."created_by" = "auth"."uid"())))) OR "public"."is_admin"()));



CREATE POLICY "Allow view stages" ON "public"."interview_stages" FOR SELECT TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM (("public"."applications" "a"
     JOIN "public"."job_openings" "j" ON (("a"."job_opening_id" = "j"."id")))
     JOIN "public"."requirements" "r" ON (("j"."requirement_id" = "r"."id")))
  WHERE (("a"."id" = "interview_stages"."application_id") AND ("r"."created_by" = "auth"."uid"())))) OR "public"."is_admin"()));



ALTER TABLE "public"."activity_log" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."applications" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."approval_logs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."approval_pipeline_access" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."approval_pipelines" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."approval_rejection_checklists" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."approval_stage_approvers" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."approval_stages" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."audit_logs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."branches" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."candidate_queries" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."candidates" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."clients" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."interview_assignments" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."interview_feedback" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."interview_stages" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."job_candidates" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."job_opening_skills" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."job_openings" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."linkedin_accounts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."member_manager_assignments" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."member_roles" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."members" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."notifications" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."organizations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pending_approvals" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pipeline_stages" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."profiles" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."requirements" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."role_permissions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."roles" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."rolling_updates" ENABLE ROW LEVEL SECURITY;




ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";


ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."activity_log";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."interview_stages";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."job_candidates";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."job_openings";



GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";






















































































































































GRANT ALL ON FUNCTION "public"."check_stage_notes_on_failure"() TO "anon";
GRANT ALL ON FUNCTION "public"."check_stage_notes_on_failure"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."check_stage_notes_on_failure"() TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_candidate_deduplication"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_candidate_deduplication"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_candidate_deduplication"() TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_update_timestamp"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_update_timestamp"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_update_timestamp"() TO "service_role";



GRANT ALL ON FUNCTION "public"."is_admin"() TO "anon";
GRANT ALL ON FUNCTION "public"."is_admin"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."is_admin"() TO "service_role";



GRANT ALL ON FUNCTION "public"."is_manager"() TO "anon";
GRANT ALL ON FUNCTION "public"."is_manager"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."is_manager"() TO "service_role";



GRANT ALL ON FUNCTION "public"."is_recruiter"() TO "anon";
GRANT ALL ON FUNCTION "public"."is_recruiter"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."is_recruiter"() TO "service_role";



GRANT ALL ON FUNCTION "public"."log_record_changes"() TO "anon";
GRANT ALL ON FUNCTION "public"."log_record_changes"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."log_record_changes"() TO "service_role";



GRANT ALL ON FUNCTION "public"."prune_activity_logs"("p_before_timestamp" timestamp with time zone, "p_organization_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."prune_activity_logs"("p_before_timestamp" timestamp with time zone, "p_organization_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."prune_activity_logs"("p_before_timestamp" timestamp with time zone, "p_organization_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."upsert_linkedin_account"("p_user_id" "uuid", "p_linkedin_member_id" "text", "p_linkedin_access_token" "text", "p_linkedin_refresh_token" "text", "p_expires_at" timestamp with time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."upsert_linkedin_account"("p_user_id" "uuid", "p_linkedin_member_id" "text", "p_linkedin_access_token" "text", "p_linkedin_refresh_token" "text", "p_expires_at" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."upsert_linkedin_account"("p_user_id" "uuid", "p_linkedin_member_id" "text", "p_linkedin_access_token" "text", "p_linkedin_refresh_token" "text", "p_expires_at" timestamp with time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."validate_job_skills_weight"() TO "anon";
GRANT ALL ON FUNCTION "public"."validate_job_skills_weight"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."validate_job_skills_weight"() TO "service_role";


















GRANT ALL ON TABLE "public"."applications" TO "anon";
GRANT ALL ON TABLE "public"."applications" TO "authenticated";
GRANT ALL ON TABLE "public"."applications" TO "service_role";



GRANT ALL ON TABLE "public"."active_applications" TO "anon";
GRANT ALL ON TABLE "public"."active_applications" TO "authenticated";
GRANT ALL ON TABLE "public"."active_applications" TO "service_role";



GRANT ALL ON TABLE "public"."candidates" TO "anon";
GRANT ALL ON TABLE "public"."candidates" TO "authenticated";
GRANT ALL ON TABLE "public"."candidates" TO "service_role";



GRANT ALL ON TABLE "public"."active_candidates" TO "anon";
GRANT ALL ON TABLE "public"."active_candidates" TO "authenticated";
GRANT ALL ON TABLE "public"."active_candidates" TO "service_role";



GRANT ALL ON TABLE "public"."clients" TO "anon";
GRANT ALL ON TABLE "public"."clients" TO "authenticated";
GRANT ALL ON TABLE "public"."clients" TO "service_role";



GRANT ALL ON TABLE "public"."active_clients" TO "anon";
GRANT ALL ON TABLE "public"."active_clients" TO "authenticated";
GRANT ALL ON TABLE "public"."active_clients" TO "service_role";



GRANT ALL ON TABLE "public"."job_openings" TO "anon";
GRANT ALL ON TABLE "public"."job_openings" TO "authenticated";
GRANT ALL ON TABLE "public"."job_openings" TO "service_role";



GRANT ALL ON TABLE "public"."active_job_openings" TO "anon";
GRANT ALL ON TABLE "public"."active_job_openings" TO "authenticated";
GRANT ALL ON TABLE "public"."active_job_openings" TO "service_role";



GRANT ALL ON TABLE "public"."requirements" TO "anon";
GRANT ALL ON TABLE "public"."requirements" TO "authenticated";
GRANT ALL ON TABLE "public"."requirements" TO "service_role";



GRANT ALL ON TABLE "public"."active_requirements" TO "anon";
GRANT ALL ON TABLE "public"."active_requirements" TO "authenticated";
GRANT ALL ON TABLE "public"."active_requirements" TO "service_role";



GRANT ALL ON TABLE "public"."activity_log" TO "anon";
GRANT ALL ON TABLE "public"."activity_log" TO "authenticated";
GRANT ALL ON TABLE "public"."activity_log" TO "service_role";



GRANT ALL ON TABLE "public"."approval_logs" TO "anon";
GRANT ALL ON TABLE "public"."approval_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."approval_logs" TO "service_role";



GRANT ALL ON TABLE "public"."approval_pipeline_access" TO "anon";
GRANT ALL ON TABLE "public"."approval_pipeline_access" TO "authenticated";
GRANT ALL ON TABLE "public"."approval_pipeline_access" TO "service_role";



GRANT ALL ON TABLE "public"."approval_pipelines" TO "anon";
GRANT ALL ON TABLE "public"."approval_pipelines" TO "authenticated";
GRANT ALL ON TABLE "public"."approval_pipelines" TO "service_role";



GRANT ALL ON TABLE "public"."approval_rejection_checklists" TO "anon";
GRANT ALL ON TABLE "public"."approval_rejection_checklists" TO "authenticated";
GRANT ALL ON TABLE "public"."approval_rejection_checklists" TO "service_role";



GRANT ALL ON TABLE "public"."approval_stage_approvers" TO "anon";
GRANT ALL ON TABLE "public"."approval_stage_approvers" TO "authenticated";
GRANT ALL ON TABLE "public"."approval_stage_approvers" TO "service_role";



GRANT ALL ON TABLE "public"."approval_stages" TO "anon";
GRANT ALL ON TABLE "public"."approval_stages" TO "authenticated";
GRANT ALL ON TABLE "public"."approval_stages" TO "service_role";



GRANT ALL ON TABLE "public"."audit_logs" TO "anon";
GRANT ALL ON TABLE "public"."audit_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."audit_logs" TO "service_role";



GRANT ALL ON TABLE "public"."branches" TO "anon";
GRANT ALL ON TABLE "public"."branches" TO "authenticated";
GRANT ALL ON TABLE "public"."branches" TO "service_role";



GRANT ALL ON TABLE "public"."candidate_queries" TO "anon";
GRANT ALL ON TABLE "public"."candidate_queries" TO "authenticated";
GRANT ALL ON TABLE "public"."candidate_queries" TO "service_role";



GRANT ALL ON TABLE "public"."job_candidates" TO "anon";
GRANT ALL ON TABLE "public"."job_candidates" TO "authenticated";
GRANT ALL ON TABLE "public"."job_candidates" TO "service_role";



GRANT ALL ON TABLE "public"."candidate_rankings_view" TO "anon";
GRANT ALL ON TABLE "public"."candidate_rankings_view" TO "authenticated";
GRANT ALL ON TABLE "public"."candidate_rankings_view" TO "service_role";



GRANT ALL ON TABLE "public"."interview_assignments" TO "anon";
GRANT ALL ON TABLE "public"."interview_assignments" TO "authenticated";
GRANT ALL ON TABLE "public"."interview_assignments" TO "service_role";



GRANT ALL ON TABLE "public"."interview_feedback" TO "anon";
GRANT ALL ON TABLE "public"."interview_feedback" TO "authenticated";
GRANT ALL ON TABLE "public"."interview_feedback" TO "service_role";



GRANT ALL ON TABLE "public"."interview_stages" TO "anon";
GRANT ALL ON TABLE "public"."interview_stages" TO "authenticated";
GRANT ALL ON TABLE "public"."interview_stages" TO "service_role";



GRANT ALL ON TABLE "public"."job_opening_skills" TO "anon";
GRANT ALL ON TABLE "public"."job_opening_skills" TO "authenticated";
GRANT ALL ON TABLE "public"."job_opening_skills" TO "service_role";



GRANT ALL ON TABLE "public"."linkedin_accounts" TO "anon";
GRANT ALL ON TABLE "public"."linkedin_accounts" TO "authenticated";
GRANT ALL ON TABLE "public"."linkedin_accounts" TO "service_role";



GRANT ALL ON TABLE "public"."member_manager_assignments" TO "anon";
GRANT ALL ON TABLE "public"."member_manager_assignments" TO "authenticated";
GRANT ALL ON TABLE "public"."member_manager_assignments" TO "service_role";



GRANT ALL ON TABLE "public"."member_roles" TO "anon";
GRANT ALL ON TABLE "public"."member_roles" TO "authenticated";
GRANT ALL ON TABLE "public"."member_roles" TO "service_role";



GRANT ALL ON TABLE "public"."members" TO "anon";
GRANT ALL ON TABLE "public"."members" TO "authenticated";
GRANT ALL ON TABLE "public"."members" TO "service_role";



GRANT ALL ON TABLE "public"."notifications" TO "anon";
GRANT ALL ON TABLE "public"."notifications" TO "authenticated";
GRANT ALL ON TABLE "public"."notifications" TO "service_role";



GRANT ALL ON TABLE "public"."organizations" TO "anon";
GRANT ALL ON TABLE "public"."organizations" TO "authenticated";
GRANT ALL ON TABLE "public"."organizations" TO "service_role";



GRANT ALL ON TABLE "public"."pending_approvals" TO "anon";
GRANT ALL ON TABLE "public"."pending_approvals" TO "authenticated";
GRANT ALL ON TABLE "public"."pending_approvals" TO "service_role";



GRANT ALL ON TABLE "public"."pipeline_stages" TO "anon";
GRANT ALL ON TABLE "public"."pipeline_stages" TO "authenticated";
GRANT ALL ON TABLE "public"."pipeline_stages" TO "service_role";



GRANT ALL ON TABLE "public"."profiles" TO "anon";
GRANT ALL ON TABLE "public"."profiles" TO "authenticated";
GRANT ALL ON TABLE "public"."profiles" TO "service_role";



GRANT ALL ON TABLE "public"."recruiter_dashboard_view" TO "anon";
GRANT ALL ON TABLE "public"."recruiter_dashboard_view" TO "authenticated";
GRANT ALL ON TABLE "public"."recruiter_dashboard_view" TO "service_role";



GRANT ALL ON TABLE "public"."role_permissions" TO "anon";
GRANT ALL ON TABLE "public"."role_permissions" TO "authenticated";
GRANT ALL ON TABLE "public"."role_permissions" TO "service_role";



GRANT ALL ON TABLE "public"."roles" TO "anon";
GRANT ALL ON TABLE "public"."roles" TO "authenticated";
GRANT ALL ON TABLE "public"."roles" TO "service_role";



GRANT ALL ON TABLE "public"."rolling_updates" TO "anon";
GRANT ALL ON TABLE "public"."rolling_updates" TO "authenticated";
GRANT ALL ON TABLE "public"."rolling_updates" TO "service_role";









ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";
































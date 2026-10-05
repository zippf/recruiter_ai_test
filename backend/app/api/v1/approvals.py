from fastapi import APIRouter, Depends, HTTPException, Header, Request, Body, BackgroundTasks, Query
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from supabase import Client
from app.core.logging import logger
from app.api.dependencies import get_admin_supabase_client, get_user_org_id, get_current_user_id
from app.schemas.common import PipelineCreateInput, PipelineApproveInput, PipelineInstantiateInput, PipelineRejectInput, ApprovalEmailInput
from app.security.authorization import deobfuscate_id, user_can_manage_pipelines, user_can_approve_stage, get_stage_approver_emails
from app.services.notification_service import dispatch_approval_notifications

router = APIRouter()
@router.post("/api/v1/approvals/pipelines")
async def create_approval_pipeline(
    payload: PipelineCreateInput,
    org_id: Optional[str] = Depends(get_user_org_id),
    user_id: Optional[str] = Depends(get_current_user_id),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    if not org_id:
        raise HTTPException(status_code=400, detail="Organization ID required")
        
    db = get_admin_supabase_client()
    if not user_can_manage_pipelines(db, user_id, x_user_email):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Your role does not have permission to create approval workflows."
        )
    pipeline_res = db.table("approval_pipelines").insert({
        "organization_id": org_id,
        "name": payload.name,
        "description": payload.description,
        "is_template": payload.is_template,
        "entity_type": payload.entity_type,
        "entity_id": payload.entity_id,
        "custom_content": payload.custom_content or {},
        "created_by": user_id if user_id and not user_id.startswith("user_") else None,
        "current_stage_index": 0,
        "status": "pending" if payload.stages and not payload.is_template else "draft"
    }).execute()
    
    if not pipeline_res.data:
        raise HTTPException(status_code=500, detail="Failed to create approval pipeline")
        
    pipeline = pipeline_res.data[0]
    pipeline_id = pipeline["id"]
    
    stage_1_id = None
    # Insert stages & approvers
    for s_idx, stg in enumerate(payload.stages):
        stg_res = db.table("approval_stages").insert({
            "pipeline_id": pipeline_id,
            "stage_index": s_idx,
            "stage_name": stg.stage_name,
            "require_all_approvers": stg.require_all_approvers,
            "status": "pending" if s_idx == 0 and not payload.is_template else "pending"
        }).execute()
        
        if stg_res.data:
            stage_id = stg_res.data[0]["id"]
            if s_idx == 0:
                stage_1_id = stage_id
            for appr in stg.approvers:
                db.table("approval_stage_approvers").insert({
                    "stage_id": stage_id,
                    "role_id": appr.role_id,
                    "member_id": appr.member_id,
                    "has_approved": False
                }).execute()
                
    stage_1_emails = get_stage_approver_emails(db, stage_1_id) if stage_1_id else []

    if stage_1_emails and not payload.is_template:
        dispatch_approval_notifications(
            db=db,
            recipient_emails=stage_1_emails,
            title=f"New Approval Required: {payload.name}",
            message=f"You have been assigned as an approver for Stage 1 of '{payload.name}'.",
            html_body=f"""
              <div style="font-family: sans-serif; padding: 20px;">
                <h2 style="color: #ff6e30;">New Approval Required: {payload.name}</h2>
                <p>A new approval workflow has been submitted for Stage 1 (<strong>{payload.stages[0].stage_name if payload.stages else 'Stage 1'}</strong>).</p>
                <p><a href="http://localhost:3000/approvals" style="background: #ff6e30; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block;">Review & Approve Stage</a></p>
              </div>
            """,
            pipeline_id=pipeline_id
        )

    # Insert Audit Log
    db.table("approval_logs").insert({
        "pipeline_id": pipeline_id,
        "actor_id": user_id if user_id and not user_id.startswith("user_") else None,
        "action": "created",
        "notes": f"Created pipeline '{payload.name}'"
    }).execute()
    
    return {
        **pipeline,
        "next_stage_approver_emails": stage_1_emails,
        "next_stage_name": payload.stages[0].stage_name if payload.stages else "Stage 1"
    }

@router.get("/api/v1/approvals/admin/all")
async def get_admin_approval_pipelines(
    org_id: Optional[str] = Depends(get_user_org_id)
):
    if not org_id:
        return {"pipelines": []}
        
    db = get_admin_supabase_client()
    res = db.table("approval_pipelines").select(
        "*, approval_stages(*, approval_stage_approvers(*, members(id, name, email), roles(id, name))), approval_rejection_checklists(*), members!approval_pipelines_created_by_fkey(id, name, email, roles(name))"
    ).eq("organization_id", org_id).order("created_at", desc=True).execute()
    
    data = res.data or []
    formatted = []
    for p in data:
        creator_raw = p.get("members")
        creator = creator_raw[0] if isinstance(creator_raw, list) and len(creator_raw) > 0 and isinstance(creator_raw[0], dict) else (creator_raw if isinstance(creator_raw, dict) else {})
        creator_role = creator.get("roles")
        creator_role_dict = creator_role[0] if isinstance(creator_role, list) and len(creator_role) > 0 and isinstance(creator_role[0], dict) else (creator_role if isinstance(creator_role, dict) else {})
        
        stages_raw = p.get("approval_stages") or []
        stages_sorted = sorted(stages_raw, key=lambda s: s.get("stage_index", 0))
        
        stages_formatted = []
        for stg in stages_sorted:
            apprs_raw = stg.get("approval_stage_approvers") or []
            apprs_formatted = []
            for a in apprs_raw:
                mem_raw = a.get("members")
                mem = mem_raw[0] if isinstance(mem_raw, list) and len(mem_raw) > 0 and isinstance(mem_raw[0], dict) else (mem_raw if isinstance(mem_raw, dict) else {})
                rol_raw = a.get("roles")
                rol = rol_raw[0] if isinstance(rol_raw, list) and len(rol_raw) > 0 and isinstance(rol_raw[0], dict) else (rol_raw if isinstance(rol_raw, dict) else {})
                apprs_formatted.append({
                    **a,
                    "member_name": mem.get("name") or mem.get("email"),
                    "role_name": rol.get("name")
                })
            stages_formatted.append({
                **stg,
                "approvers": apprs_formatted
            })
            
        checklists = p.get("approval_rejection_checklists") or []
        rej_checklist = checklists[0] if checklists else None
        
        formatted.append({
            **{k: v for k, v in p.items() if k not in ["approval_stages", "approval_rejection_checklists"]},
            "created_by_name": creator.get("name") or creator.get("email") or "Member",
            "created_by_role": creator_role_dict.get("name") or "Recruiter",
            "stages": stages_formatted,
            "rejection_checklist": rej_checklist
        })
    return {"pipelines": formatted}

@router.post("/api/v1/approvals/email")
async def send_approval_notification_email(
    payload: ApprovalEmailInput,
    user_id: Optional[str] = Depends(get_current_user_id)
):
    db = get_admin_supabase_client()
    clean_email = payload.to.strip().lower()
    
    subject = payload.subject or f"Action Required: Approval for '{payload.pipelineName}'"
    
    if payload.html:
        html_body = payload.html
    elif payload.rejectionChecklist or payload.feedbackNotes:
        reasons_list = payload.rejectionChecklist.get("reasons", []) if payload.rejectionChecklist else []
        reasons_html = "".join([f"<li>{r}</li>" for r in reasons_list])
        html_body = f"""
          <div style="font-family: sans-serif; padding: 20px; max-width: 600px; margin: auto; border: 1px solid #e5e7eb; rounded: 8px;">
            <h2 style="color: #e11d48; margin-top: 0;">Revision Requested: {payload.pipelineName}</h2>
            <p>Your approval workflow <strong>{payload.pipelineName}</strong> has been returned for revisions at <strong>{payload.stageName}</strong>.</p>
            {f'<div style="background: #fff1f2; padding: 12px; border-left: 4px solid #f43f5e; margin: 15px 0;"><strong>Rejection Reasons:</strong><ul>{reasons_html}</ul></div>' if reasons_list else ''}
            {f'<p><strong>Feedback Notes:</strong> {payload.feedbackNotes}</p>' if payload.feedbackNotes else ''}
            <p style="margin-top: 20px;"><a href="http://localhost:3000/approvals" style="background: #e11d48; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">View & Update Workflow</a></p>
          </div>
        """
    else:
        html_body = f"""
          <div style="font-family: sans-serif; padding: 20px; max-width: 600px; margin: auto; border: 1px solid #e5e7eb; rounded: 8px;">
            <h2 style="color: #ff6e30; margin-top: 0;">Approval Needed: {payload.pipelineName}</h2>
            <p>You have been assigned to review and approve <strong>{payload.stageName}</strong> for <strong>{payload.pipelineName}</strong> (Submitted by {payload.submitterName}).</p>
            {f'<blockquote style="background: #f9fafb; padding: 10px; border-left: 3px solid #ff6e30; color: #4b5563;">"{payload.contentPreview}"</blockquote>' if payload.contentPreview else ''}
            <p style="margin-top: 20px;"><a href="http://localhost:3000/approvals" style="background: #ff6e30; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">Review & Approve Stage</a></p>
          </div>
        """
        
    dispatch_approval_notifications(
        db=db,
        recipient_emails=[clean_email],
        title=f"Approval Notification: {payload.pipelineName}",
        message=f"Action required for stage '{payload.stageName}' of workflow '{payload.pipelineName}'",
        html_body=html_body
    )
    return {"status": "success", "message": f"Notification dispatched to {clean_email}"}

@router.post("/api/v1/approvals/pipelines/{id}/instantiate")
async def instantiate_approval_pipeline(
    id: str,
    payload: Optional[PipelineInstantiateInput] = Body(None),
    org_id: Optional[str] = Depends(get_user_org_id),
    user_id: Optional[str] = Depends(get_current_user_id),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    db = get_admin_supabase_client()
    if not user_can_manage_pipelines(db, user_id, x_user_email):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Your role does not have permission to launch approval workflows."
        )
        
    clean_id = deobfuscate_id(id)
    pipe_res = db.table("approval_pipelines").select("*, approval_stages(*, approval_stage_approvers(*))").eq("id", clean_id).execute()
    if not pipe_res.data:
        raise HTTPException(status_code=404, detail="Template pipeline not found")
        
    template = pipe_res.data[0]
    stages = sorted(template.get("approval_stages") or [], key=lambda s: s.get("stage_index", 0))
    
    new_pipe_name = payload.name.strip() if (payload and payload.name and payload.name.strip()) else f"{template['name']} (Live)"
    new_content = payload.custom_content if (payload and payload.custom_content) else (template.get("custom_content") or {})
    
    new_pipe_res = db.table("approval_pipelines").insert({
        "organization_id": org_id or template.get("organization_id"),
        "name": new_pipe_name,
        "description": template.get("description"),
        "is_template": False,
        "entity_type": template.get("entity_type", "mandate"),
        "entity_id": template.get("entity_id"),
        "custom_content": new_content,
        "created_by": user_id if user_id and not user_id.startswith("user_") else None,
        "current_stage_index": 0,
        "status": "pending"
    }).execute()
    
    if not new_pipe_res.data:
        raise HTTPException(status_code=500, detail="Failed to instantiate pipeline from template")
        
    new_pipeline = new_pipe_res.data[0]
    new_pipe_id = new_pipeline["id"]
    new_stage_1_id = None
    
    for s_idx, stg in enumerate(stages):
        stg_res = db.table("approval_stages").insert({
            "pipeline_id": new_pipe_id,
            "stage_index": s_idx,
            "stage_name": stg.get("stage_name", f"Stage {s_idx + 1}"),
            "require_all_approvers": stg.get("require_all_approvers", False),
            "status": "pending"
        }).execute()
        
        if stg_res.data:
            new_stage_id = stg_res.data[0]["id"]
            if s_idx == 0:
                new_stage_1_id = new_stage_id
                
            approvers = stg.get("approval_stage_approvers") or []
            for appr in approvers:
                db.table("approval_stage_approvers").insert({
                    "stage_id": new_stage_id,
                    "role_id": appr.get("role_id"),
                    "member_id": appr.get("member_id"),
                    "has_approved": False
                }).execute()
                
    stage_1_emails = get_stage_approver_emails(db, new_stage_1_id) if new_stage_1_id else []
    
    if stage_1_emails:
        dispatch_approval_notifications(
            db=db,
            recipient_emails=stage_1_emails,
            title=f"Approval Workflow Launched: {new_pipe_name}",
            message=f"Workflow launched from template for Stage 1 of '{new_pipe_name}'.",
            html_body=f"""
              <div style="font-family: sans-serif; padding: 20px;">
                <h2 style="color: #ff6e30;">Workflow Launched: {new_pipe_name}</h2>
                <p>A new active workflow has been launched from a template for Stage 1 (<strong>{stages[0]['stage_name'] if stages else 'Stage 1'}</strong>).</p>
                <p><a href="http://localhost:3000/approvals" style="background: #ff6e30; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block;">Review & Approve Stage</a></p>
              </div>
            """,
            pipeline_id=new_pipe_id
        )
    
    db.table("approval_logs").insert({
        "pipeline_id": new_pipe_id,
        "actor_id": user_id if user_id and not user_id.startswith("user_") else None,
        "action": "instantiated",
        "notes": f"Launched live workflow from template '{template['name']}'"
    }).execute()
    
    return {
        **new_pipeline,
        "next_stage_approver_emails": stage_1_emails,
        "next_stage_name": stages[0]["stage_name"] if stages else "Stage 1"
    }

@router.post("/api/v1/approvals/pipelines/{id}/approve")
async def approve_pipeline_stage(
    id: str,
    payload: PipelineApproveInput,
    user_id: Optional[str] = Depends(get_current_user_id),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    db = get_admin_supabase_client()
    clean_id = deobfuscate_id(id)
    pipe_res = db.table("approval_pipelines").select("*, approval_stages(*)").eq("id", clean_id).execute()
    if not pipe_res.data:
        raise HTTPException(status_code=404, detail="Pipeline not found")
        
    pipeline = pipe_res.data[0]
    stages = sorted(pipeline.get("approval_stages") or [], key=lambda s: s["stage_index"])
    # Figure out which stage is currently "active" (waiting on approval).
    curr_idx = pipeline["current_stage_index"]
    
    if curr_idx >= len(stages):
        raise HTTPException(status_code=400, detail="Pipeline has no remaining pending stages")
        
    current_stage = stages[curr_idx]
    stage_id = current_stage["id"]
    
    # Make sure the person clicking "approve" is actually allowed to
    # approve THIS stage before recording anything.
    # STAGE AUTHORIZATION CHECK
    if not user_can_approve_stage(db, stage_id, user_id, x_user_email):
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden: You are not authorized to approve Stage {curr_idx + 1} ('{current_stage.get('stage_name')}') of this workflow."
        )
        
    # Record this specific person's approval against their
    # approval_stage_approvers row (matched by their member id, or by their
    # role if the stage was assigned to a role rather than a named person).
    # Update stage approver status
    clean_email = x_user_email.strip().lower() if x_user_email else None
    resolved_member_id = user_id if (user_id and not user_id.startswith("user_")) else None
    
    if not resolved_member_id and clean_email:
        m_res = db.table("members").select("id").ilike("email", clean_email).execute()
        if m_res.data and m_res.data[0].get("id"):
            resolved_member_id = m_res.data[0]["id"]
            
    apprs_res = db.table("approval_stage_approvers").select("*").eq("stage_id", stage_id).execute()
    apprs = apprs_res.data or []
    
    for a in apprs:
        is_match = False
        if resolved_member_id and a.get("member_id") == resolved_member_id:
            is_match = True
        elif clean_email and a.get("role_id"):
            mr_res = db.table("member_roles").select("role_id, members!inner(email)").ilike("members.email", clean_email).execute()
            user_roles = [mr["role_id"] for mr in (mr_res.data or []) if mr.get("role_id")]
            if a["role_id"] in user_roles:
                is_match = True
        elif not a.get("member_id") and not a.get("role_id"):
            is_match = True
            
        if is_match:
            db.table("approval_stage_approvers").update({
                "has_approved": True,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "notes": payload.notes
            }).eq("id", a["id"]).execute()
        
    # Depending on how this stage was configured, either EVERY listed
    # approver must approve before moving on ("require_all_approvers"), or
    # just ONE of them is enough.
    # Check consensus or 1-of-N logic
    apprs_res = db.table("approval_stage_approvers").select("*").eq("stage_id", stage_id).execute()
    apprs = apprs_res.data or []
    
    should_advance = False
    if current_stage.get("require_all_approvers"):
        should_advance = all(a.get("has_approved") for a in apprs)
    else:
        should_advance = any(a.get("has_approved") for a in apprs) or len(apprs) == 0
        
    next_stage_approver_emails = []
    next_stage_name = None

    # Consensus reached — advance the pipeline. If there's another stage
    # after this one, move to it and notify its approvers; otherwise this
    # was the last stage, so the whole pipeline is now fully approved.
    if should_advance:
        db.table("approval_stages").update({"status": "approved"}).eq("id", stage_id).execute()
        
        if curr_idx + 1 < len(stages):
            # Advance to next stage
            next_idx = curr_idx + 1
            db.table("approval_pipelines").update({
                "current_stage_index": next_idx,
                "status": "pending"
            }).eq("id", clean_id).execute()
            
            next_stage = stages[next_idx]
            next_stage_name = next_stage.get("stage_name")
            next_stage_approver_emails = get_stage_approver_emails(db, next_stage["id"])
            
            if next_stage_approver_emails:
                dispatch_approval_notifications(
                    db=db,
                    recipient_emails=next_stage_approver_emails,
                    title=f"Stage Advanced: {pipeline.get('name')}",
                    message=f"Workflow '{pipeline.get('name')}' has advanced to '{next_stage_name}' awaiting your approval.",
                    html_body=f"""
                      <div style="font-family: sans-serif; padding: 20px;">
                        <h2 style="color: #ff6e30;">Approval Needed: {pipeline.get('name')}</h2>
                        <p>The previous stage was approved. The workflow is now awaiting your sign-off for <strong>{next_stage_name}</strong>.</p>
                        <p><a href="http://localhost:3000/approvals" style="background: #ff6e30; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block;">Review & Approve Stage</a></p>
                      </div>
                    """,
                    pipeline_id=clean_id
                )
        else:
            # Final Approval!
            db.table("approval_pipelines").update({
                "status": "approved"
            }).eq("id", clean_id).execute()
            
    # Audit log
    db.table("approval_logs").insert({
        "pipeline_id": clean_id,
        "stage_id": stage_id,
        "actor_id": user_id if user_id and not user_id.startswith("user_") else None,
        "action": "stage_approved",
        "notes": payload.notes or "Stage approved"
    }).execute()
    
    return {
        "status": "success",
        "should_advance": should_advance,
        "next_stage_name": next_stage_name,
        "next_stage_approver_emails": next_stage_approver_emails
    }

@router.post("/api/v1/approvals/pipelines/{id}/reject")
async def reject_pipeline_stage(
    id: str,
    payload: PipelineRejectInput,
    user_id: Optional[str] = Depends(get_current_user_id),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    db = get_admin_supabase_client()
    clean_id = deobfuscate_id(id)
    pipe_res = db.table("approval_pipelines").select("*, approval_stages(*)").eq("id", clean_id).execute()
    if not pipe_res.data:
        raise HTTPException(status_code=404, detail="Pipeline not found")
        
    pipeline = pipe_res.data[0]
    stages = sorted(pipeline.get("approval_stages") or [], key=lambda s: s["stage_index"])
    curr_idx = pipeline["current_stage_index"]
    current_stage = stages[curr_idx] if curr_idx < len(stages) else None
    stage_id = current_stage["id"] if current_stage else None
    
    if stage_id and not user_can_approve_stage(db, stage_id, user_id, x_user_email):
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden: You are not authorized to reject Stage {curr_idx + 1} of this workflow."
        )
        
    # Store Rejection Checklist
    db.table("approval_rejection_checklists").insert({
        "pipeline_id": clean_id,
        "stage_id": stage_id,
        "rejected_by": user_id if user_id and not user_id.startswith("user_") else None,
        "reasons": payload.reasons,
        "highlighted_fields": payload.highlighted_fields,
        "feedback_notes": payload.feedback_notes
    }).execute()
    
    # Revert pipeline status to Stage 1 Draft for revision
    db.table("approval_pipelines").update({
        "status": "rejected",
        "current_stage_index": 0
    }).eq("id", clean_id).execute()
    
    if stage_id:
        db.table("approval_stages").update({"status": "rejected"}).eq("id", stage_id).execute()
        
    creator_email = None
    if pipeline.get("created_by"):
        c_res = db.table("members").select("email").eq("id", pipeline["created_by"]).execute()
        if c_res.data and c_res.data[0].get("email"):
            creator_email = c_res.data[0]["email"]
            
    # Audit Log
    db.table("approval_logs").insert({
        "pipeline_id": clean_id,
        "stage_id": stage_id,
        "actor_id": user_id if user_id and not user_id.startswith("user_") else None,
        "action": "stage_rejected",
        "notes": payload.feedback_notes or "Pipeline rejected"
    }).execute()
    
    return {
        "status": "success",
        "message": "Pipeline rejected and reverted to Stage 1 Draft with checklist feedback.",
        "creator_email": creator_email
    }

@router.delete("/api/v1/approvals/pipelines/{id}")
async def delete_approval_pipeline(
    id: str,
    org_id: Optional[str] = Depends(get_user_org_id),
    user_id: Optional[str] = Depends(get_current_user_id),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    db = get_admin_supabase_client()
    clean_id = deobfuscate_id(id)
    pipe_res = db.table("approval_pipelines").select("id, organization_id, created_by").eq("id", clean_id).execute()
    if not pipe_res.data:
        raise HTTPException(status_code=404, detail="Pipeline not found")
        
    pipeline = pipe_res.data[0]
    if org_id and pipeline.get("organization_id") and pipeline["organization_id"] != org_id:
        raise HTTPException(status_code=403, detail="Forbidden from deleting pipelines of another organization")
        
    if not user_can_manage_pipelines(db, user_id, x_user_email, pipeline.get("created_by")):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Your role does not have permission to delete approval workflows."
        )

    # Get associated stage IDs
    stg_res = db.table("approval_stages").select("id").eq("pipeline_id", clean_id).execute()
    stage_ids = [s["id"] for s in (stg_res.data or []) if "id" in s]
    
    # Delete child relational records
    if stage_ids:
        for sid in stage_ids:
            db.table("approval_stage_approvers").delete().eq("stage_id", sid).execute()
    
    db.table("approval_rejection_checklists").delete().eq("pipeline_id", clean_id).execute()
    db.table("approval_logs").delete().eq("pipeline_id", clean_id).execute()
    db.table("approval_stages").delete().eq("pipeline_id", clean_id).execute()
    db.table("approval_pipelines").delete().eq("id", clean_id).execute()
    
    return {"status": "success", "message": "Approval pipeline deleted successfully"}


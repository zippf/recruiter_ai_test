"""
Common / shared schemas.

Re-exports all models from domain-specific schema modules so that code
importing from a single place can get any model. Also holds truly cross-cutting
models that do not belong to a single resource.
"""
from app.schemas.auth import (
    AuthLogEventModel,
    PasswordOtpConfirmModel,
    PasswordOtpRequestModel,
    PruneLogsRequestModel,
    SignupRequestModel,
)
from app.schemas.applications import (
    CandidateMessageCreateModel,
    EndConversationModel,
    VerifyStatusModel,
)
from app.schemas.approvals import (
    ApprovalEmailInput,
    HighlightedFieldInput,
    PipelineAccessInput,
    PipelineApproveInput,
    PipelineCreateInput,
    PipelineInstantiateInput,
    PipelineRejectInput,
    StageApproverInput,
    StageInput,
)
from app.schemas.callbacks import (
    CandidateMatchesCallback,
    CandidateMatchItem,
    ExtractedSkill,
    GeneratedQuestion,
    JobOpeningDraft,
    JobOpeningsCallback,
    JobRegenerateCallback,
    JobSkillsCallback,
    QuestionRefineCallback,
    ScreeningQuestionsCallback,
)
from app.schemas.candidates import CandidateModel, CandidateUpdateModel, CSVUploadModel
from app.schemas.chat import ChatMessageModel
from app.schemas.clients import ClientModel
from app.schemas.jobs import (
    AppendJobsModel,
    JobOpeningModel,
    JobOpeningUpdateModel,
    JobRegenerateModel,
    SkillsApprovalModel,
)
from app.schemas.linkedin import CompanyPageModel, SharePostModel
from app.schemas.queries import AnswerQueryModel, CandidateQueryCreateModel, ResolveQueryModel
from app.schemas.questions import QuestionCreateModel
from app.schemas.requirements import RequirementModel, RequirementUpdateModel
from app.schemas.telemetry import TelemetryEventModel

__all__ = [
    "AuthLogEventModel",
    "PasswordOtpConfirmModel",
    "PasswordOtpRequestModel",
    "PruneLogsRequestModel",
    "SignupRequestModel",
    "CandidateMessageCreateModel",
    "EndConversationModel",
    "VerifyStatusModel",
    "ApprovalEmailInput",
    "HighlightedFieldInput",
    "PipelineAccessInput",
    "PipelineApproveInput",
    "PipelineCreateInput",
    "PipelineInstantiateInput",
    "PipelineRejectInput",
    "StageApproverInput",
    "StageInput",
    "CandidateMatchesCallback",
    "CandidateMatchItem",
    "ExtractedSkill",
    "GeneratedQuestion",
    "JobOpeningDraft",
    "JobOpeningsCallback",
    "JobRegenerateCallback",
    "JobSkillsCallback",
    "QuestionRefineCallback",
    "ScreeningQuestionsCallback",
    "CandidateModel",
    "CandidateUpdateModel",
    "CSVUploadModel",
    "ChatMessageModel",
    "ClientModel",
    "AppendJobsModel",
    "JobOpeningModel",
    "JobOpeningUpdateModel",
    "JobRegenerateModel",
    "SkillsApprovalModel",
    "CompanyPageModel",
    "SharePostModel",
    "AnswerQueryModel",
    "CandidateQueryCreateModel",
    "ResolveQueryModel",
    "QuestionCreateModel",
    "RequirementModel",
    "RequirementUpdateModel",
    "TelemetryEventModel",
]

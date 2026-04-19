"""API response models for all endpoints."""

from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field


# ============================================================================
# Claim Details & Extraction Results
# ============================================================================
class IdentityData(BaseModel):
    patient_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    id_number: Optional[str] = None
    id_type: Optional[str] = None
    policy_number: Optional[str] = None
    insurance_provider: Optional[str] = None
    address: Optional[str] = None
    contact_number: Optional[str] = None


class DischargeSummaryData(BaseModel):
    patient_name: Optional[str] = None
    age: Optional[str] = None
    gender: Optional[str] = None
    diagnosis_primary: Optional[str] = None
    diagnosis_secondary: Optional[List[str]] = None
    admission_date: Optional[str] = None
    discharge_date: Optional[str] = None
    length_of_stay_days: Optional[int] = None
    attending_physician: Optional[str] = None
    hospital_name: Optional[str] = None
    department: Optional[str] = None
    procedures_performed: Optional[List[str]] = None
    discharge_condition: Optional[str] = None
    follow_up_instructions: Optional[str] = None


class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    total_price: float


class ItemizedBillData(BaseModel):
    hospital_name: Optional[str] = None
    bill_date: Optional[str] = None
    patient_name: Optional[str] = None
    line_items: Optional[List[LineItem]] = None
    subtotal: Optional[float] = None
    taxes: Optional[float] = None
    discounts: Optional[float] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None


class ExtractionResults(BaseModel):
    identity: IdentityData = Field(default_factory=IdentityData)
    discharge_summary: DischargeSummaryData = Field(default_factory=DischargeSummaryData)
    itemized_bill: ItemizedBillData = Field(default_factory=ItemizedBillData)


class ClaimDetailsResponse(BaseModel):
    claimId: str
    status: str = Field(default="processing", description="processing | completed | failed | approved")
    file_name: Optional[str] = None
    upload_timestamp: Optional[str] = None
    completion_timestamp: Optional[str] = None
    page_count: int = 0
    pages_by_type: Dict[str, int] = Field(default_factory=dict)
    agents_invoked: List[str] = Field(default_factory=list)
    processing_time_seconds: Optional[float] = None
    error_message: Optional[str] = None


class DocumentBreakdown(BaseModel):
    claimId: str
    total_pages: int
    page_classifications: Dict[str, List[int]] = Field(
        description="Maps document type to list of page numbers"
    )
    document_types_found: List[str]


# ============================================================================
# Pipeline Status
# ============================================================================
class PipelineStepStatus(BaseModel):
    step_id: str
    step_name: str
    status: str = Field(description="pending | running | completed | failed")
    progress_percent: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


class PipelineStatusResponse(BaseModel):
    claimId: str
    overall_status: str = Field(description="idle | running | paused | completed | failed")
    current_step: Optional[str] = None
    progress_percent: int
    steps: List[PipelineStepStatus]
    estimated_time_remaining_seconds: Optional[int] = None


class PipelineLogEntry(BaseModel):
    timestamp: str
    level: str
    message: str


class DashboardSummary(BaseModel):
    total_claims: int
    active_pipelines: int
    completed_claims: int
    failed_claims: int
    approved_claims: int
    average_processing_time_seconds: Optional[float] = None
    recent_claims: List[ClaimDetailsResponse] = Field(default_factory=list)


# ============================================================================
# Settings
# ============================================================================
class SystemSettings(BaseModel):
    gemini_api_key_configured: bool = False
    max_file_size_mb: int = 50
    supported_document_types: List[str] = Field(
        default_factory=lambda: [
            "identity_document",
            "discharge_summary",
            "itemized_bill",
            "claim_forms",
            "cheque_or_bank_details",
            "prescription",
            "investigation_report",
            "cash_receipt",
            "other",
        ]
    )
    enable_auto_approval: bool = False
    enable_email_notifications: bool = False
    batch_processing_enabled: bool = True


# ============================================================================
# Action Responses
# ============================================================================
class ApprovalResponse(BaseModel):
    claimId: str
    status: str
    approved_at: str
    approved_by: Optional[str] = None
    message: str


class ExportResponse(BaseModel):
    claimId: str
    export_format: str = "pdf"
    download_url: str
    file_size_bytes: int
    expires_in_seconds: int


class PipelineActionResponse(BaseModel):
    claimId: str
    action: str = Field(description="pause | restart")
    status: str
    message: str

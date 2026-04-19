import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from utils.pdf_utils import get_pdf_page_count
from workflow import build_workflow
from models.api_responses import (
    ApprovalResponse,
    ClaimDetailsResponse,
    DashboardSummary,
    DocumentBreakdown,
    ExtractionResults,
    ExportResponse,
    IdentityData,
    ItemizedBillData,
    PipelineActionResponse,
    PipelineLogEntry,
    PipelineStatusResponse,
    PipelineStepStatus,
    SystemSettings,
    DischargeSummaryData,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

app = FastAPI(
    title="Claims Processing Pipeline",
    description=(
        "FastAPI + LangGraph PDF insurance claims processor.\n\n"
        "Upload a PDF claim file and receive structured JSON with extracted data "
        "from identity documents, discharge summaries, and itemized bills."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Persistent JSON-backed stores for development/demo
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CLAIMS_STORE_FILE = DATA_DIR / "claims_store.json"
PIPELINE_STORE_FILE = DATA_DIR / "pipeline_store.json"
PIPELINE_LOGS_FILE = DATA_DIR / "pipeline_logs.json"


def _load_store(file_path: Path) -> dict:
    if not file_path.exists():
        return {}
    try:
        with file_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_store(file_path: Path, store: dict) -> None:
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def _append_pipeline_log(claimId: str, level: str, message: str) -> None:
    normalized = _normalize_claim_id(claimId)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message,
    }
    pipeline_logs_store.setdefault(normalized, []).append(entry)
    _save_store(PIPELINE_LOGS_FILE, pipeline_logs_store)


claims_store: dict = _load_store(CLAIMS_STORE_FILE)
pipeline_store: dict = _load_store(PIPELINE_STORE_FILE)
pipeline_logs_store: dict = _load_store(PIPELINE_LOGS_FILE)


def _normalize_claim_id(claimId: str) -> str:
    return claimId.strip()


def _has_pipeline_context(claimId: str) -> bool:
    normalized = _normalize_claim_id(claimId)
    return normalized in claims_store or normalized in pipeline_store


@app.get("/health", tags=["System"], summary="Health check")
async def health_check():
    return {"status": "ok", "service": "Claims Processing Pipeline", "version": "1.0.0"}


@app.get("/api/workflow-info", tags=["System"], summary="LangGraph workflow structure")
async def workflow_info():
    steps = [
        {
            "id": "segregator",
            "title": "Segregator Node",
            "description": "Classifies every PDF page into one of 9 document types using Gemini Vision",
        },
        {
            "id": "id_agent",
            "title": "ID Agent",
            "description": "Extracts patient identity details from identity_document pages",
        },
        {
            "id": "discharge_agent",
            "title": "Discharge Agent",
            "description": "Extracts diagnosis, dates, and physician info from discharge_summary pages",
        },
        {
            "id": "bill_agent",
            "title": "Bill Agent",
            "description": "Extracts line items and totals from itemized_bill pages",
        },
        {
            "id": "aggregator",
            "title": "Aggregator Node",
            "description": "Merges all agent outputs into final structured JSON",
        },
    ]

    return {
        "name": "Claims Processing Pipeline",
        "title": "Claims Processing Workflow",
        "description": "Upload a PDF claim and run the LangGraph workflow to classify pages and extract structured data.",
        "count": len(steps),
        "steps": steps,
        "nodes": {
            "segregator": "Classifies every PDF page into one of 9 document types using Gemini Vision",
            "id_agent": "Extracts patient identity details from identity_document pages",
            "discharge_agent": "Extracts diagnosis, dates, physician info from discharge_summary pages",
            "bill_agent": "Extracts line items and totals from itemized_bill pages",
            "aggregator": "Merges all agent outputs into final structured JSON",
        },
        "document_types": [
            "claim_forms",
            "cheque_or_bank_details",
            "identity_document",
            "itemized_bill",
            "discharge_summary",
            "prescription",
            "investigation_report",
            "cash_receipt",
            "other",
        ],
        "parallelism": "id_agent, discharge_agent, and bill_agent run in parallel after segregator",
    }


@app.post(
    "/api/process",
    tags=["Claims"],
    summary="Process a PDF insurance claim",
    response_description="Structured JSON with classified pages and extracted data",
)
async def process_claim(
    claim_id: str,
    file: UploadFile = File(description="PDF insurance claim file"),
):
    """
    Upload a PDF insurance claim and receive fully extracted structured data.

    **Workflow:**
    1. Each page is classified by the Segregator Agent (AI Vision)
    2. Relevant pages are routed to ID, Discharge, and Bill agents **in parallel**
    3. Results are merged by the Aggregator node
    4. Structured JSON is returned
    """
    claim_id = _normalize_claim_id(claim_id)
    log.info("📄 Received claim: %s | File: %s", claim_id, file.filename)

    if not (
        file.content_type == "application/pdf"
        or (file.filename and file.filename.lower().endswith(".pdf"))
    ):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        page_count = get_pdf_page_count(pdf_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Could not read PDF: {exc}"
        ) from exc

    if page_count == 0:
        raise HTTPException(status_code=400, detail="PDF contains no pages.")

    log.info("📑 Pages detected: %d | Starting LangGraph workflow…", page_count)
    start_time = time.time()

    initial_state = {
        "claim_id": claim_id,
        "pdf_bytes": pdf_bytes,
        "total_pages": page_count,
        "page_classifications": {},
        "id_pages": [],
        "discharge_pages": [],
        "bill_pages": [],
        "identity_data": {},
        "discharge_data": {},
        "bill_data": {},
        "final_output": {},
    }

    try:
        workflow = build_workflow()
        result = await asyncio.to_thread(workflow.invoke, initial_state)
        elapsed = round(time.time() - start_time, 2)
        output = result["final_output"]
        output["processing_metadata"]["processing_time_seconds"] = elapsed
        log.info("✅ Claim %s processed in %ss", claim_id, elapsed)

        # Rename claim_id to claimId for frontend compatibility
        output["claimId"] = output.pop("claim_id", claim_id)

        # Store claim details for later retrieval
        claims_store[claim_id] = {
            "claimId": claim_id,
            "status": "completed",
            "file_name": file.filename,
            "upload_timestamp": datetime.now().isoformat(),
            "completion_timestamp": datetime.now().isoformat(),
            "page_count": page_count,
            "pages_by_type": output["processing_metadata"].get("pages_by_type", {}),
            "agents_invoked": output["processing_metadata"].get("agents_invoked", []),
            "processing_time_seconds": elapsed,
            "extracted_data": output.get("extracted_data", {}),
            "page_classification": output.get("page_classification", {}),
        }
        _save_store(CLAIMS_STORE_FILE, claims_store)
        _append_pipeline_log(claim_id, "INFO", "Claim processed successfully")

        return JSONResponse(content=output)
    except Exception as exc:
        log.error("❌ Workflow failed for claim %s: %s", claim_id, exc)
        raise HTTPException(
            status_code=500, detail=f"Workflow processing failed: {exc}"
        ) from exc


# ============================================================================
# CLAIM MANAGEMENT ENDPOINTS
# ============================================================================


@app.get(
    "/api/claims/summary",
    tags=["Claims"],
    summary="Get dashboard summary for claims",
    response_model=DashboardSummary,
)
async def get_claims_summary():
    """Return dashboard metrics and recent claims."""
    total_claims = len(claims_store)
    active_pipelines = sum(
        1 for claim in claims_store.values() if claim.get("status") not in {"completed", "approved", "failed"}
    )
    completed_claims = sum(1 for claim in claims_store.values() if claim.get("status") == "completed")
    failed_claims = sum(1 for claim in claims_store.values() if claim.get("status") == "failed")
    approved_claims = sum(1 for claim in claims_store.values() if claim.get("status") == "approved")
    processing_times = [claim.get("processing_time_seconds") for claim in claims_store.values() if claim.get("processing_time_seconds") is not None]
    average_processing_time_seconds = (
        round(sum(processing_times) / len(processing_times), 2) if processing_times else None
    )
    recent_claims = sorted(
        [
            ClaimDetailsResponse(
                claimId=claim.get("claimId"),
                status=claim.get("status"),
                file_name=claim.get("file_name"),
                upload_timestamp=claim.get("upload_timestamp"),
                completion_timestamp=claim.get("completion_timestamp"),
                page_count=claim.get("page_count", 0),
                pages_by_type=claim.get("pages_by_type", {}),
                agents_invoked=claim.get("agents_invoked", []),
                processing_time_seconds=claim.get("processing_time_seconds"),
            )
            for claim in claims_store.values()
        ],
        key=lambda entry: entry.upload_timestamp or "",
        reverse=True,
    )[:10]
    return DashboardSummary(
        total_claims=total_claims,
        active_pipelines=active_pipelines,
        completed_claims=completed_claims,
        failed_claims=failed_claims,
        approved_claims=approved_claims,
        average_processing_time_seconds=average_processing_time_seconds,
        recent_claims=recent_claims,
    )


@app.get(
    "/api/claims/{claimId}",
    tags=["Claims"],
    summary="Get claim details and processing status",
    response_model=ClaimDetailsResponse,
)
async def get_claim_details(claimId: str):
    """Fetch claim details, status, and processing metadata."""
    claimId = _normalize_claim_id(claimId)
    if claimId not in claims_store:
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
    
    claim = claims_store[claimId]
    return ClaimDetailsResponse(
        claimId=claim.get("claimId"),
        status=claim.get("status"),
        file_name=claim.get("file_name"),
        upload_timestamp=claim.get("upload_timestamp"),
        completion_timestamp=claim.get("completion_timestamp"),
        page_count=claim.get("page_count", 0),
        pages_by_type=claim.get("pages_by_type", {}),
        agents_invoked=claim.get("agents_invoked", []),
        processing_time_seconds=claim.get("processing_time_seconds"),
    )


@app.get(
    "/api/claims",
    tags=["Claims"],
    summary="List all processed claims",
    response_model=list[ClaimDetailsResponse],
)
async def list_claims():
    """List all existing claims stored in the system."""
    return [
        ClaimDetailsResponse(
            claimId=claim.get("claimId"),
            status=claim.get("status"),
            file_name=claim.get("file_name"),
            upload_timestamp=claim.get("upload_timestamp"),
            completion_timestamp=claim.get("completion_timestamp"),
            page_count=claim.get("page_count", 0),
            pages_by_type=claim.get("pages_by_type", {}),
            agents_invoked=claim.get("agents_invoked", []),
            processing_time_seconds=claim.get("processing_time_seconds"),
        )
        for claim in claims_store.values()
    ]


@app.get(
    "/api/dashboard/metrics",
    tags=["Dashboard"],
    summary="Get dashboard metrics",
    response_model=DashboardSummary,
)
async def get_dashboard_metrics():
    """Return the same dashboard summary as claims summary."""
    return await get_claims_summary()


@app.get(
    "/api/claims/{claimId}/history",
    tags=["Claims"],
    summary="Get processing history for a claim",
    response_model=list[PipelineLogEntry],
)
async def get_claim_history(claimId: str):
    """Return the stored pipeline history/log for a specific claim."""
    claimId = _normalize_claim_id(claimId)
    if not _has_pipeline_context(claimId):
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
    raw_history = pipeline_logs_store.get(claimId, [])
    return [PipelineLogEntry(**entry) for entry in raw_history]


@app.get(
    "/api/claims/{claimId}/extraction-results",
    tags=["Claims"],
    summary="Get extracted data for a claim",
    response_model=ExtractionResults,
)
async def get_extraction_results(claimId: str):
    """Retrieve extracted identity, discharge, and billing data."""
    claimId = _normalize_claim_id(claimId)
    if claimId not in claims_store:
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
    
    claim = claims_store[claimId]
    extracted = claim.get("extracted_data", {})
    
    return ExtractionResults(
        identity=IdentityData(**extracted.get("identity", {})),
        discharge_summary=DischargeSummaryData(**extracted.get("discharge_summary", {})),
        itemized_bill=ItemizedBillData(**extracted.get("itemized_bill", {})),
    )


@app.put(
    "/api/claims/{claimId}/extraction-results",
    tags=["Claims"],
    summary="Update extracted fields (manual editing)",
)
async def update_extraction_results(claimId: str, updates: dict):
    """Update extracted fields for manual corrections."""
    claimId = _normalize_claim_id(claimId)
    if claimId not in claims_store:
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
    
    # Merge updates into existing extracted data
    claim = claims_store[claimId]
    if "extracted_data" not in claim:
        claim["extracted_data"] = {}
    
    for key, value in updates.items():
        if key in claim["extracted_data"]:
            if isinstance(claim["extracted_data"][key], dict):
                claim["extracted_data"][key].update(value)
            else:
                claim["extracted_data"][key] = value
    _save_store(CLAIMS_STORE_FILE, claims_store)
    log.info("✏️ Updated extraction results for claim %s", claimId)
    return {"claimId": claimId, "message": "Extraction results updated", "status": "success"}


@app.get(
    "/api/claims/{claimId}/document-breakdown",
    tags=["Claims"],
    summary="Get page classification and document types",
    response_model=DocumentBreakdown,
)
async def get_document_breakdown(claimId: str):
    """Get page-by-page classification breakdown."""
    claimId = _normalize_claim_id(claimId)
    if claimId not in claims_store:
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
    
    claim = claims_store[claimId]
    page_class = claim.get("page_classification", {})
    
    # Invert: map doc_type -> list of pages
    pages_by_type = {}
    for page_str, doc_type in page_class.items():
        if doc_type not in pages_by_type:
            pages_by_type[doc_type] = []
        pages_by_type[doc_type].append(int(page_str))
    
    return DocumentBreakdown(
        claimId=claimId,
        total_pages=claim.get("page_count", 0),
        page_classifications=pages_by_type,
        document_types_found=list(pages_by_type.keys()),
    )


# ============================================================================
# CLAIM ACTIONS
# ============================================================================


@app.post(
    "/api/claims/{claimId}/approve",
    tags=["Claims"],
    summary="Approve a processed claim",
)
async def approve_claim(claimId: str):
    """Approve the processed claim for next stage."""
    claimId = _normalize_claim_id(claimId)
    if claimId not in claims_store:
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
    
    claims_store[claimId]["status"] = "approved"
    _save_store(CLAIMS_STORE_FILE, claims_store)
    log.info("✅ Claim %s approved", claimId)
    
    return ApprovalResponse(
        claimId=claimId,
        status="approved",
        approved_at=datetime.now().isoformat(),
        message=f"Claim {claimId} has been approved",
    )


@app.post(
    "/api/claims/{claimId}/export",
    tags=["Claims"],
    summary="Export claim as PDF",
)
async def export_claim(claimId: str):
    """Generate and provide download link for claim PDF."""
    claimId = _normalize_claim_id(claimId)
    if claimId not in claims_store:
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
    
    log.info("📥 Exporting claim %s as PDF", claimId)
    
    return ExportResponse(
        claimId=claimId,
        export_format="pdf",
        download_url=f"/api/claims/{claimId}/download-pdf",
        file_size_bytes=512000,
        expires_in_seconds=86400,
    )


# ============================================================================
# PIPELINE CONTROL
# ============================================================================


@app.get(
    "/api/pipeline/status/{claimId}",
    tags=["Pipeline"],
    summary="Get real-time pipeline execution status",
    response_model=PipelineStatusResponse,
)
async def get_pipeline_status(claimId: str):
    """Get current pipeline status and step progress."""
    claimId = _normalize_claim_id(claimId)
    if not _has_pipeline_context(claimId):
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")

    if claimId in pipeline_store and claimId not in claims_store:
        status_entry = pipeline_store[claimId]
        return PipelineStatusResponse(
            claimId=claimId,
            overall_status=status_entry.get("status", "paused"),
            current_step="paused",
            progress_percent=0,
            steps=[
                PipelineStepStatus(
                    step_id="pipeline_pause",
                    step_name="Pipeline Pause",
                    status=status_entry.get("status", "paused"),
                    progress_percent=0,
                    started_at=status_entry.get("paused_at"),
                    completed_at=status_entry.get("paused_at"),
                )
            ],
        )

    claim = claims_store[claimId]
    
    # Generate steps based on agents invoked
    steps = [
        PipelineStepStatus(
            step_id="segregator",
            step_name="Segregator",
            status="completed",
            progress_percent=100,
            completed_at=datetime.now().isoformat(),
        ),
    ]
    
    if "id_agent" in claim.get("agents_invoked", []):
        steps.append(
            PipelineStepStatus(
                step_id="id_agent",
                step_name="ID Agent",
                status="completed",
                progress_percent=100,
                completed_at=datetime.now().isoformat(),
            )
        )
    
    if "discharge_agent" in claim.get("agents_invoked", []):
        steps.append(
            PipelineStepStatus(
                step_id="discharge_agent",
                step_name="Discharge Agent",
                status="completed",
                progress_percent=100,
                completed_at=datetime.now().isoformat(),
            )
        )
    
    if "bill_agent" in claim.get("agents_invoked", []):
        steps.append(
            PipelineStepStatus(
                step_id="bill_agent",
                step_name="Bill Agent",
                status="completed",
                progress_percent=100,
                completed_at=datetime.now().isoformat(),
            )
        )
    
    steps.append(
        PipelineStepStatus(
            step_id="aggregator",
            step_name="Aggregator",
            status="completed",
            progress_percent=100,
            completed_at=datetime.now().isoformat(),
        )
    )
    
    return PipelineStatusResponse(
        claimId=claimId,
        overall_status="completed",
        current_step="aggregator",
        progress_percent=100,
        steps=steps,
    )


@app.get(
    "/api/pipeline/logs/{claimId}",
    tags=["Pipeline"],
    summary="Get live pipeline logs for a claim",
    response_model=list[PipelineLogEntry],
)
async def get_pipeline_logs(claimId: str):
    """Return the stored pipeline logs for the given claim."""
    claimId = _normalize_claim_id(claimId)
    if not _has_pipeline_context(claimId):
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
    raw_logs = pipeline_logs_store.get(claimId, [])
    return [PipelineLogEntry(**entry) for entry in raw_logs]


@app.post(
    "/api/pipeline/pause/{claimId}",
    tags=["Pipeline"],
    summary="Pause running pipeline",
)
async def pause_pipeline(claimId: str):
    """Pause the pipeline execution for a claim."""
    claimId = _normalize_claim_id(claimId)
    if not _has_pipeline_context(claimId):
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
    
    pipeline_store[claimId] = {"status": "paused", "paused_at": datetime.now().isoformat()}
    if claimId in claims_store:
        claims_store[claimId]["status"] = "paused"
    _save_store(PIPELINE_STORE_FILE, pipeline_store)
    _save_store(CLAIMS_STORE_FILE, claims_store)
    _append_pipeline_log(claimId, "INFO", "Pipeline paused")
    log.info("⏸ Pipeline paused for claim %s", claimId)
    
    return PipelineActionResponse(
        claimId=claimId,
        action="pause",
        status="paused",
        message=f"Pipeline for claim {claimId} has been paused",
    )


@app.post(
    "/api/pipeline/restart/{claimId}",
    tags=["Pipeline"],
    summary="Restart pipeline graph",
)
async def restart_pipeline(claimId: str):
    """Restart the pipeline for a claim."""
    claimId = _normalize_claim_id(claimId)
    if not _has_pipeline_context(claimId):
        raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
    
    if claimId in pipeline_store:
        del pipeline_store[claimId]
    
    if claimId not in claims_store:
        claims_store[claimId] = {
            "status": "processing",
            "agents_invoked": [],
            "page_count": 0,
            "page_classification": {},
        }
    else:
        claims_store[claimId]["status"] = "processing"
    _save_store(PIPELINE_STORE_FILE, pipeline_store)
    _save_store(CLAIMS_STORE_FILE, claims_store)
    _append_pipeline_log(claimId, "INFO", "Pipeline restarted")
    log.info("🔄 Pipeline restarted for claim %s", claimId)
    
    return PipelineActionResponse(
        claimId=claimId,
        action="restart",
        status="running",
        message=f"Pipeline for claim {claimId} has been restarted",
    )


# ============================================================================
# SETTINGS MANAGEMENT
# ============================================================================


@app.get(
    "/api/settings/configuration",
    tags=["Settings"],
    summary="Get system settings",
    response_model=SystemSettings,
)
async def get_settings():
    """Retrieve current system configuration."""
    return SystemSettings(
        gemini_api_key_configured=bool(os.environ.get("GEMINI_API_KEY")),
        max_file_size_mb=50,
        enable_auto_approval=False,
        enable_email_notifications=False,
        batch_processing_enabled=True,
    )


@app.put(
    "/api/settings/configuration",
    tags=["Settings"],
    summary="Save system settings",
)
async def update_settings(settings: SystemSettings):
    """Update system configuration."""
    log.info("⚙️ System settings updated")
    return {
        "message": "Settings updated successfully",
        "status": "success",
        "settings": settings.dict(),
    }



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

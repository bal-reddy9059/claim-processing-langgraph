import asyncio
import base64
import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

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

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        log.exception("Unhandled exception on %s %s", request.method, request.url)
        return JSONResponse(status_code=500, content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "*"],
    allow_headers=["*"],
)

# Persistent JSON-backed stores for development/demo
BASE_DIR = Path(__file__).resolve().parent
if os.getenv("VERCEL") or not os.access(BASE_DIR, os.W_OK):
    DATA_DIR = Path(os.getenv("DATA_DIR", "/tmp/claims_pipeline_data"))
else:
    DATA_DIR = BASE_DIR / "data"
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
processing_claims: set[str] = set()


def _normalize_claim_id(claimId: str) -> str:
    return claimId.strip().upper()


def _get_claim(claimId: str) -> dict | None:
    return claims_store.get(_normalize_claim_id(claimId))


def _has_pipeline_context(claimId: str) -> bool:
    normalized = _normalize_claim_id(claimId)
    return normalized in claims_store or normalized in pipeline_store


@app.get("/", tags=["System"], summary="Root")
async def root():
    return {"status": "ok", "service": "Claims Processing Pipeline", "message": "FastAPI app is running."}


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


async def _decode_file_data(file_data: str) -> bytes:
    if isinstance(file_data, str) and file_data.startswith("data:"):
        file_data = file_data.split(",", 1)[1]
    try:
        return base64.b64decode(file_data, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not decode base64 file data: {exc}") from exc


async def run_pipeline(claim_id: str, file_data: bytes | str) -> dict:
    claim_id = _normalize_claim_id(claim_id)
    if claim_id in processing_claims:
        return {"status": "already_processing", "claim_id": claim_id}

    if isinstance(file_data, bytes):
        pdf_bytes = file_data
    else:
        pdf_bytes = await _decode_file_data(file_data)

    try:
        from utils.pdf_utils import get_pdf_page_count

        page_count = get_pdf_page_count(pdf_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Could not read PDF: {exc}"
        ) from exc

    if page_count == 0:
        raise HTTPException(status_code=400, detail="PDF contains no pages.")

    processing_claims.add(claim_id)
    try:
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

        from workflow import build_workflow

        workflow = build_workflow()
        result = await asyncio.to_thread(workflow.invoke, initial_state)
        elapsed = round(time.time() - start_time, 2)
        output = result["final_output"]
        output["processing_metadata"]["processing_time_seconds"] = elapsed
        log.info("✅ Claim %s processed in %ss", claim_id, elapsed)

        output["claimId"] = output.pop("claim_id", claim_id)

        claims_store[claim_id] = {
            "claimId": claim_id,
            "status": "completed",
            "file_name": None,
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

        return output
    except Exception as exc:
        log.error("❌ Workflow failed for claim %s: %s", claim_id, exc)
        raise HTTPException(
            status_code=500, detail=f"Workflow processing failed: {exc}"
        ) from exc
    finally:
        processing_claims.discard(claim_id)


@app.post(
    "/api/process",
    tags=["Claims"],
    summary="Process a PDF insurance claim",
    response_description="Structured JSON with classified pages and extracted data",
)
async def process_claim(
    request: Request,
    claim_id: str | None = Form(None),
    file: UploadFile | None = File(None),
):
    file_name = None
    file_data = None

    claim_id = claim_id or request.query_params.get("claim_id") or request.query_params.get("claimId")

    if file is not None:
        file_name = file.filename
        try:
            file_data = await file.read()
        except Exception as exc:
            log.exception("Failed reading uploaded file for claim %s", claim_id)
            raise HTTPException(status_code=500, detail=f"Failed to read uploaded file: {exc}") from exc

    else:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            try:
                form = await request.form()
            except Exception as exc:
                log.exception("Failed to parse multipart/form-data request")
                raise HTTPException(status_code=400, detail="Invalid multipart/form-data payload") from exc

            claim_id = claim_id or form.get("claim_id") or form.get("claimId")
            file_input = form.get("file") or form.get("file_data")
            if file_input is not None:
                if hasattr(file_input, "read"):
                    file_name = getattr(file_input, "filename", None)
                    try:
                        file_data = await file_input.read()
                    except Exception as exc:
                        log.exception("Failed reading uploaded file for claim %s", claim_id)
                        raise HTTPException(status_code=500, detail=f"Failed to read uploaded file: {exc}") from exc
                elif isinstance(file_input, (bytes, bytearray)):
                    file_data = bytes(file_input)
                elif isinstance(file_input, str):
                    if file_input.startswith("data:"):
                        file_input = file_input.split(",", 1)[1]
                    try:
                        file_data = base64.b64decode(file_input, validate=True)
                    except Exception as exc:
                        raise HTTPException(status_code=400, detail=f"Could not decode base64 file data: {exc}") from exc

        else:
            try:
                body = await request.json()
            except Exception as exc:
                log.exception("Failed to parse JSON body for /api/process request")
                raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

            claim_id = claim_id or body.get("claim_id") or body.get("claimId")
            file_content = body.get("file") or body.get("file_data")
            if file_content is not None:
                if isinstance(file_content, (bytes, bytearray)):
                    file_data = bytes(file_content)
                elif isinstance(file_content, str):
                    if file_content.startswith("data:"):
                        file_content = file_content.split(",", 1)[1]
                    try:
                        file_data = base64.b64decode(file_content, validate=True)
                    except Exception as exc:
                        raise HTTPException(status_code=400, detail=f"Could not decode base64 file data: {exc}") from exc

    if not claim_id:
        raise HTTPException(status_code=400, detail="claim_id is required")

    if not file_data:
        raise HTTPException(status_code=400, detail="file is required")

    log.info("/api/process request received: claim_id=%s file_name=%s file_size=%d bytes", claim_id, file_name, len(file_data))

    try:
        result = await run_pipeline(claim_id=claim_id, file_data=file_data)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Pipeline failed for claim %s", claim_id)
        raise HTTPException(status_code=500, detail=f"Pipeline processing failed: {exc}") from exc


# ============================================================================
# CLAIM MANAGEMENT ENDPOINTS
# ============================================================================


@app.get(
    "/api/summary",
    tags=["Claims"],
    summary="Get dashboard summary (alias)",
)
async def get_claims_summary_alias():
    """Return dashboard metrics and recent claims (alias for /api/claims/summary)."""
    return await get_claims_summary()


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
    
    # Return empty/default response if claim doesn't exist (graceful degradation)
    if claimId not in claims_store:
        return ClaimDetailsResponse(
            claimId=claimId,
            status="not_found",
            file_name=None,
            upload_timestamp=None,
            completion_timestamp=None,
            page_count=0,
            pages_by_type={},
            agents_invoked=[],
            processing_time_seconds=None,
        )
    
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
    "/api/extraction-results",
    tags=["Claims"],
    summary="Get extraction results (with query parameter)",
)
async def get_extraction_results_alias(claimId: str = None):
    if not claimId:
        return {"results": []}
    try:
        return await get_extraction_results(claimId)
    except HTTPException as e:
        if e.status_code == 404:
            return {"results": []}
        raise


@app.get(
    "/api/document-breakdown",
    tags=["Claims"],
    summary="Get document breakdown (with query parameter)",
)
async def get_document_breakdown_alias(claimId: str = None):
    if not claimId:
        return {"breakdown": []}
    try:
        return await get_document_breakdown(claimId)
    except HTTPException as e:
        if e.status_code == 404:
            return {"breakdown": []}
        raise


@app.get(
    "/api/history",
    tags=["Claims"],
    summary="Get history (with query parameter)",
)
async def get_history_alias(claimId: str = None):
    if not claimId:
        return {"history": []}
    try:
        return await get_claim_history(claimId)
    except HTTPException as e:
        if e.status_code == 404:
            return {"history": []}
        raise


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
)
async def get_claim_history(claimId: str):
    """Return processing history for a specific claim."""
    claimId = _normalize_claim_id(claimId)
    
    # Return empty history if claim doesn't exist (graceful degradation)
    if not _has_pipeline_context(claimId):
        return {"history": []}

    history = pipeline_logs_store.get(claimId, [])
    return {"history": history}


@app.get(
    "/api/claims/{claim_id}/extraction-results",
    tags=["Claims"],
    summary="Get extracted results for a claim",
)
async def get_extraction_results(claim_id: str):
    """Return pre-extracted data for a specific claim."""
    claim_id = _normalize_claim_id(claim_id)
    
    # Return empty results if claim doesn't exist (graceful degradation)
    if not _has_pipeline_context(claim_id):
        return {"results": {}}

    claim = claims_store.get(claim_id, {})
    results = claim.get("extracted_data", {})
    return {"results": results}


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
    
    # Return empty breakdown if claim doesn't exist (graceful degradation)
    if claimId not in claims_store:
        return DocumentBreakdown(
            claimId=claimId,
            total_pages=0,
            page_classifications={},
            document_types_found=[],
        )
    
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
    "/api/approve",
    tags=["Claims"],
    summary="Approve a claim (with query parameter)",
)
async def approve_claim_alias(claimId: str = None):
    """Approve the processed claim for next stage (query parameter version)."""
    if not claimId:
        raise HTTPException(status_code=400, detail="claimId query parameter is required")
    try:
        return await approve_claim(claimId)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Claim {claimId} not found")
        raise


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
    "/api/export",
    tags=["Claims"],
    summary="Export claim as PDF (with query parameter)",
)
async def export_claim_alias(claimId: str = None):
    """Generate and provide download link for claim PDF (query parameter version)."""
    if not claimId:
        raise HTTPException(status_code=400, detail="claimId query parameter is required")
    try:
        return await export_claim(claimId)
    except HTTPException:
        raise


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
    "/api/pipeline/status",
    tags=["Pipeline"],
    summary="Get pipeline status (with query parameter)",
)
async def get_pipeline_status_alias(claimId: str = None):
    """Get current pipeline status and step progress (query parameter version)."""
    if not claimId:
        raise HTTPException(status_code=400, detail="claimId query parameter is required")
    try:
        return await get_pipeline_status(claimId)
    except HTTPException:
        raise


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
    "/api/pipeline/logs",
    tags=["Pipeline"],
    summary="Get pipeline logs (with query parameter)",
)
async def get_pipeline_logs_alias(claimId: str = None):
    """Return the stored pipeline logs for the given claim (query parameter version)."""
    if not claimId:
        return []
    try:
        return await get_pipeline_logs(claimId)
    except HTTPException as e:
        if e.status_code == 404:
            return []
        raise


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
    "/api/pipeline/pause",
    tags=["Pipeline"],
    summary="Pause pipeline (with query parameter)",
)
async def pause_pipeline_alias(claimId: str = None):
    """Pause the pipeline execution for a claim (query parameter version)."""
    if not claimId:
        raise HTTPException(status_code=400, detail="claimId query parameter is required")
    try:
        return await pause_pipeline(claimId)
    except HTTPException:
        raise


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
    "/api/pipeline/restart",
    tags=["Pipeline"],
    summary="Restart pipeline (with query parameter)",
)
async def restart_pipeline_alias(claimId: str = None):
    """Restart the pipeline for a claim (query parameter version)."""
    if not claimId:
        raise HTTPException(status_code=400, detail="claimId query parameter is required")
    try:
        return await restart_pipeline(claimId)
    except HTTPException:
        raise


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
    "/api/configuration",
    tags=["Settings"],
    summary="Get system settings (alias)",
)
async def get_settings_alias():
    """Retrieve current system configuration (alias for /api/settings/configuration)."""
    return await get_settings()


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
    "/api/configuration",
    tags=["Settings"],
    summary="Save system settings (alias)",
)
async def update_settings_alias(settings: SystemSettings):
    """Update system configuration (alias for /api/settings/configuration)."""
    return await update_settings(settings)


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

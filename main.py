import asyncio
import logging
import os
import time

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from utils.pdf_utils import get_pdf_page_count
from workflow import build_workflow

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


@app.get("/health", tags=["System"], summary="Health check")
async def health_check():
    return {"status": "ok", "service": "Claims Processing Pipeline", "version": "1.0.0"}


@app.get("/api/workflow-info", tags=["System"], summary="LangGraph workflow structure")
async def workflow_info():
    return {
        "workflow": "LangGraph StateGraph",
        "flow": "START -> segregator -> [id_agent || discharge_agent || bill_agent] -> aggregator -> END",
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
    claim_id: str = Form(default="CLM-2024-001", description="Unique claim identifier  e.g. CLM-2024-001"),
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
        return JSONResponse(content=output)
    except Exception as exc:
        log.error("❌ Workflow failed for claim %s: %s", claim_id, exc)
        raise HTTPException(
            status_code=500, detail=f"Workflow processing failed: {exc}"
        ) from exc


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

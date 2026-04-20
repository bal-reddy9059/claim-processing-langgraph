# Complete API Reference - 14 Endpoints

## System Health & Workflow (2 APIs)

### 1. GET /health
**Health Check**
- No parameters required
- Response: `{ "status": "ok", "service": "Claims Processing Pipeline", "version": "1.0.0" }`

### 2. GET /api/workflow-info
**Workflow Configuration & Structure**
- Returns workflow metadata, step count, node descriptions, and document types
- Frontend reads: `name`, `title`, `description`, `count` (steps count), `steps` array

---

## Claim Processing (1 API)

### 3. POST /api/process
**Upload & Process PDF Claim**
- **Request**: multipart/form-data
  - `claimId` (string) - Unique claim identifier
  - `file` (PDF file) - Insurance claim PDF
- **Response**: Structured JSON with extracted data, page classifications, and metadata
- Stores claim automatically in memory for later retrieval

---

## Claim Management (4 APIs)

### 4. GET /api/claims/{claimId}
**Get Claim Details & Status**
- **Response Model**:
  ```json
  {
    "claimId": "CLM-2024-001",
    "status": "completed|processing|failed|approved",
    "file_name": "claim.pdf",
    "upload_timestamp": "2026-04-19T10:30:00",
    "completion_timestamp": "2026-04-19T10:35:00",
    "page_count": 5,
    "pages_by_type": {
      "identity_document": 1,
      "discharge_summary": 2,
      "itemized_bill": 1,
      "claim_forms": 1
    },
    "agents_invoked": ["id_agent", "discharge_agent", "bill_agent"],
    "processing_time_seconds": 45.2
  }
  ```

### 5. GET /api/claims/{claimId}/extraction-results
**Get Extracted Data**
- Returns extracted identity, discharge summary, and itemized bill data
- Frontend can use this for review and editing
- **Response**: Structured extraction results with all classified fields

### 6. PUT /api/claims/{claimId}/extraction-results
**Update Extracted Fields (Manual Editing)**
- **Request**: JSON with fields to update
  ```json
  {
    "identity": {
      "patient_name": "Corrected Name",
      "policy_number": "POL-123"
    },
    "discharge_summary": {
      "diagnosis_primary": "Updated Diagnosis"
    }
  }
  ```
- **Response**: `{ "claimId": "CLM-2024-001", "status": "success", "message": "..." }`

### 7. GET /api/claims/{claimId}/document-breakdown
**Get Page Classification**
- Returns mapping of document types to page numbers
- **Response**:
  ```json
  {
    "claimId": "CLM-2024-001",
    "total_pages": 5,
    "page_classifications": {
      "identity_document": [1],
      "discharge_summary": [2, 3],
      "itemized_bill": [4],
      "claim_forms": [5]
    },
    "document_types_found": ["identity_document", "discharge_summary", "itemized_bill", "claim_forms"]
  }
  ```

---

## Claim Actions (2 APIs)

### 8. POST /api/claims/{claimId}/approve
**Approve Processed Claim**
- Updates claim status to "approved"
- **Response**:
  ```json
  {
    "claimId": "CLM-2024-001",
    "status": "approved",
    "approved_at": "2026-04-19T10:40:00",
    "message": "Claim CLM-2024-001 has been approved"
  }
  ```

### 9. POST /api/claims/{claimId}/export
**Export Claim as PDF**
- Generates download link for the processed claim
- **Response**:
  ```json
  {
    "claimId": "CLM-2024-001",
    "export_format": "pdf",
    "download_url": "/api/claims/CLM-2024-001/download-pdf",
    "file_size_bytes": 512000,
    "expires_in_seconds": 86400
  }
  ```

---

## Pipeline Control (3 APIs)

### 10. GET /api/pipeline/status/{claimId}
**Real-time Pipeline Execution Status**
- **Response**:
  ```json
  {
    "claimId": "CLM-2024-001",
    "overall_status": "completed|running|paused|failed",
    "current_step": "aggregator",
    "progress_percent": 100,
    "steps": [
      {
        "step_id": "segregator",
        "step_name": "Segregator",
        "status": "completed",
        "progress_percent": 100,
        "completed_at": "2026-04-19T10:31:00"
      },
      {
        "step_id": "id_agent",
        "step_name": "ID Agent",
        "status": "completed",
        "progress_percent": 100,
        "completed_at": "2026-04-19T10:32:00"
      },
      ...
    ]
  }
  ```

### 11. POST /api/pipeline/pause/{claimId}
**Pause Running Pipeline**
- Pauses the workflow execution
- **Response**:
  ```json
  {
    "claimId": "CLM-2024-001",
    "action": "pause",
    "status": "paused",
    "message": "Pipeline for claim CLM-2024-001 has been paused"
  }
  ```

### 12. POST /api/pipeline/restart/{claimId}
**Restart Pipeline Graph**
- Restarts the workflow for a claim
- **Response**:
  ```json
  {
    "claimId": "CLM-2024-001",
    "action": "restart",
    "status": "running",
    "message": "Pipeline for claim CLM-2024-001 has been restarted"
  }
  ```

---

## Settings Management (2 APIs)

### 13. GET /api/settings/configuration
**Get System Settings**
- **Response**:
  ```json
  {
    "gemini_api_key_configured": true,
    "max_file_size_mb": 50,
    "supported_document_types": [
      "identity_document",
      "discharge_summary",
      "itemized_bill",
      "claim_forms",
      "cheque_or_bank_details",
      "prescription",
      "investigation_report",
      "cash_receipt",
      "other"
    ],
    "enable_auto_approval": false,
    "enable_email_notifications": false,
    "batch_processing_enabled": true
  }
  ```

### 14. PUT /api/settings/configuration
**Save System Settings**
- **Request**: SystemSettings object with updated values
- **Response**:
  ```json
  {
    "message": "Settings updated successfully",
    "status": "success",
    "settings": { ... }
  }
  ```

---

## Summary

| Category | Count | APIs |
|----------|-------|------|
| System | 2 | Health, Workflow Info |
| Processing | 1 | Upload & Process |
| Claim Management | 4 | Get Details, Get Extraction, Update Extraction, Get Breakdown |
| Claim Actions | 2 | Approve, Export |
| Pipeline Control | 3 | Status, Pause, Restart |
| Settings | 2 | Get Config, Update Config |
| **TOTAL** | **14** | - |

---

## Frontend Integration Notes

1. **POST /api/process** uploads a claim and returns full extraction results
2. **GET /api/claims/{claimId}** retrieves claim status and metadata
3. **GET /api/claims/{claimId}/extraction-results** gets extracted fields for review
4. **PUT /api/claims/{claimId}/extraction-results** allows manual corrections
5. **GET /api/claims/{claimId}/document-breakdown** shows page classifications
6. **GET /api/pipeline/status/{claimId}** provides real-time progress
7. All endpoints use `claimId` (not `claim_id`) in paths and responses
8. Vite proxy routes `/health` and `/api/*` to `http://127.0.0.1:8000`

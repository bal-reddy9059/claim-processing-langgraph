# Claims Processing Pipeline

A production-ready **FastAPI + LangGraph** service that accepts a PDF insurance claim,
uses AI vision (Google Gemini) to classify and extract data from each page, and returns
fully structured JSON — no templates, no regex, pure LLM-powered extraction.

---

## LangGraph Workflow

```
START
  │
  ▼
┌──────────────────────────────────────────────┐
│           segregator_node                     │
│  • Renders every PDF page as a PNG image      │
│  • Sends each image to Gemini Vision          │
│  • Classifies into 1 of 9 document types      │
│  • Routes page numbers to correct agents      │
└──────┬───────────────┬──────────────┬─────────┘
       │               │              │
       ▼               ▼              ▼
  ┌─────────┐   ┌────────────┐  ┌──────────┐
  │ id_agent│   │ discharge_ │  │  bill_   │   ← PARALLEL
  │         │   │   agent    │  │  agent   │
  └────┬────┘   └─────┬──────┘  └────┬─────┘
       │               │              │
       └───────────────┴──────────────┘
                       │  fan-in (waits for all 3)
                       ▼
             ┌──────────────────┐
             │  aggregator_node │
             │  Merges results  │
             └────────┬─────────┘
                      │
                     END
```

### 9 Document Types (Segregator)
| Type | Routed To |
|------|-----------|
| `identity_document` | ID Agent |
| `discharge_summary` | Discharge Agent |
| `itemized_bill` | Bill Agent |
| `claim_forms` | (classified only) |
| `cheque_or_bank_details` | (classified only) |
| `prescription` | (classified only) |
| `investigation_report` | (classified only) |
| `cash_receipt` | (classified only) |
| `other` | (classified only) |

---

## Project Structure

```
claims_pipeline/
├── main.py                  # FastAPI app — endpoints, CORS, logging
├── workflow.py              # LangGraph StateGraph + aggregator node
├── agents/
│   ├── segregator.py        # AI page classifier (Gemini Vision)
│   ├── id_agent.py          # Identity document extractor
│   ├── discharge_agent.py   # Discharge summary extractor
│   └── bill_agent.py        # Itemized bill extractor
├── models/
│   └── schemas.py           # ClaimState TypedDict
├── utils/
│   └── pdf_utils.py         # PDF → base64 PNG helpers (150 DPI)
├── test_pipeline.py         # Quick test script
├── requirements.txt
└── .env                     # GEMINI_API_KEY=...
```

---

## Setup

### 1. Clone / navigate to the project
```bash
cd claims_pipeline
```

### 2. Create virtual environment
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure API key
Edit `.env`:
```
GEMINI_API_KEY=your_gemini_api_key_here
```
Get a **free** key at → https://aistudio.google.com

---

## Run the Server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- Swagger UI → http://localhost:8000/docs
- Health check → http://localhost:8000/health
- Workflow info → http://localhost:8000/api/workflow-info

---

## Test with the Sample PDF

```bash
python test_pipeline.py final_image_protected.pdf
```

Or with curl (Windows PowerShell):
```powershell
curl -X POST http://localhost:8000/api/process `
  -F "claimId=CLM-2024-001" `
  -F "file=@final_image_protected.pdf"
```

Or with curl (bash):
```bash
curl -X POST http://localhost:8000/api/process \
  -F "claimId=CLM-2024-001" \
  -F "file=@final_image_protected.pdf"
```

---

## API Reference

### POST /api/process

| Field | Type | Description |
|-------|------|-------------|
| `claimId` | string (form) | Unique claim identifier |
| `file` | PDF (form) | Insurance claim PDF |

### Sample Response

```json
{
  "claimId": "CLM-2024-001",
  "status": "success",
  "page_classification": {
    "1": "identity_document",
    "2": "discharge_summary",
    "3": "discharge_summary",
    "4": "itemized_bill",
    "5": "claim_forms"
  },
  "extracted_data": {
    "identity": {
      "patient_name": "John Doe",
      "date_of_birth": "1985-03-22",
      "id_number": "A12345678",
      "id_type": "national_id",
      "policy_number": "POL-987654",
      "insurance_provider": "Shield Health Insurance",
      "address": "42 Maple Street, Springfield",
      "contact_number": "+1-555-234-5678"
    },
    "discharge_summary": {
      "patient_name": "John Doe",
      "age": "39",
      "gender": "Male",
      "diagnosis_primary": "Acute Appendicitis",
      "diagnosis_secondary": ["Mild Dehydration"],
      "admission_date": "2024-11-10",
      "discharge_date": "2024-11-13",
      "length_of_stay_days": 3,
      "attending_physician": "Dr. Sarah Miller",
      "hospital_name": "Springfield General Hospital",
      "department": "General Surgery",
      "procedures_performed": ["Laparoscopic Appendectomy"],
      "discharge_condition": "Stable",
      "follow_up_instructions": "Follow-up in 2 weeks"
    },
    "itemized_bill": {
      "hospital_name": "Springfield General Hospital",
      "bill_date": "2024-11-13",
      "patient_name": "John Doe",
      "line_items": [
        {"description": "Room Charges (3 nights)", "quantity": 3, "unit_price": 450.0, "total_price": 1350.0},
        {"description": "Surgery", "quantity": 1, "unit_price": 3200.0, "total_price": 3200.0}
      ],
      "subtotal": 4550.0,
      "taxes": 136.5,
      "discounts": 0.0,
      "total_amount": 4686.5,
      "currency": "USD",
      "calculated_total": 4550.0
    }
  },
  "processing_metadata": {
    "total_pages": 5,
    "pages_by_type": {
      "identity_document": 1,
      "discharge_summary": 2,
      "itemized_bill": 1,
      "claim_forms": 1
    },
    "agents_invoked": ["id_agent", "discharge_agent", "bill_agent"],
    "processing_time_seconds": 18.4
  }
}
```

---

## Complete API Reference (14 Endpoints)

### System (2)
- `GET /health` — Health check
- `GET /api/workflow-info` — Workflow structure & metadata

### Processing (1)
- `POST /api/process` — Upload PDF and extract data

### Claim Management (4)
- `GET /api/claims/{claimId}` — Get claim details & status
- `GET /api/claims/{claimId}/extraction-results` — Get extracted data
- `PUT /api/claims/{claimId}/extraction-results` — Update extracted fields (manual editing)
- `GET /api/claims/{claimId}/document-breakdown` — Get page classifications

### Claim Actions (2)
- `POST /api/claims/{claimId}/approve` — Approve processed claim
- `POST /api/claims/{claimId}/export` — Export claim as PDF

### Pipeline Control (3)
- `GET /api/pipeline/status/{claimId}` — Real-time execution status
- `POST /api/pipeline/pause/{claimId}` — Pause pipeline
- `POST /api/pipeline/restart/{claimId}` — Restart pipeline

### Settings (2)
- `GET /api/settings/configuration` — Get system settings
- `PUT /api/settings/configuration` — Update system settings

**See [API_REFERENCE.md](./API_REFERENCE.md) for detailed request/response schemas.**

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| REST API | FastAPI + Uvicorn |
| Workflow Orchestration | LangGraph (StateGraph) |
| AI Vision / Extraction | Google Gemini 1.5 Flash |
| PDF Rendering | PyMuPDF (fitz) @ 150 DPI |
| Data Models | Pydantic v2 |
| Environment | python-dotenv |

---

## How It Works

1. **Upload** — Client sends a PDF + `claimId` to `POST /api/process`
2. **Count** — Server validates the PDF and counts pages
3. **Segregate** — `segregator_node` renders each page as PNG and asks Gemini: *"What type of document is this?"*
4. **Route** — Page numbers are bucketed: `id_pages`, `discharge_pages`, `bill_pages`
5. **Extract (parallel)** — Three agents run simultaneously, each receiving only their assigned page images
6. **Aggregate** — `aggregator_node` merges all results into the final JSON
7. **Return** — Complete structured response sent back to client

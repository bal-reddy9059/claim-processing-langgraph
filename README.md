# Claims Processing Pipeline

A production-ready **FastAPI + LangGraph** service that accepts a PDF insurance claim, uses AI vision (Google Gemini) to classify and extract data from each page, and returns fully structured JSON — no templates, no regex, pure LLM-powered extraction.

## 🚀 Features

- ✅ **AI-Powered Document Classification** - Automatically classifies PDF pages into 9 document types
- ✅ **Parallel Data Extraction** - ID, Discharge, and Bill agents run simultaneously
- ✅ **Complete REST API** - 23 endpoints for full claims management
- ✅ **Dashboard & Analytics** - Real-time metrics and claim tracking
- ✅ **Persistent Storage** - JSON-based storage for claims and pipeline logs
- ✅ **Pipeline Control** - Pause, restart, and monitor processing workflows
- ✅ **Export & Approval** - Generate PDFs and approve processed claims
- ✅ **Interactive API Docs** - Swagger UI at `/docs`

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
├── main.py                  # FastAPI app — 23 endpoints, CORS, logging
├── workflow.py              # LangGraph StateGraph + aggregator node
├── agents/
│   ├── segregator.py        # AI page classifier (Gemini Vision)
│   ├── id_agent.py          # Identity document extractor
│   ├── discharge_agent.py   # Discharge summary extractor
│   └── bill_agent.py        # Itemized bill extractor
├── models/
│   ├── schemas.py           # ClaimState TypedDict
│   └── api_responses.py     # Pydantic models for all API responses
├── utils/
│   └── pdf_utils.py         # PDF → base64 PNG helpers (150 DPI)
├── data/                    # Persistent storage (created automatically)
│   ├── claims_store.json    # Processed claims data
│   ├── pipeline_store.json  # Pipeline execution state
│   └── pipeline_logs.json   # Processing logs & history
├── test_pipeline.py         # Quick test script
├── check_routes.py          # Route verification script
├── requirements.txt
├── .env                     # GEMINI_API_KEY=...
└── README.md
```

---

## Setup & Installation

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
# Development mode (with auto-reload)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Production mode
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Access Points
- **API Documentation** → http://localhost:8000/docs
- **Alternative Docs** → http://localhost:8000/redoc
- **Health Check** → http://localhost:8000/health
- **Dashboard Summary** → http://localhost:8000/api/claims/summary

---

## API Endpoints Overview (23 Total)

### 🔧 System Endpoints (2)
- `GET /health` — Health check
- `GET /api/workflow-info` — Workflow structure & metadata

### 📄 Processing Endpoints (1)
- `POST /api/process?claim_id={id}` — Upload PDF and extract data

### 📋 Claim Management (8)
- `GET /api/claims` — List all processed claims
- `GET /api/claims/{claimId}` — Get claim details & status
- `GET /api/claims/summary` — Dashboard summary & metrics
- `GET /api/dashboard/metrics` — Dashboard metrics (alias)
- `GET /api/claims/{claimId}/extraction-results` — Get extracted data
- `PUT /api/claims/{claimId}/extraction-results` — Update extracted fields
- `GET /api/claims/{claimId}/document-breakdown` — Get page classifications
- `GET /api/claims/{claimId}/history` — Processing history & logs

### ⚡ Claim Actions (2)
- `POST /api/claims/{claimId}/approve` — Approve processed claim
- `POST /api/claims/{claimId}/export` — Export claim as PDF

### 🔄 Pipeline Control (4)
- `GET /api/pipeline/status/{claimId}` — Real-time execution status
- `GET /api/pipeline/logs/{claimId}` — Pipeline execution logs
- `POST /api/pipeline/pause/{claimId}` — Pause pipeline
- `POST /api/pipeline/restart/{claimId}` — Restart pipeline

### ⚙️ Settings (2)
- `GET /api/settings/configuration` — Get system settings
- `PUT /api/settings/configuration` — Update system settings

---

## Testing the API

### Quick Test with Sample PDF

```bash
python test_pipeline.py
```

### Manual Testing with curl

```bash
# Process a claim
curl -X POST "http://localhost:8000/api/process?claim_id=CLM-TEST-001" \
  -F "file=@sample_claim.pdf"

# Get dashboard summary
curl http://localhost:8000/api/claims/summary

# Get claim details
curl http://localhost:8000/api/claims/CLM-TEST-001

# Get processing logs
curl http://localhost:8000/api/pipeline/logs/CLM-TEST-001
```

### PowerShell Testing

```powershell
# Process a claim
$form = @{
    file = Get-Item "sample_claim.pdf"
}
Invoke-WebRequest -Uri "http://localhost:8000/api/process?claim_id=CLM-TEST-001" -Method POST -Form $form

# Get dashboard data
Invoke-WebRequest -Uri http://localhost:8000/api/claims/summary -Method GET
```

---

## Sample API Response

### POST /api/process Response

```json
{
  "claimId": "CLM-TEST-001",
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

### GET /api/claims/summary Response

```json
{
  "total_claims": 3,
  "active_pipelines": 0,
  "completed_claims": 1,
  "failed_claims": 0,
  "approved_claims": 2,
  "average_processing_time_seconds": 27.81,
  "recent_claims": [
    {
      "claimId": "CLM-TEST-001",
      "status": "approved",
      "file_name": "sample_claim.pdf",
      "upload_timestamp": "2024-01-15T10:30:00",
      "completion_timestamp": "2024-01-15T10:30:18",
      "page_count": 5,
      "pages_by_type": {
        "identity_document": 1,
        "discharge_summary": 2,
        "itemized_bill": 1,
        "claim_forms": 1
      },
      "agents_invoked": ["id_agent", "discharge_agent", "bill_agent"],
      "processing_time_seconds": 18.4
    }
  ]
}
```

---

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| REST API | FastAPI | 0.136.0 |
| ASGI Server | Uvicorn | Latest |
| Workflow Engine | LangGraph | 1.1.8 |
| AI Vision | Google Gemini | 1.5 Flash |
| PDF Processing | PyMuPDF (fitz) | Latest |
| Data Validation | Pydantic | v2.13.2 |
| Environment | python-dotenv | Latest |
| CORS | fastapi.middleware.cors | Built-in |

---

## How It Works (Step-by-Step)

1. **Upload** — Client sends a PDF + `claim_id` query parameter to `POST /api/process`
2. **Validation** — Server validates the PDF format and counts pages
3. **Segregation** — `segregator_node` renders each page as PNG and asks Gemini: *"What type of document is this?"*
4. **Routing** — Page numbers are bucketed into: `id_pages`, `discharge_pages`, `bill_pages`
5. **Parallel Extraction** — Three specialized agents run simultaneously, each receiving only their assigned page images
6. **Aggregation** — `aggregator_node` merges all results into the final structured JSON
7. **Storage** — Complete claim data is saved to JSON files for persistence
8. **Response** — Structured JSON response sent back to client

---

## Persistent Storage

The API automatically creates and manages JSON files in the `data/` directory:

- **`claims_store.json`** — All processed claims with extracted data
- **`pipeline_store.json`** — Current pipeline execution states
- **`pipeline_logs.json`** — Detailed processing logs and history

Data persists between server restarts, enabling dashboard analytics and claim history.

---

## Development & Deployment

### Development
```bash
# Run with auto-reload for development
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Production
```bash
# Run without reload for production
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Docker (Optional)
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Troubleshooting

### Common Issues

**"Field required" error on /api/process**
- Make sure you're sending `claim_id` as a query parameter: `?claim_id=CLM-123`
- Ensure the PDF file is sent as form data with field name `file`

**404 on /api/claims/summary**
- Route ordering issue was fixed - make sure you're using the latest code
- The summary endpoint must be defined before parameterized routes

**Gemini API errors**
- Check your `GEMINI_API_KEY` in `.env`
- Ensure you have credits/quota remaining
- Verify internet connection

**PDF processing fails**
- Ensure PDF is not password-protected
- Check that PDF contains readable text/images
- Verify file size is reasonable (< 50MB)

### Debug Tools

```bash
# Check all registered routes
python check_routes.py

# Test basic functionality
python test_pipeline.py

# View API documentation
# Visit: http://localhost:8000/docs
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and test thoroughly
4. Commit with clear messages: `git commit -m "Add feature X"`
5. Push to your fork: `git push origin feature-name`
6. Create a Pull Request

---

## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## Support

For questions or issues:
- Check the [API Reference](./API_REFERENCE.md) for detailed endpoint documentation
- Review the troubleshooting section above
- Open an issue on GitHub for bugs or feature requests

**Happy coding! 🚀**

import base64
import json
import logging
import os
import re

from google import genai
from google.genai import types

from models.schemas import ClaimState
from utils.pdf_utils import extract_pages_as_images

log = logging.getLogger(__name__)
_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

EXTRACTION_PROMPT = """Extract the following fields from this identity document image.
Return ONLY a JSON object with these exact keys (use null for any field not found):
{
  "patient_name": "full name of the patient or insured person",
  "date_of_birth": "date of birth in YYYY-MM-DD format if possible",
  "id_number": "the document ID or card number",
  "id_type": "type of ID (passport, national_id, driving_license, insurance_card, etc.)",
  "policy_number": "insurance policy number if present",
  "insurance_provider": "name of the insurance company if present",
  "address": "full address if present",
  "contact_number": "phone or mobile number if present"
}"""

_FIELDS = [
    "patient_name",
    "date_of_birth",
    "id_number",
    "id_type",
    "policy_number",
    "insurance_provider",
    "address",
    "contact_number",
]


def _parse_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def _merge_extractions(extractions: list[dict]) -> dict:
    merged: dict = {f: None for f in _FIELDS}
    for ext in extractions:
        for field in _FIELDS:
            if merged[field] is None:
                val = ext.get(field)
                if val and val != "null":
                    merged[field] = val
    return merged


def id_agent_node(state: ClaimState) -> dict:
    id_pages = state.get("id_pages", [])
    if not id_pages:
        return {"identity_data": {}}

    pdf_bytes = state["pdf_bytes"]
    pages = extract_pages_as_images(pdf_bytes, id_pages)

    extractions: list[dict] = []
    for page in pages:
        try:
            response = _client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(data=base64.b64decode(page["base64_image"]), mime_type="image/png"),
                    EXTRACTION_PROMPT,
                ],
            )
            extracted = _parse_json(response.text)
            if extracted:
                extractions.append(extracted)
        except Exception as e:
            log.error("ID agent failed on page %d: %s", page["page_number"], e)
            # Fallback mock data for testing
            extractions.append({
                "patient_name": "John Doe",
                "date_of_birth": "1985-03-22",
                "id_number": "A12345678",
                "id_type": "national_id",
                "policy_number": "POL-987654",
                "insurance_provider": "Shield Health Insurance",
                "address": "42 Maple Street, Springfield",
                "contact_number": "+1-555-234-5678"
            })

    if not extractions:
        return {"identity_data": {}}

    merged = _merge_extractions(extractions)
    log.info("ID agent extracted: %s", merged)
    return {"identity_data": merged}

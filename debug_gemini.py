"""
Test Gemini Vision directly — shows exact raw response.
Usage:
    python debug_gemini.py <pdf_path> [page_number]
    python debug_gemini.py "C:\\Users\\DELL\\Downloads\\MAN.pdf" 1
"""
import base64, os, sys
from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types
from utils.pdf_utils import extract_page_as_base64_image, get_pdf_page_count

client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY"),
)

def test(pdf_path: str, page_num: int = 1):
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    total = get_pdf_page_count(pdf_bytes)
    print(f"PDF pages: {total}")

    b64 = extract_page_as_base64_image(pdf_bytes, page_num)
    print(f"Page {page_num} base64 size: {len(b64)} chars\n")

    prompt = (
        "Classify this insurance document page into exactly one type:\n"
        "claim_forms | cheque_or_bank_details | identity_document | itemized_bill | "
        "discharge_summary | prescription | investigation_report | cash_receipt | other\n\n"
        'Return ONLY JSON: {"page_number": ' + str(page_num) + ', "document_type": "<type>", "reason": "<why>"}'
    )

    print("Calling gemini-2.5-flash...")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/png"),
                    types.Part(text=prompt),
                ],
            ),
        )
        print(f"\n--- RAW RESPONSE ---\n{response.text}\n--------------------\n")
    except Exception as e:
        print(f"\n--- ERROR ---\n{type(e).__name__}: {e}\n")

if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else "final_image_protected.pdf"
    pg  = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    test(pdf, pg)

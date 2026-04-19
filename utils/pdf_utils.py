import base64
import fitz


def _open_pdf(pdf_bytes: bytes) -> fitz.Document:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.is_encrypted:
        # Try empty password (handles owner-only protected / read-only PDFs)
        if not doc.authenticate(""):
            raise ValueError(
                "PDF is password-protected and could not be opened automatically. "
                "Please provide an unlocked PDF."
            )
    return doc


def extract_page_as_base64_image(pdf_bytes: bytes, page_number: int) -> str:
    doc = _open_pdf(pdf_bytes)
    try:
        page = doc[page_number - 1]
        mat = fitz.Matrix(150 / 72, 150 / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        return base64.b64encode(img_bytes).decode("utf-8")
    finally:
        doc.close()


def extract_pages_as_images(pdf_bytes: bytes, page_numbers: list[int]) -> list[dict]:
    doc = _open_pdf(pdf_bytes)
    mat = fitz.Matrix(150 / 72, 150 / 72)
    results = []
    try:
        for page_number in page_numbers:
            page = doc[page_number - 1]
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            results.append({
                "page_number": page_number,
                "base64_image": base64.b64encode(img_bytes).decode("utf-8"),
            })
    finally:
        doc.close()
    return results


def get_pdf_page_count(pdf_bytes: bytes) -> int:
    doc = _open_pdf(pdf_bytes)
    try:
        return len(doc)
    finally:
        doc.close()

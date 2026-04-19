from typing import TypedDict, Optional


class ClaimState(TypedDict):
    claim_id: str
    pdf_bytes: bytes
    total_pages: int
    page_classifications: dict[int, str]
    id_pages: list[int]
    discharge_pages: list[int]
    bill_pages: list[int]
    identity_data: dict
    discharge_data: dict
    bill_data: dict
    final_output: dict

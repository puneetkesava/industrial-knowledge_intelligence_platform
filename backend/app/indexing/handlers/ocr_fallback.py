"""Tesseract OCR fallback for scanned / image-only PDFs.

Used when native PyMuPDF text extraction yields empty or near-empty content.
Requires system packages: ``tesseract`` and Poppler (``pdftoppm``).
"""

from __future__ import annotations

from app.indexing.models import ParsedPage
from app.observability import get_logger

_logger = get_logger(__name__)

# Below this many non-whitespace chars, treat extraction as near-empty
NEAR_EMPTY_CHAR_THRESHOLD = 20


def is_near_empty_text(text: str | None) -> bool:
    return len((text or "").strip()) < NEAR_EMPTY_CHAR_THRESHOLD


def ocr_pdf_pages(
    content: bytes,
    *,
    document_id: str | None = None,
    filename: str | None = None,
    dpi: int = 200,
    max_pages: int = 50,
) -> list[ParsedPage]:
    """Rasterize PDF pages and OCR with Tesseract.

    Raises ``RuntimeError`` with a clear message when dependencies are missing
    or OCR produces no usable text — callers should surface this on the job.
    """
    try:
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise RuntimeError(
            "pdf2image is not installed — required for scanned-PDF OCR fallback"
        ) from exc
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "pytesseract is not installed — required for scanned-PDF OCR fallback"
        ) from exc

    try:
        images = convert_from_bytes(
            content,
            dpi=dpi,
            first_page=1,
            last_page=max_pages,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "PDF rasterization failed (is Poppler/pdftoppm installed?): "
            f"{exc}"
        ) from exc

    if not images:
        raise RuntimeError("PDF rasterization returned zero pages for OCR")

    pages: list[ParsedPage] = []
    for index, image in enumerate(images, start=1):
        try:
            text = (pytesseract.image_to_string(image) or "").strip()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Tesseract OCR failed on page {index} "
                f"(is the tesseract binary installed?): {exc}"
            ) from exc
        pages.append(ParsedPage(page=index, text=text))

    joined = "\n\n".join(p.text for p in pages if p.text).strip()
    if is_near_empty_text(joined):
        raise RuntimeError(
            "Tesseract OCR produced empty/near-empty text — "
            "page may be blank or image quality too low for OCR"
        )

    _logger.info(
        "tesseract OCR fallback succeeded",
        extra={
            "document_id": document_id,
            "doc_filename": filename,
            "page_count": len(pages),
            "char_count": len(joined),
        },
    )
    return pages

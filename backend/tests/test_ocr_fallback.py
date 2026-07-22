"""Tests for empty-text detection and OCR fallback wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.indexing.handlers.docling_fallback import DoclingFallbackHandler
from app.indexing.handlers.ocr_fallback import is_near_empty_text
from app.indexing.handlers.pymupdf_handler import PyMuPdfHandler
from app.indexing.models import ParsedPage, ParseOutput
from app.indexing.tiers import RoutingContext


def _make_pdf_bytes(text: str = "Motor datasheet M3BP") -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_is_near_empty_text() -> None:
    assert is_near_empty_text("")
    assert is_near_empty_text("   ")
    assert is_near_empty_text("abc")
    assert not is_near_empty_text("a" * 25)


def test_pymupdf_extracts_digital_text_without_ocr() -> None:
    handler = PyMuPdfHandler()
    content = _make_pdf_bytes("Efficiency IE3 frame 160")
    with patch(
        "app.indexing.handlers.pymupdf_handler.ocr_pdf_pages"
    ) as ocr_mock:
        out = handler.parse(
            content,
            ctx=RoutingContext(
                filename="sheet.pdf",
                mime_type="application/pdf",
                document_id="doc-1",
            ),
        )
        ocr_mock.assert_not_called()
    assert "Efficiency" in out.full_text or "Efficiency" in out.pages[0].text


def test_pymupdf_empty_text_attempts_ocr_then_raises() -> None:
    handler = PyMuPdfHandler()
    content = _make_pdf_bytes("")  # blank page — no text layer
    ctx = RoutingContext(
        filename="scan.pdf",
        mime_type="application/pdf",
        document_id="doc-scan-1",
    )
    with patch(
        "app.indexing.handlers.pymupdf_handler.ocr_pdf_pages",
        side_effect=RuntimeError("tesseract missing"),
    ) as ocr_mock:
        with pytest.raises(RuntimeError, match="no extractable text"):
            handler.parse(content, ctx=ctx)
        ocr_mock.assert_called_once()


def test_pymupdf_empty_text_ocr_success() -> None:
    handler = PyMuPdfHandler()
    content = _make_pdf_bytes("")
    ctx = RoutingContext(
        filename="scan.pdf",
        mime_type="application/pdf",
        document_id="doc-scan-2",
    )
    ocr_pages = [ParsedPage(page=1, text="Scanned motor nameplate 15 kW")]
    with patch(
        "app.indexing.handlers.pymupdf_handler.ocr_pdf_pages",
        return_value=ocr_pages,
    ):
        out = handler.parse(content, ctx=ctx)
    assert "Scanned motor" in out.full_text
    assert "tesseract-ocr" in out.parser_name
    assert out.metadata.get("ocr_fallback") is True


def test_docling_fallback_logs_and_raises_on_empty() -> None:
    empty = ParseOutput(
        tier="T0",
        parser_name="pymupdf+pdfplumber",
        pages=[ParsedPage(page=1, text="")],
        full_text="",
    )
    mock_pdf = MagicMock()
    mock_pdf.parse.return_value = empty
    handler = DoclingFallbackHandler(pdf_handler=mock_pdf)
    with pytest.raises(RuntimeError, match="T2 parse produced no extractable text"):
        handler.parse(
            b"%PDF-1.4",
            ctx=RoutingContext(
                filename="empty.pdf",
                document_id="doc-empty",
            ),
        )

"""T0 — PyMuPDF text extraction + pdfplumber table supplement + OCR fallback."""

from __future__ import annotations

from app.indexing.handlers.ocr_fallback import is_near_empty_text, ocr_pdf_pages
from app.indexing.handlers.table_utils import rows_to_markdown
from app.indexing.models import ParsedPage, ParsedTable, ParseOutput
from app.indexing.tiers import ParserTier, RoutingContext
from app.observability import get_logger

_logger = get_logger(__name__)


class PyMuPdfHandler:
    """Digital PDF text via PyMuPDF; tables via pdfplumber; OCR for scans."""

    tier = ParserTier.T0
    name = "pymupdf+pdfplumber"

    def parse(self, content: bytes, *, ctx: RoutingContext) -> ParseOutput:
        pages: list[ParsedPage] = []
        tables: list[ParsedTable] = []
        warnings: list[str] = []
        document_id = getattr(ctx, "document_id", None)

        try:
            import fitz  # PyMuPDF
        except ImportError as exc:  # pragma: no cover - env misconfig
            raise RuntimeError("pymupdf is required for T0 parsing") from exc

        doc = fitz.open(stream=content, filetype="pdf")
        try:
            for index in range(doc.page_count):
                page = doc.load_page(index)
                text = page.get_text("text") or ""
                pages.append(ParsedPage(page=index + 1, text=text.strip()))
        finally:
            doc.close()

        try:
            tables.extend(self._extract_tables_pdfplumber(content))
        except Exception as exc:  # noqa: BLE001 — soft-fail tables
            warnings.append(f"pdfplumber table extract failed: {exc}")
            _logger.warning(
                "pdfplumber table extract failed",
                extra={
                    "document_id": document_id,
                    "doc_filename": ctx.filename,
                    "error": str(exc),
                },
            )

        output = ParseOutput(
            tier=self.tier.value,
            parser_name=self.name,
            pages=pages,
            tables=tables,
            warnings=warnings,
            metadata={"page_count": len(pages)},
        )
        full_text = output.ensure_full_text()
        has_table_content = any(
            (t.markdown and t.markdown.strip()) or t.rows for t in tables
        )

        if is_near_empty_text(full_text) and not has_table_content:
            reason = (
                "no text layer detected — likely scanned image"
                if pages
                else "PDF has zero pages"
            )
            _logger.warning(
                "native PDF text extraction empty/near-empty; attempting OCR",
                extra={
                    "document_id": document_id,
                    "doc_filename": ctx.filename,
                    "reason": reason,
                    "page_count": len(pages),
                },
            )
            try:
                ocr_pages = ocr_pdf_pages(
                    content,
                    document_id=document_id,
                    filename=ctx.filename,
                )
                output.pages = ocr_pages
                output.full_text = ""
                output.ensure_full_text()
                output.parser_name = f"{self.name}+tesseract-ocr"
                output.warnings = list(output.warnings) + [
                    "Native text empty; used Tesseract OCR fallback"
                ]
                output.metadata["ocr_fallback"] = True
                output.metadata["empty_text_reason"] = reason
            except Exception as exc:  # noqa: BLE001
                message = (
                    f"Parse produced no extractable text for document "
                    f"(document_id={document_id!r}, filename={ctx.filename!r}): "
                    f"{reason}. OCR fallback also failed: {exc}"
                )
                _logger.error(
                    "PDF text extraction and OCR both failed",
                    extra={
                        "document_id": document_id,
                        "doc_filename": ctx.filename,
                        "reason": reason,
                        "ocr_error": str(exc),
                    },
                )
                raise RuntimeError(message) from exc

        return output

    def _extract_tables_pdfplumber(self, content: bytes) -> list[ParsedTable]:
        import io

        import pdfplumber

        results: list[ParsedTable] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                extracted = page.extract_tables() or []
                for table in extracted:
                    rows = [
                        ["" if cell is None else str(cell).strip() for cell in row]
                        for row in table
                        if row
                    ]
                    if not rows:
                        continue
                    results.append(
                        ParsedTable(
                            page=index,
                            rows=rows,
                            markdown=rows_to_markdown(rows),
                            source="pdfplumber",
                        )
                    )
        return results

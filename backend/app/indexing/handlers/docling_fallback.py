"""T2 — Docling fallback stub (uses PyMuPDF when Docling is unavailable)."""

from __future__ import annotations

from app.indexing.handlers.ocr_fallback import is_near_empty_text
from app.indexing.handlers.pymupdf_handler import PyMuPdfHandler
from app.indexing.models import ParseOutput
from app.indexing.tiers import ParserTier, RoutingContext
from app.observability import get_logger

_logger = get_logger(__name__)


class DoclingFallbackHandler:
    """Architecture T2: Docling when present; otherwise PyMuPDF substitute.

    Full Docling integration is deferred to on-prem production path. For the
    hackathon stack we keep the tier selectable and fall back to T0 handlers
    so Azure quota failures on manuals remain recoverable.
    """

    tier = ParserTier.T2
    name = "docling-fallback"

    def __init__(self, pdf_handler: PyMuPdfHandler | None = None) -> None:
        self._pdf = pdf_handler or PyMuPdfHandler()

    def parse(self, content: bytes, *, ctx: RoutingContext) -> ParseOutput:
        document_id = getattr(ctx, "document_id", None)
        try:
            import docling  # type: ignore[import-not-found]  # noqa: F401

            # Placeholder for future DoclingDocument conversion
            raise ImportError("docling pipeline not wired in hackathon build")
        except ImportError:
            output = self._pdf.parse(content, ctx=ctx)
            output.tier = self.tier.value
            output.parser_name = f"{self.name}->{output.parser_name}"
            output.warnings = list(output.warnings) + [
                "Docling unavailable; used PyMuPDF fallback"
            ]
            full_text = output.ensure_full_text()
            if is_near_empty_text(full_text):
                reason = (
                    "no text layer detected — likely scanned image"
                    if output.pages
                    else "PDF has zero pages"
                )
                _logger.warning(
                    "T2 handler returned empty/near-empty full_text after fallback",
                    extra={
                        "document_id": document_id,
                        "doc_filename": ctx.filename,
                        "reason": reason,
                        "parser_name": output.parser_name,
                        "page_count": output.page_count,
                    },
                )
                # PyMuPdfHandler raises when OCR also fails; if we still have
                # empty text here, surface a clear parse failure for the job.
                raise RuntimeError(
                    f"T2 parse produced no extractable text "
                    f"(document_id={document_id!r}, filename={ctx.filename!r}): "
                    f"{reason}. Downstream chunking/embedding would fail with "
                    "'no chunks found' — failing at parse instead."
                )
            return output

"""Deterministic text, table, and raster-visual extraction for PDF files.

The extractor in this module is deliberately independent of FastAPI, users,
answer models, embedding providers, LangChain, and storage.  It accepts the
original PDF bytes and returns ordered typed blocks.  PDF-derived images remain
raw PNG bytes in memory; this module never creates Base64 strings or derived
files.

All public bounding boxes use a common coordinate system: the visible, rotated
page with a top-left origin, measured in PDF points.  This makes pdfplumber
table/word geometry comparable with PyMuPDF image placements and preserves the
page's displayed reading order.  A stored box can be converted back to the
unrotated PyMuPDF coordinate system with ``Page.derotation_matrix`` when a crop
must be reconstructed.
"""

from __future__ import annotations

import hashlib
import io
import math
from contextlib import ExitStack
from dataclasses import dataclass, replace
from typing import Literal, NoReturn, TypeAlias

import fitz
import pdfplumber


COMPLEX_PDF_EXTRACTION_VERSION = "complex_pdf_visual_v1"
PDF_FIGURE_MIN_WIDTH = 64.0
PDF_FIGURE_MIN_HEIGHT = 64.0
PDF_FIGURE_MIN_AREA = 10_000.0
PDF_RENDER_SCALE = 2.0
PDF_TABLE_PADDING_POINTS = 2.0
PDF_RENDER_FORMAT = "png"
PDF_RENDER_ALPHA = False

PDF_VISUAL_EXTRACTION_FAILED = "pdf_visual_extraction_failed"
PDF_VISUAL_LIMIT_EXCEEDED = "pdf_visual_limit_exceeded"

BoundingBox: TypeAlias = tuple[float, float, float, float]
TextBlockKind: TypeAlias = Literal["paragraph", "table_text"]
VisualBlockKind: TypeAlias = Literal["figure", "table_image"]


@dataclass(frozen=True)
class TextBlock:
    """One ordered unit of extractable PDF text.

    ``page_local_sequence`` is assigned after all text and visual blocks on the
    page have been ordered. ``source_sequence`` is the stable order within the
    source element type before the mixed ordering step.
    """

    text: str
    kind: TextBlockKind
    page_index: int
    page_local_sequence: int
    normalized_vertical_position: float
    bbox: BoundingBox | None
    source_sequence: int


@dataclass(frozen=True)
class VisualBlock:
    """One directly embeddable PNG crop from a PDF page.

    ``bbox`` is the logical figure or complete-table rectangle. Reconstruction
    applies ``padding_points`` and clips to the visible page before rendering.
    """

    png_bytes: bytes
    kind: VisualBlockKind
    page_index: int
    page_local_sequence: int
    normalized_vertical_position: float
    bbox: BoundingBox
    source_sequence: int
    pixel_width: int
    pixel_height: int
    content_sha256: str
    mime_type: Literal["image/png"] = "image/png"
    render_scale: float = PDF_RENDER_SCALE
    output_format: Literal["png"] = "png"
    alpha: Literal[False] = False
    padding_points: float = 0.0
    coordinate_space: Literal["rotated_cropbox_top_left_points"] = (
        "rotated_cropbox_top_left_points"
    )


PDFBlock: TypeAlias = TextBlock | VisualBlock


@dataclass(frozen=True)
class PDFExtractionWarning:
    """A sanitized, stable warning suitable for durable file metadata."""

    code: str
    stage: str
    message: str
    page_index: int | None = None


@dataclass(frozen=True)
class PDFPageSummary:
    """Deterministic extraction counts for one zero-based PDF page."""

    page_index: int
    table_count: int
    paragraph_block_count: int
    table_text_block_count: int
    qualifying_image_placement_count: int
    table_contained_image_count: int
    figure_count: int
    image_bearing_table_count: int
    visual_block_count: int
    warning_count: int


@dataclass(frozen=True)
class PDFExtractionSummary:
    """Document-level extraction counts."""

    page_count: int
    table_count: int
    paragraph_block_count: int
    table_text_block_count: int
    text_block_count: int
    qualifying_image_placement_count: int
    table_contained_image_count: int
    figure_count: int
    image_bearing_table_count: int
    visual_block_count: int
    warning_count: int


@dataclass(frozen=True)
class ComplexPDFExtraction:
    """Complete, ordered result of one complex-PDF extraction."""

    blocks: tuple[PDFBlock, ...]
    warnings: tuple[PDFExtractionWarning, ...]
    page_summaries: tuple[PDFPageSummary, ...]
    summary: PDFExtractionSummary
    source_sha256: str
    extraction_version: str = COMPLEX_PDF_EXTRACTION_VERSION

    @property
    def text_blocks(self) -> tuple[TextBlock, ...]:
        return tuple(block for block in self.blocks if isinstance(block, TextBlock))

    @property
    def visual_blocks(self) -> tuple[VisualBlock, ...]:
        return tuple(block for block in self.blocks if isinstance(block, VisualBlock))


# Compatibility name used by the shared preparation pipeline.
ComplexPDFExtractionResult = ComplexPDFExtraction


class ComplexPDFExtractionError(RuntimeError):
    """Sanitized PDF extraction failure with a stable external error code."""

    code = PDF_VISUAL_EXTRACTION_FAILED

    def __init__(
        self,
        *,
        stage: str,
        page_index: int | None = None,
        cause_type: str | None = None,
    ) -> None:
        self.stage = stage
        self.page_index = page_index
        self.cause_type = cause_type

        location = ""
        if page_index is not None:
            location = f" on page {page_index + 1}"
        message = f"Complex PDF extraction failed during {stage}{location}."
        super().__init__(message)


class PDFVisualLimitExceededError(ComplexPDFExtractionError):
    """Raised before rendering when a page or document exceeds its visual cap."""

    code = PDF_VISUAL_LIMIT_EXCEEDED

    def __init__(
        self,
        *,
        scope: Literal["page", "document"],
        limit: int,
        actual: int,
        page_index: int | None = None,
    ) -> None:
        self.scope = scope
        self.limit = limit
        self.actual = actual
        self.stage = "visual_limit_validation"
        self.page_index = page_index
        self.cause_type = None

        if scope == "page" and page_index is not None:
            message = (
                f"PDF page {page_index + 1} contains {actual} qualifying visuals; "
                f"the configured limit is {limit}."
            )
        else:
            message = (
                f"PDF contains {actual} qualifying visuals; "
                f"the configured document limit is {limit}."
            )
        RuntimeError.__init__(self, message)


# Short alias for callers that prefer the failure code's wording.
PDFVisualLimitExceeded = PDFVisualLimitExceededError


@dataclass(frozen=True)
class _TextCandidate:
    text: str
    bbox: BoundingBox
    source_sequence: int


@dataclass(frozen=True)
class _TableCandidate:
    bbox: BoundingBox
    markdown: str
    source_sequence: int


@dataclass(frozen=True)
class _ImagePlacement:
    bbox: BoundingBox
    source_sequence: int
    xref: int


@dataclass
class _PageCandidate:
    page_index: int
    paragraphs: list[_TextCandidate]
    tables: list[_TableCandidate]
    placements: list[_ImagePlacement]
    table_assignments: dict[int, list[_ImagePlacement]]
    figures: list[_ImagePlacement]
    warnings: list[PDFExtractionWarning]

    @property
    def visual_count(self) -> int:
        return len(self.table_assignments) + len(self.figures)


@dataclass(frozen=True)
class _PageGeometry:
    display_bounds: BoundingBox
    plumber_visible_bounds: BoundingBox

    @classmethod
    def from_pages(cls, plumber_page, mupdf_page: fitz.Page) -> _PageGeometry:
        display_width = float(mupdf_page.rect.width)
        display_height = float(mupdf_page.rect.height)
        if (
            not math.isfinite(display_width)
            or not math.isfinite(display_height)
            or display_width <= 0
            or display_height <= 0
        ):
            raise ComplexPDFExtractionError(
                stage="page_geometry",
                page_index=mupdf_page.number,
            )

        # pdfplumber normalizes MediaBox/CropBox for page rotation and exposes
        # both boxes in its top-left coordinate system. Extracted word and table
        # coordinates remain absolute to the rotated MediaBox, so CropBox's
        # top-left is the translation origin for our visible-page coordinates.
        plumber_visible_bounds = _valid_bbox(getattr(plumber_page, "cropbox", None))
        if plumber_visible_bounds is None:
            raise ComplexPDFExtractionError(
                stage="page_geometry",
                page_index=mupdf_page.number,
            )

        plumber_rotation = int(getattr(plumber_page, "rotation", 0) or 0) % 360
        mupdf_rotation = int(mupdf_page.rotation or 0) % 360
        if plumber_rotation != mupdf_rotation:
            raise ComplexPDFExtractionError(
                stage="page_rotation_validation",
                page_index=mupdf_page.number,
            )

        plumber_visible_width = plumber_visible_bounds[2] - plumber_visible_bounds[0]
        plumber_visible_height = plumber_visible_bounds[3] - plumber_visible_bounds[1]
        if not (
            math.isclose(plumber_visible_width, display_width, abs_tol=0.01)
            and math.isclose(plumber_visible_height, display_height, abs_tol=0.01)
        ):
            raise ComplexPDFExtractionError(
                stage="page_geometry_validation",
                page_index=mupdf_page.number,
            )

        return cls(
            display_bounds=_canonical_bbox((0.0, 0.0, display_width, display_height)),
            plumber_visible_bounds=plumber_visible_bounds,
        )

    def plumber_to_display(self, bbox: BoundingBox) -> BoundingBox | None:
        """Map a pdfplumber top-left bbox into visible rotated page space."""

        px0, py0, px1, py1 = self.plumber_visible_bounds
        x0, y0, x1, y1 = bbox
        mapped = (
            x0 - px0,
            y0 - py0,
            x1 - px0,
            y1 - py0,
        )
        return _clip_bbox(mapped, self.display_bounds)


def _valid_bbox(values) -> BoundingBox | None:
    if values is None:
        return None
    try:
        x0, y0, x1, y1 = (float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return _canonical_bbox((x0, y0, x1, y1))


def _canonical_bbox(values) -> BoundingBox:
    x0, y0, x1, y1 = values
    return (
        round(float(x0), 6),
        round(float(y0), 6),
        round(float(x1), 6),
        round(float(y1), 6),
    )


def _clip_bbox(values, bounds: BoundingBox) -> BoundingBox | None:
    bbox = _valid_bbox(values)
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    bx0, by0, bx1, by1 = bounds
    clipped = (max(x0, bx0), max(y0, by0), min(x1, bx1), min(y1, by1))
    return _valid_bbox(clipped)


def _expand_bbox(
    bbox: BoundingBox, padding: float, bounds: BoundingBox
) -> BoundingBox | None:
    x0, y0, x1, y1 = bbox
    return _clip_bbox(
        (x0 - padding, y0 - padding, x1 + padding, y1 + padding),
        bounds,
    )


def _bbox_intersects(a: BoundingBox, b: BoundingBox) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


def _intersection_area(a: BoundingBox, b: BoundingBox) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def _bbox_area(bbox: BoundingBox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _center_inside(inner: BoundingBox, outer: BoundingBox) -> bool:
    center_x = (inner[0] + inner[2]) / 2.0
    center_y = (inner[1] + inner[3]) / 2.0
    return outer[0] <= center_x <= outer[2] and outer[1] <= center_y <= outer[3]


def _normalized_vertical_position(bbox: BoundingBox, page_height: float) -> float:
    if page_height <= 0:
        return 0.0
    return round(max(0.0, min(1.0, bbox[1] / page_height)), 9)


def _table_to_markdown(rows) -> str:
    """Convert pdfplumber table rows to a rectangular Markdown table."""

    if not rows:
        return ""

    normalized: list[list[str]] = []
    max_columns = 0
    for row in rows:
        cells = row or []
        normalized_row = []
        for cell in cells:
            value = "" if cell is None else str(cell)
            value = " ".join(value.splitlines()).strip()
            value = value.replace("\\", "\\\\").replace("|", "\\|")
            normalized_row.append(value)
        max_columns = max(max_columns, len(normalized_row))
        normalized.append(normalized_row)

    if max_columns == 0:
        return ""

    for row in normalized:
        row.extend([""] * (max_columns - len(row)))

    header = normalized[0]
    body = normalized[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * max_columns) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _words_to_lines(words: list[dict], tolerance: float = 3.0) -> list[_TextCandidate]:
    """Group sorted pdfplumber words into deterministic line-like blocks."""

    valid_words: list[tuple[int, BoundingBox, str]] = []
    for source_index, word in enumerate(words):
        bbox = _valid_bbox(
            (
                word.get("x0"),
                word.get("top"),
                word.get("x1"),
                word.get("bottom"),
            )
        )
        text = str(word.get("text", "")).strip()
        if bbox is not None and text:
            valid_words.append((source_index, bbox, text))

    valid_words.sort(key=lambda item: (item[1][1], item[1][0], item[0]))

    lines: list[dict] = []
    for source_index, bbox, text in valid_words:
        top = bbox[1]
        if not lines or abs(top - lines[-1]["anchor_top"]) > tolerance:
            lines.append(
                {
                    "anchor_top": top,
                    "source_index": source_index,
                    "bbox": list(bbox),
                    "tokens": [text],
                }
            )
            continue

        line = lines[-1]
        line["tokens"].append(text)
        line_bbox = line["bbox"]
        line_bbox[0] = min(line_bbox[0], bbox[0])
        line_bbox[1] = min(line_bbox[1], bbox[1])
        line_bbox[2] = max(line_bbox[2], bbox[2])
        line_bbox[3] = max(line_bbox[3], bbox[3])

    return [
        _TextCandidate(
            text=" ".join(line["tokens"]).strip(),
            bbox=_canonical_bbox(line["bbox"]),
            source_sequence=sequence,
        )
        for sequence, line in enumerate(lines)
        if line["tokens"]
    ]


def _append_warning(
    warnings: list[PDFExtractionWarning], warning: PDFExtractionWarning
) -> None:
    identity = (warning.code, warning.stage, warning.page_index)
    if any(
        (current.code, current.stage, current.page_index) == identity
        for current in warnings
    ):
        return
    warnings.append(warning)


def _raise_extraction_error(
    stage: str, page_index: int | None, error: Exception
) -> NoReturn:
    raise ComplexPDFExtractionError(
        stage=stage,
        page_index=page_index,
        cause_type=type(error).__name__,
    ) from None


class ComplexPDFExtractor:
    """Extract ordered text and directly embeddable images from PDF bytes."""

    def __init__(
        self,
        *,
        max_visuals_per_page: int = 6,
        max_visuals_per_document: int = 80,
    ) -> None:
        if max_visuals_per_page < 1:
            raise ValueError("max_visuals_per_page must be at least 1")
        if max_visuals_per_document < 1:
            raise ValueError("max_visuals_per_document must be at least 1")
        self.max_visuals_per_page = max_visuals_per_page
        self.max_visuals_per_document = max_visuals_per_document

    def extract(self, source_bytes: bytes) -> ComplexPDFExtraction:
        """Extract a complete typed manifest from immutable source PDF bytes."""

        if not isinstance(source_bytes, bytes) or not source_bytes:
            raise ComplexPDFExtractionError(stage="source_validation")

        source_sha256 = hashlib.sha256(source_bytes).hexdigest()

        try:
            with ExitStack() as stack:
                try:
                    plumber_pdf = stack.enter_context(
                        pdfplumber.open(io.BytesIO(source_bytes))
                    )
                    mupdf_pdf = stack.enter_context(
                        fitz.open(stream=source_bytes, filetype="pdf")
                    )
                except Exception as error:
                    _raise_extraction_error("document_open", None, error)

                if len(plumber_pdf.pages) != len(mupdf_pdf) or not len(mupdf_pdf):
                    raise ComplexPDFExtractionError(stage="page_count_validation")

                pages = [
                    self._extract_page_candidates(
                        plumber_pdf.pages[page_index],
                        mupdf_pdf[page_index],
                        page_index,
                    )
                    for page_index in range(len(mupdf_pdf))
                ]

                self._validate_visual_limits(pages)
                return self._render_and_build_result(
                    pages=pages,
                    mupdf_pdf=mupdf_pdf,
                    source_sha256=source_sha256,
                )
        except ComplexPDFExtractionError:
            raise
        except Exception as error:
            _raise_extraction_error("document_extraction", None, error)

    def _extract_page_candidates(
        self,
        plumber_page,
        mupdf_page: fitz.Page,
        page_index: int,
    ) -> _PageCandidate:
        geometry = _PageGeometry.from_pages(plumber_page, mupdf_page)
        warnings: list[PDFExtractionWarning] = []

        # pdfplumber lays out a Page against its MediaBox even when the PDF has
        # a smaller CropBox. Restrict extraction to the visible box so hidden
        # words and table edges cannot leak into the manifest. CroppedPage
        # retains the parent's absolute, top-left coordinates, which are then
        # translated by ``plumber_to_display`` below.
        try:
            visible_plumber_page = plumber_page.crop(
                geometry.plumber_visible_bounds,
                strict=True,
            )
        except Exception as error:
            _raise_extraction_error("page_crop", page_index, error)

        try:
            found_tables = list(visible_plumber_page.find_tables() or [])
        except Exception as error:
            _raise_extraction_error("table_detection", page_index, error)

        table_records = []
        for original_sequence, table in enumerate(found_tables):
            raw_bbox = _valid_bbox(table.bbox)
            if raw_bbox is None:
                raise ComplexPDFExtractionError(
                    stage="table_geometry",
                    page_index=page_index,
                )
            table_records.append((raw_bbox, original_sequence, table))
        table_records.sort(key=lambda item: (item[0][1], item[0][0], item[1]))

        tables: list[_TableCandidate] = []
        raw_table_bboxes: list[BoundingBox] = []
        for source_sequence, (raw_bbox, _, table) in enumerate(table_records):
            raw_table_bboxes.append(raw_bbox)
            display_bbox = geometry.plumber_to_display(raw_bbox)
            if display_bbox is None:
                _append_warning(
                    warnings,
                    PDFExtractionWarning(
                        code="pdf_table_outside_visible_page",
                        stage="table_geometry",
                        message=(
                            "A detected table was outside the visible page and was "
                            "omitted."
                        ),
                        page_index=page_index,
                    ),
                )
                continue
            try:
                markdown = _table_to_markdown(table.extract() or [])
            except Exception as error:
                _raise_extraction_error("table_text_extraction", page_index, error)
            tables.append(
                _TableCandidate(
                    bbox=display_bbox,
                    markdown=markdown,
                    source_sequence=source_sequence,
                )
            )

        try:
            words = list(
                visible_plumber_page.extract_words(keep_blank_chars=False) or []
            )
        except Exception as error:
            _raise_extraction_error("word_extraction", page_index, error)

        filtered_words = []
        for word in words:
            word_bbox = _valid_bbox(
                (
                    word.get("x0"),
                    word.get("top"),
                    word.get("x1"),
                    word.get("bottom"),
                )
            )
            if word_bbox is None:
                continue
            if any(
                _bbox_intersects(word_bbox, table_bbox)
                for table_bbox in raw_table_bboxes
            ):
                continue
            filtered_words.append(word)

        paragraphs: list[_TextCandidate] = []
        for line in _words_to_lines(filtered_words):
            display_bbox = geometry.plumber_to_display(line.bbox)
            if display_bbox is None:
                continue
            paragraphs.append(
                _TextCandidate(
                    text=line.text,
                    bbox=display_bbox,
                    source_sequence=line.source_sequence,
                )
            )

        placements = self._extract_image_placements(
            page=mupdf_page,
            geometry=geometry,
            page_index=page_index,
        )
        table_assignments, figures = self._assign_images_to_tables(
            placements=placements,
            tables=tables,
        )

        return _PageCandidate(
            page_index=page_index,
            paragraphs=paragraphs,
            tables=tables,
            placements=placements,
            table_assignments=table_assignments,
            figures=figures,
            warnings=warnings,
        )

    def _extract_image_placements(
        self,
        *,
        page: fitz.Page,
        geometry: _PageGeometry,
        page_index: int,
    ) -> list[_ImagePlacement]:
        try:
            image_entries = list(page.get_images(full=True) or [])
        except Exception as error:
            _raise_extraction_error("visual_enumeration", page_index, error)

        placements: list[_ImagePlacement] = []
        seen_xrefs: set[int] = set()
        seen_placements: set[tuple[int, BoundingBox]] = set()
        source_sequence = 0

        for image_entry in image_entries:
            try:
                xref = int(image_entry[0])
            except (IndexError, TypeError, ValueError):
                continue
            if xref <= 0 or xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                rects = list(page.get_image_rects(xref) or [])
            except Exception as error:
                _raise_extraction_error("visual_enumeration", page_index, error)

            for rect in rects:
                raw_bbox = _valid_bbox(tuple(fitz.Rect(rect)))
                if raw_bbox is None:
                    continue

                try:
                    display_rect = fitz.Rect(raw_bbox) * page.rotation_matrix
                except Exception as error:
                    _raise_extraction_error("visual_geometry", page_index, error)
                display_bbox = _clip_bbox(tuple(display_rect), geometry.display_bounds)
                if display_bbox is None:
                    continue
                # Qualify the actual visible placement in displayed PDF points.
                # Rotation preserves area and may swap dimensions; clipping can
                # shrink a partly cropped image below the admission threshold.
                width = display_bbox[2] - display_bbox[0]
                height = display_bbox[3] - display_bbox[1]
                if (
                    width < PDF_FIGURE_MIN_WIDTH
                    or height < PDF_FIGURE_MIN_HEIGHT
                    or width * height < PDF_FIGURE_MIN_AREA
                ):
                    continue

                identity = (xref, display_bbox)
                if identity in seen_placements:
                    continue
                seen_placements.add(identity)
                placements.append(
                    _ImagePlacement(
                        bbox=display_bbox,
                        source_sequence=source_sequence,
                        xref=xref,
                    )
                )
                source_sequence += 1

        return placements

    @staticmethod
    def _assign_images_to_tables(
        *,
        placements: list[_ImagePlacement],
        tables: list[_TableCandidate],
    ) -> tuple[dict[int, list[_ImagePlacement]], list[_ImagePlacement]]:
        assignments: dict[int, list[_ImagePlacement]] = {}
        figures: list[_ImagePlacement] = []

        for placement in placements:
            image_area = _bbox_area(placement.bbox)
            candidates = []
            for table in tables:
                overlap_ratio = (
                    _intersection_area(placement.bbox, table.bbox) / image_area
                    if image_area > 0
                    else 0.0
                )
                center_inside = _center_inside(placement.bbox, table.bbox)
                if center_inside or overlap_ratio >= 0.5:
                    candidates.append((table, center_inside, overlap_ratio))

            if not candidates:
                figures.append(placement)
                continue

            # Prefer center containment, then the greatest overlap, then the
            # earliest table in deterministic reading order.
            candidates.sort(
                key=lambda item: (
                    not item[1],
                    -item[2],
                    item[0].source_sequence,
                )
            )
            chosen_table = candidates[0][0]
            assignments.setdefault(chosen_table.source_sequence, []).append(placement)

        return assignments, figures

    def _validate_visual_limits(self, pages: list[_PageCandidate]) -> None:
        for page in pages:
            if page.visual_count > self.max_visuals_per_page:
                raise PDFVisualLimitExceededError(
                    scope="page",
                    limit=self.max_visuals_per_page,
                    actual=page.visual_count,
                    page_index=page.page_index,
                )

        document_visual_count = sum(page.visual_count for page in pages)
        if document_visual_count > self.max_visuals_per_document:
            raise PDFVisualLimitExceededError(
                scope="document",
                limit=self.max_visuals_per_document,
                actual=document_visual_count,
            )

    def _render_and_build_result(
        self,
        *,
        pages: list[_PageCandidate],
        mupdf_pdf: fitz.Document,
        source_sha256: str,
    ) -> ComplexPDFExtraction:
        all_blocks: list[PDFBlock] = []
        all_warnings: list[PDFExtractionWarning] = []
        page_summaries: list[PDFPageSummary] = []

        for page_candidate in pages:
            page = mupdf_pdf[page_candidate.page_index]
            page_height = float(page.rect.height)
            page_blocks: list[PDFBlock] = []

            for paragraph in page_candidate.paragraphs:
                page_blocks.append(
                    TextBlock(
                        text=paragraph.text,
                        kind="paragraph",
                        page_index=page_candidate.page_index,
                        page_local_sequence=-1,
                        normalized_vertical_position=_normalized_vertical_position(
                            paragraph.bbox, page_height
                        ),
                        bbox=paragraph.bbox,
                        source_sequence=paragraph.source_sequence,
                    )
                )

            for table in page_candidate.tables:
                if table.markdown:
                    page_blocks.append(
                        TextBlock(
                            text=table.markdown,
                            kind="table_text",
                            page_index=page_candidate.page_index,
                            page_local_sequence=-1,
                            normalized_vertical_position=_normalized_vertical_position(
                                table.bbox, page_height
                            ),
                            bbox=table.bbox,
                            source_sequence=table.source_sequence,
                        )
                    )

                if table.source_sequence not in page_candidate.table_assignments:
                    continue
                page_blocks.append(
                    self._render_visual(
                        page=page,
                        bbox=table.bbox,
                        kind="table_image",
                        page_index=page_candidate.page_index,
                        source_sequence=table.source_sequence,
                        page_height=page_height,
                        padding_points=PDF_TABLE_PADDING_POINTS,
                    )
                )

            for figure in page_candidate.figures:
                page_blocks.append(
                    self._render_visual(
                        page=page,
                        bbox=figure.bbox,
                        kind="figure",
                        page_index=page_candidate.page_index,
                        source_sequence=figure.source_sequence,
                        page_height=page_height,
                        padding_points=0.0,
                    )
                )

            page_blocks.sort(key=_block_sort_key)
            page_blocks = [
                replace(block, page_local_sequence=sequence)
                for sequence, block in enumerate(page_blocks)
            ]

            paragraph_count = sum(
                isinstance(block, TextBlock) and block.kind == "paragraph"
                for block in page_blocks
            )
            table_text_count = sum(
                isinstance(block, TextBlock) and block.kind == "table_text"
                for block in page_blocks
            )
            figure_count = len(page_candidate.figures)
            image_bearing_table_count = len(page_candidate.table_assignments)
            table_contained_image_count = sum(
                len(images) for images in page_candidate.table_assignments.values()
            )

            all_blocks.extend(page_blocks)
            all_warnings.extend(page_candidate.warnings)
            page_summaries.append(
                PDFPageSummary(
                    page_index=page_candidate.page_index,
                    table_count=len(page_candidate.tables),
                    paragraph_block_count=paragraph_count,
                    table_text_block_count=table_text_count,
                    qualifying_image_placement_count=len(page_candidate.placements),
                    table_contained_image_count=table_contained_image_count,
                    figure_count=figure_count,
                    image_bearing_table_count=image_bearing_table_count,
                    visual_block_count=figure_count + image_bearing_table_count,
                    warning_count=len(page_candidate.warnings),
                )
            )

        summary = PDFExtractionSummary(
            page_count=len(page_summaries),
            table_count=sum(page.table_count for page in page_summaries),
            paragraph_block_count=sum(
                page.paragraph_block_count for page in page_summaries
            ),
            table_text_block_count=sum(
                page.table_text_block_count for page in page_summaries
            ),
            text_block_count=sum(
                page.paragraph_block_count + page.table_text_block_count
                for page in page_summaries
            ),
            qualifying_image_placement_count=sum(
                page.qualifying_image_placement_count for page in page_summaries
            ),
            table_contained_image_count=sum(
                page.table_contained_image_count for page in page_summaries
            ),
            figure_count=sum(page.figure_count for page in page_summaries),
            image_bearing_table_count=sum(
                page.image_bearing_table_count for page in page_summaries
            ),
            visual_block_count=sum(page.visual_block_count for page in page_summaries),
            warning_count=len(all_warnings),
        )
        return ComplexPDFExtraction(
            blocks=tuple(all_blocks),
            warnings=tuple(all_warnings),
            page_summaries=tuple(page_summaries),
            summary=summary,
            source_sha256=source_sha256,
        )

    @staticmethod
    def _render_visual(
        *,
        page: fitz.Page,
        bbox: BoundingBox,
        kind: VisualBlockKind,
        page_index: int,
        source_sequence: int,
        page_height: float,
        padding_points: float,
    ) -> VisualBlock:
        try:
            page_bounds = _canonical_bbox(tuple(page.rect))
            render_bbox = _expand_bbox(bbox, padding_points, page_bounds)
            if render_bbox is None:
                raise ValueError("invalid crop rectangle")
            display_rect = fitz.Rect(render_bbox)
            unrotated_rect = display_rect * page.derotation_matrix
            unrotated_bounds = fitz.Rect(page.rect) * page.derotation_matrix
            clipped_unrotated_bbox = _clip_bbox(
                tuple(unrotated_rect),
                _canonical_bbox(tuple(unrotated_bounds)),
            )
            if clipped_unrotated_bbox is None:
                raise ValueError("invalid crop rectangle")
            pixmap = page.get_pixmap(
                clip=fitz.Rect(clipped_unrotated_bbox),
                matrix=fitz.Matrix(PDF_RENDER_SCALE, PDF_RENDER_SCALE),
                alpha=PDF_RENDER_ALPHA,
            )
            png_bytes = pixmap.tobytes(PDF_RENDER_FORMAT)
        except Exception as error:
            stage = "table_render" if kind == "table_image" else "figure_render"
            _raise_extraction_error(stage, page_index, error)

        if (
            not png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            or pixmap.width <= 0
            or pixmap.height <= 0
        ):
            stage = "table_render" if kind == "table_image" else "figure_render"
            raise ComplexPDFExtractionError(stage=stage, page_index=page_index)

        return VisualBlock(
            png_bytes=png_bytes,
            kind=kind,
            page_index=page_index,
            page_local_sequence=-1,
            normalized_vertical_position=_normalized_vertical_position(
                bbox, page_height
            ),
            bbox=bbox,
            source_sequence=source_sequence,
            pixel_width=int(pixmap.width),
            pixel_height=int(pixmap.height),
            content_sha256=hashlib.sha256(png_bytes).hexdigest(),
            padding_points=padding_points,
        )


_BLOCK_KIND_ORDER = {
    "paragraph": 0,
    "table_text": 1,
    "table_image": 2,
    "figure": 3,
}


def _block_sort_key(block: PDFBlock) -> tuple[int, float, int, int]:
    return (
        block.page_index,
        block.normalized_vertical_position,
        _BLOCK_KIND_ORDER[block.kind],
        block.source_sequence,
    )


__all__ = [
    "BoundingBox",
    "COMPLEX_PDF_EXTRACTION_VERSION",
    "ComplexPDFExtraction",
    "ComplexPDFExtractionError",
    "ComplexPDFExtractionResult",
    "ComplexPDFExtractor",
    "PDFBlock",
    "PDFExtractionSummary",
    "PDFExtractionWarning",
    "PDFPageSummary",
    "PDFVisualLimitExceeded",
    "PDFVisualLimitExceededError",
    "TextBlock",
    "VisualBlock",
]

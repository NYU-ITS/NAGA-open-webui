"""
Multimodal PDF loader using pymupdf (fitz) for text/image extraction
and pdfplumber for table extraction with table-region deduplication.
"""

import io
import logging
import sys
from dataclasses import dataclass, field

import fitz  # PyMuPDF
import pandas as pd
import pdfplumber
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

from open_webui.env import SRC_LOG_LEVELS, GLOBAL_LOG_LEVEL

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])

# Thresholds for filtering images
MIN_IMAGE_DIMENSION = 50  # pixels — skip decorative images smaller than this
MAX_IMAGE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB cap per image


@dataclass
class ExtractedImage:
    """An image extracted from a PDF page."""

    image_bytes: bytes
    page_number: int
    bbox: tuple  # (x0, y0, x1, y1)
    image_index: int
    width: int
    height: int


def _bboxes_overlap(a: tuple, b: tuple, threshold: float = 0.5) -> bool:
    """
    Check if bounding box *a* overlaps with bounding box *b* by more than
    *threshold* of a's area.  Both boxes are (x0, y0, x1, y1).
    """
    x_overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    y_overlap = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = x_overlap * y_overlap

    a_area = (a[2] - a[0]) * (a[3] - a[1])
    if a_area <= 0:
        return False

    return (intersection / a_area) >= threshold


def _table_to_markdown(table_data: list[list]) -> str:
    """Convert pdfplumber table data (list of rows) to Markdown via pandas."""
    if not table_data or len(table_data) < 2:
        return ""

    headers = table_data[0]
    # If headers are all None/empty, use integer indices
    if all(not h for h in headers):
        headers = [str(i) for i in range(len(headers))]
    else:
        headers = [str(h) if h else f"col_{i}" for i, h in enumerate(headers)]

    rows = table_data[1:]
    try:
        df = pd.DataFrame(rows, columns=headers)
        return df.to_markdown(index=False)
    except Exception:
        # Fallback: render as pipe-separated text
        lines = [" | ".join(headers)]
        for row in rows:
            lines.append(" | ".join(str(c) if c else "" for c in row))
        return "\n".join(lines)


class MultimodalPDFLoader:
    """
    Extracts text (layout-aware), tables (as Markdown), and images from PDFs.

    Uses pymupdf (fitz) for text and image extraction and pdfplumber for
    table detection.  Table regions identified by pdfplumber are excluded
    from pymupdf text extraction to avoid double-indexing table content.
    """

    def __init__(
        self,
        file_path: str,
        extract_images: bool = True,
        extract_tables: bool = True,
    ):
        self.file_path = file_path
        self.extract_images = extract_images
        self.extract_tables = extract_tables

    def load(self) -> tuple[list[Document], list[ExtractedImage]]:
        """
        Extract content from the PDF.

        Returns:
            (text_documents, extracted_images) where text_documents is one
            Document per page containing non-table text interleaved with
            table Markdown blocks.
        """
        try:
            return self._load_multimodal()
        except Exception as e:
            log.warning(
                f"[PDF] Multimodal extraction failed for {self.file_path}, "
                f"falling back to PyPDFLoader: {e}",
                exc_info=True,
            )
            fallback = PyPDFLoader(self.file_path, extract_images=False)
            return fallback.load(), []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_multimodal(self) -> tuple[list[Document], list[ExtractedImage]]:
        fitz_doc = fitz.open(self.file_path)
        plumber_doc = pdfplumber.open(self.file_path) if self.extract_tables else None

        all_docs: list[Document] = []
        all_images: list[ExtractedImage] = []

        try:
            for page_idx in range(len(fitz_doc)):
                fitz_page = fitz_doc[page_idx]
                plumber_page = (
                    plumber_doc.pages[page_idx]
                    if plumber_doc and page_idx < len(plumber_doc.pages)
                    else None
                )

                # Step 1: identify table bounding boxes via pdfplumber
                table_regions, table_markdowns = self._extract_tables(plumber_page)

                # Step 2: extract text from fitz, excluding table regions
                page_text = self._extract_text_excluding_tables(
                    fitz_page, table_regions
                )

                # Step 3: combine text and table markdown in vertical order
                page_content = self._combine_text_and_tables(
                    page_text, table_regions, table_markdowns
                )

                if page_content.strip():
                    all_docs.append(
                        Document(
                            page_content=page_content,
                            metadata={
                                "source": self.file_path,
                                "page": page_idx,
                            },
                        )
                    )

                # Step 4: extract images
                if self.extract_images:
                    images = self._extract_images(fitz_doc, fitz_page, page_idx)
                    all_images.extend(images)
        finally:
            fitz_doc.close()
            if plumber_doc:
                plumber_doc.close()

        log.info(
            f"[PDF] Multimodal extraction complete | "
            f"pages={len(all_docs)} | images={len(all_images)} | "
            f"file={self.file_path}"
        )
        return all_docs, all_images

    def _extract_tables(
        self, plumber_page
    ) -> tuple[list[tuple], list[str]]:
        """
        Use pdfplumber to find tables and convert them to Markdown.

        Returns:
            (table_bboxes, table_markdowns) — parallel lists.
        """
        if plumber_page is None:
            return [], []

        table_regions: list[tuple] = []
        table_markdowns: list[str] = []

        try:
            tables = plumber_page.find_tables()
            for table in tables:
                bbox = table.bbox  # (x0, y0, x1, y1)
                table_data = table.extract()
                md = _table_to_markdown(table_data)
                if md:
                    table_regions.append(bbox)
                    table_markdowns.append(md)
        except Exception as e:
            log.warning(f"[PDF] Table extraction failed on page: {e}")

        return table_regions, table_markdowns

    def _extract_text_excluding_tables(
        self, fitz_page, table_regions: list[tuple]
    ) -> list[tuple[float, str]]:
        """
        Extract text blocks from a pymupdf page, filtering out blocks that
        overlap with table regions.

        Returns:
            List of (y_position, text) tuples for non-table text blocks,
            sorted by vertical position.
        """
        text_blocks: list[tuple[float, str]] = []

        try:
            blocks = fitz_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)[
                "blocks"
            ]
        except Exception as e:
            log.warning(f"[PDF] fitz text extraction failed: {e}")
            # Fallback to simple text extraction
            plain = fitz_page.get_text("text")
            if plain.strip():
                return [(0.0, plain)]
            return []

        for block in blocks:
            if block.get("type") != 0:  # 0 = text block
                continue

            block_bbox = (
                block["bbox"][0],
                block["bbox"][1],
                block["bbox"][2],
                block["bbox"][3],
            )

            # Check if this block overlaps with any table region
            overlaps_table = any(
                _bboxes_overlap(block_bbox, tr, threshold=0.5)
                for tr in table_regions
            )
            if overlaps_table:
                continue

            # Reassemble text from lines/spans in this block
            block_text_parts = []
            for line in block.get("lines", []):
                line_text = ""
                for span in line.get("spans", []):
                    line_text += span.get("text", "")
                if line_text.strip():
                    block_text_parts.append(line_text)

            if block_text_parts:
                text_blocks.append(
                    (block["bbox"][1], "\n".join(block_text_parts))  # y0 position
                )

        text_blocks.sort(key=lambda x: x[0])
        return text_blocks

    def _combine_text_and_tables(
        self,
        text_blocks: list[tuple[float, str]],
        table_regions: list[tuple],
        table_markdowns: list[str],
    ) -> str:
        """
        Interleave non-table text and table Markdown blocks in vertical
        page order.
        """
        # Build a unified list of (y_position, content) entries
        entries: list[tuple[float, str]] = list(text_blocks)

        for bbox, md in zip(table_regions, table_markdowns):
            y_pos = bbox[1]  # y0 of table
            entries.append((y_pos, f"\n\n[TABLE]\n{md}\n[/TABLE]\n\n"))

        entries.sort(key=lambda x: x[0])
        return "\n".join(content for _, content in entries)

    def _extract_images(
        self, fitz_doc, fitz_page, page_number: int
    ) -> list[ExtractedImage]:
        """Extract embedded images from a pymupdf page."""
        images: list[ExtractedImage] = []

        try:
            image_list = fitz_page.get_images(full=True)
        except Exception as e:
            log.warning(f"[PDF] Image enumeration failed on page {page_number}: {e}")
            return []

        for img_idx, img_info in enumerate(image_list):
            try:
                xref = img_info[0]
                pix = fitz.Pixmap(fitz_doc, xref)

                # Convert CMYK to RGB if needed
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                width, height = pix.width, pix.height

                # Skip tiny/decorative images
                if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
                    continue

                # Convert to PNG bytes
                png_bytes = pix.tobytes("png")

                # Skip oversized images
                if len(png_bytes) > MAX_IMAGE_SIZE_BYTES:
                    log.warning(
                        f"[PDF] Skipping oversized image on page {page_number} "
                        f"({len(png_bytes)} bytes > {MAX_IMAGE_SIZE_BYTES})"
                    )
                    continue

                # Try to get image bbox on page (approximate)
                try:
                    img_rects = fitz_page.get_image_rects(xref)
                    bbox = tuple(img_rects[0]) if img_rects else (0, 0, width, height)
                except Exception:
                    bbox = (0, 0, width, height)

                images.append(
                    ExtractedImage(
                        image_bytes=png_bytes,
                        page_number=page_number,
                        bbox=bbox,
                        image_index=img_idx,
                        width=width,
                        height=height,
                    )
                )
            except Exception as e:
                log.warning(
                    f"[PDF] Failed to extract image {img_idx} on page {page_number}: {e}"
                )
                continue

        return images

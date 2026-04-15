import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import fitz
import pdfplumber
from langchain_core.documents import Document

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])


@dataclass
class PageImage:
    image_id: str
    top_norm: float
    width: float
    height: float
    png_base64: str


def _strip_code_fence_wrappers(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    return cleaned


def _normalize_description_text(value: Any) -> str:
    cleaned = str(value).strip() if value is not None else ""
    if not cleaned:
        return ""

    cleaned = _strip_code_fence_wrappers(cleaned).strip()
    if not cleaned:
        return ""

    # Handle quoted JSON scalar responses for single-image cases.
    if len(cleaned) >= 2 and cleaned[0] == '"' and cleaned[-1] == '"':
        try:
            decoded = json.loads(cleaned)
            if isinstance(decoded, str):
                cleaned = decoded.strip()
        except Exception:
            pass

    invalid_markers = {
        "```",
        "```json",
        "json",
        "[]",
        "[",
        "]",
        "{}",
        "{",
        "}",
        "null",
        "none",
    }
    if cleaned.lower() in invalid_markers:
        return ""

    return cleaned


def _extract_json_array(text: str) -> list[str]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return [_normalize_description_text(item) for item in parsed]
        if isinstance(parsed, dict) and isinstance(parsed.get("descriptions"), list):
            return [_normalize_description_text(item) for item in parsed["descriptions"]]
    except Exception:
        pass

    match = re.search(r"\[[\s\S]*\]", cleaned)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return [_normalize_description_text(item) for item in parsed]
        except Exception:
            pass

    return []


def _bbox_intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


def _table_to_markdown(rows: list[list[Any]]) -> str:
    if not rows:
        return ""

    normalized = []
    max_cols = 0
    for row in rows:
        normalized_row = ["" if cell is None else str(cell).replace("\n", " ").strip() for cell in row]
        max_cols = max(max_cols, len(normalized_row))
        normalized.append(normalized_row)

    if max_cols == 0:
        return ""

    for row in normalized:
        if len(row) < max_cols:
            row.extend([""] * (max_cols - len(row)))

    header = normalized[0]
    body = normalized[1:] if len(normalized) > 1 else []

    lines = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for row in body:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def _words_to_text(words: list[dict], tolerance: float = 3.0) -> list[tuple[float, str]]:
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (float(w.get("top", 0.0)), float(w.get("x0", 0.0))))
    lines: list[tuple[float, list[str]]] = []

    for w in sorted_words:
        top = float(w.get("top", 0.0))
        token = str(w.get("text", "")).strip()
        if not token:
            continue

        if not lines:
            lines.append((top, [token]))
            continue

        last_top, last_tokens = lines[-1]
        if abs(top - last_top) <= tolerance:
            last_tokens.append(token)
        else:
            lines.append((top, [token]))

    output: list[tuple[float, str]] = []
    for top, tokens in lines:
        text = " ".join(tokens).strip()
        if text:
            output.append((top, text))
    return output


class ComplexPDFLoader:
    def __init__(
        self,
        file_path: str,
        image_describer=None,
        max_images_per_page: int = 6,
        max_images_per_document: int = 80,
    ):
        self.file_path = file_path
        self.image_describer = image_describer
        self.max_images_per_page = max_images_per_page
        self.max_images_per_document = max_images_per_document

    def _extract_page_images(self, page: fitz.Page, page_number: int) -> list[PageImage]:
        image_entries = []
        for idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            rects = page.get_image_rects(xref)
            for r_idx, rect in enumerate(rects):
                width = max(0.0, rect.width)
                height = max(0.0, rect.height)
                area = width * height
                if width < 64 or height < 64 or area < 10000:
                    continue

                image_entries.append((f"p{page_number}_i{idx}_{r_idx}", rect, area))

        image_entries.sort(key=lambda item: item[2], reverse=True)
        image_entries = image_entries[: self.max_images_per_page]

        page_height = max(1.0, float(page.rect.height))
        images: list[PageImage] = []

        for image_id, rect, _ in image_entries:
            pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(2, 2), alpha=False)
            png_bytes = pix.tobytes("png")
            images.append(
                PageImage(
                    image_id=image_id,
                    top_norm=max(0.0, min(1.0, float(rect.y0) / page_height)),
                    width=float(rect.width),
                    height=float(rect.height),
                    png_base64=base64.b64encode(png_bytes).decode("utf-8"),
                )
            )

        return images

    def load(self) -> list[Document]:
        docs: list[Document] = []

        with pdfplumber.open(self.file_path) as plumber_pdf, fitz.open(self.file_path) as mupdf_pdf:
            total_pages = min(len(plumber_pdf.pages), len(mupdf_pdf))
            image_budget = self.max_images_per_document

            for page_index in range(total_pages):
                page_warnings: list[str] = []
                plumber_page = plumber_pdf.pages[page_index]
                mupdf_page = mupdf_pdf[page_index]

                page_height = max(1.0, float(plumber_page.height or 1.0))
                table_blocks: list[tuple[float, str]] = []
                table_bboxes: list[tuple[float, float, float, float]] = []

                try:
                    tables = plumber_page.find_tables()
                except Exception as e:
                    tables = []
                    page_warnings.append(f"page {page_index + 1}: table detection failed: {type(e).__name__}")

                for t_idx, table in enumerate(tables):
                    bbox = tuple(float(v) for v in table.bbox)
                    table_bboxes.append(bbox)
                    markdown = _table_to_markdown(table.extract() or [])
                    if markdown:
                        top_norm = max(0.0, min(1.0, bbox[1] / page_height))
                        table_blocks.append((top_norm, f"[Table {t_idx + 1} | Page {page_index + 1}]\n{markdown}"))

                words = plumber_page.extract_words(keep_blank_chars=False) or []
                filtered_words = []
                for w in words:
                    word_bbox = (
                        float(w.get("x0", 0.0)),
                        float(w.get("top", 0.0)),
                        float(w.get("x1", 0.0)),
                        float(w.get("bottom", 0.0)),
                    )
                    if any(_bbox_intersects(word_bbox, table_bbox) for table_bbox in table_bboxes):
                        continue
                    filtered_words.append(w)

                text_blocks = []
                for top, text in _words_to_text(filtered_words):
                    top_norm = max(0.0, min(1.0, top / page_height))
                    text_blocks.append((top_norm, text))

                page_images: list[PageImage] = []
                try:
                    page_images = self._extract_page_images(mupdf_page, page_index + 1)
                except Exception as e:
                    page_warnings.append(f"page {page_index + 1}: image extraction failed: {type(e).__name__}")

                if image_budget <= 0:
                    page_images = []
                elif len(page_images) > image_budget:
                    page_images = page_images[:image_budget]

                image_budget -= len(page_images)

                image_blocks: list[tuple[float, str]] = []
                if page_images and self.image_describer is not None:
                    try:
                        descriptions = self.image_describer(page_number=page_index + 1, images=page_images)
                        for idx, image in enumerate(page_images):
                            desc = (descriptions[idx] if idx < len(descriptions) else "").strip()
                            if not desc:
                                desc = "Image content could not be described."
                            image_blocks.append(
                                (image.top_norm, f"[Figure {idx + 1} | Page {page_index + 1}]\n{desc}")
                            )
                    except Exception as e:
                        page_warnings.append(f"page {page_index + 1}: image description failed: {type(e).__name__}")
                elif page_images:
                    page_warnings.append(f"page {page_index + 1}: image descriptions skipped (no describer)")

                merged_blocks = text_blocks + table_blocks + image_blocks
                merged_blocks.sort(key=lambda item: item[0])
                page_content = "\n\n".join(block for _, block in merged_blocks if block and block.strip())

                docs.append(
                    Document(
                        page_content=page_content,
                        metadata={
                            "source": self.file_path,
                            "page": page_index,
                            "table_count": len(table_blocks),
                            "image_count": len(image_blocks),
                            "parse_warnings": page_warnings,
                        },
                    )
                )

        return docs


def describe_images_with_task_model(
    request: Any,
    user: Any,
    page_number: int,
    images: list[PageImage],
) -> list[str]:
    if request is None or user is None or not images:
        return []

    try:
        import asyncio

        from open_webui.utils.models import get_models_for_user
        from open_webui.utils.chat import generate_chat_completion
        from open_webui.utils.task import get_task_model_id

        def _guess_vision_model_id(models: dict) -> str | None:
            if not models:
                return None

            preferred_keywords = [
                "gpt-4o",
                "gemini",
                "claude",
                "vision",
                "multimodal",
            ]

            for model_id in sorted(models.keys()):
                model_id_lower = model_id.lower()
                if "embedding" in model_id_lower or "rerank" in model_id_lower:
                    continue
                if any(keyword in model_id_lower for keyword in preferred_keywords):
                    return model_id

            # Last resort: any non-embedding model
            for model_id in sorted(models.keys()):
                model_id_lower = model_id.lower()
                if "embedding" in model_id_lower or "rerank" in model_id_lower:
                    continue
                return model_id

            return None

        async def _run() -> list[str]:
            models = await get_models_for_user(request, user)
            task_model_id = get_task_model_id(
                model_id="",
                task_model=request.app.state.config.TASK_MODEL,
                task_model_external=request.app.state.config.TASK_MODEL_EXTERNAL.get(user.email),
                models=models,
            )
            if not task_model_id or task_model_id not in models:
                task_model_id = _guess_vision_model_id(models)
                if task_model_id:
                    log.info(
                        "PDF image description fallback model selected for %s: %s",
                        user.email,
                        task_model_id,
                    )
                else:
                    log.warning(
                        "PDF image description skipped for %s: no candidate model available",
                        user.email,
                    )
                    return []

            model_info = models.get(task_model_id, {})
            vision_capable = (
                model_info.get("info", {})
                .get("meta", {})
                .get("capabilities", {})
                .get("vision")
            )
            if vision_capable is False:
                model_id_lower = task_model_id.lower()
                likely_vision = any(
                    keyword in model_id_lower for keyword in ["gpt-4o", "gemini", "claude", "vision"]
                )
                if not likely_vision:
                    log.warning(
                        "PDF image description skipped for %s: selected model not vision-capable (%s)",
                        user.email,
                        task_model_id,
                    )
                    return []

            prompt = (
                "For each image, provide a very descriptive, detailed, and accurate account including every important and minor detail visible. "
                "Describe all elements, objects, people, backgrounds, colors, shapes, layout, and any text or annotations present on the image. "
                "Be exhaustive and ensure no significant visual detail is omitted. "
                "Return ONLY a JSON array of strings describing the images in the same order as provided."
            )
       
            content = [{"type": "text", "text": f"Page {page_number}. {prompt}"}]
            for image in images:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image.png_base64}"},
                    }
                )

            payload = {
                "model": task_model_id,
                "messages": [{"role": "user", "content": content}],
                "stream": False,
                "metadata": {
                    "task": "pdf_image_description",
                    "page": page_number,
                },
            }

            log.info(
                "PDF image description request | user=%s | page=%s | model=%s | images=%s",
                user.email,
                page_number,
                task_model_id,
                len(images),
            )
            response = await generate_chat_completion(request, form_data=payload, user=user)
            response_text = (
                response.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                if isinstance(response, dict)
                else ""
            )
            parsed = _extract_json_array(response_text)
            if parsed and not any(desc for desc in parsed):
                parsed = []
            if not parsed and isinstance(response_text, str):
                fallback_text = _normalize_description_text(response_text)
                if fallback_text:
                    if len(images) == 1:
                        parsed = [fallback_text]
                    else:
                        lines = [
                            _normalize_description_text(line.strip("-* \t"))
                            for line in response_text.splitlines()
                            if line.strip()
                        ]
                        lines = [line for line in lines if line]
                        if lines:
                            parsed = lines[: len(images)]
            if not parsed:
                log.warning(
                    "PDF image description returned empty result | user=%s | page=%s | model=%s",
                    user.email,
                    page_number,
                    task_model_id,
                )
            return parsed

        return asyncio.run(_run())
    except Exception as e:
        log.warning("PDF image description failed on page %s: %s", page_number, e)
        return []

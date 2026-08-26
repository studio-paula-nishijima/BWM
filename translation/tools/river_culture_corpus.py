#!/usr/bin/env python3
"""Build and inspect the River Culture canonical passage corpus.

The PDF is intentionally an input, not a repository artifact.  This module
uses its existing text layer and coordinates; it never falls back to OCR.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

CORPUS_VERSION = "1.2.0"
TOKEN_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)
PAGE_NUMBER_RE = re.compile(r"^\s*(\d{1,4})\s*$")
HEADING_RE = re.compile(r"^(?:\d{1,2}(?:\.\d+)*\s+|[A-Z][A-Z\s,:;\-]{10,}$)")
FIGURE_CAPTION_RE = re.compile(r"^\s*(?:fig(?:ure)?\.?\s*\d+(?:\.\d+)*)\b", re.IGNORECASE)
TABLE_CAPTION_RE = re.compile(r"^\s*table\s+\d+(?:\.\d+)*\b", re.IGNORECASE)
BIBLIOGRAPHY_RE = re.compile(r"^\s*(?:bibliography|bibliographie|references)\b", re.IGNORECASE)
CONTENTS_HEADING_RE = re.compile(r"^\s*(?:contents|table of contents)\b", re.IGNORECASE)
CONTENTS_ENTRY_RE = re.compile(r"(?:\.{3,}|\s{3,})\s*\d{1,4}\s*$")
CHAPTER_BOUNDARY_RE = re.compile(r"^\s*(\d{1,2})(?:\.\d+)*\s+([A-Z][^\n]{3,})$")
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
PHOTO_CREDIT_RE = re.compile(r"\b(?:photo(?:graph)?|image)\s*:\s*\S+", re.IGNORECASE)
FRONT_MATTER_RE = re.compile(r"\b(?:ISBN(?:-1[03])?\s*[:#]?\s*[\dXx-]{8,}|doi\s*:\s*10\.\d{4,9}/|this (?:book|article) should be cited as|cover (?:design|photo)|design by|printed (?:in|on)|all rights reserved|creative commons)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Block:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    font_size: float
    lines: tuple[tuple[float, float, float, str], ...]

    @property
    def width(self) -> float:
        return self.x1 - self.x0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def normalise_text(text: str) -> str:
    """Conservatively join line wraps while retaining author wording."""
    # PDF text layers occasionally contain bell/backspace and other formatting
    # controls. Keep processing whitespace until after line joining, but never
    # let non-textual controls enter the canonical record.
    text = "".join(char for char in text if ord(char) >= 32 or char in "\t\n\r")
    text = text.replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def token_count(text: str) -> int:
    return len(TOKEN_RE.findall(text))


def block_text_and_font(raw_block: dict[str, Any]) -> tuple[str, float, tuple[tuple[float, float, float, str], ...]]:
    lines: list[str] = []
    sizes: list[float] = []
    coordinates: list[tuple[float, float, float, str]] = []
    for line in raw_block.get("lines", []):
        spans = line.get("spans", [])
        value = "".join(span.get("text", "") for span in spans)
        if value:
            lines.append(value)
            x0, y0, _x1, y1 = line["bbox"]
            coordinates.append((x0, y0, y1, value))
            sizes.extend(float(span.get("size", 0)) for span in spans)
    return "\n".join(lines), (statistics.median(sizes) if sizes else 0.0), tuple(coordinates)


def page_blocks(page: Any) -> list[Block]:
    """Get coordinate-bearing text blocks from a PyMuPDF page."""
    blocks: list[Block] = []
    for raw in page.get_text("dict", flags=11).get("blocks", []):
        if raw.get("type") != 0:
            continue
        text, font_size, lines = block_text_and_font(raw)
        if text.strip():
            x0, y0, x1, y1 = raw["bbox"]
            blocks.append(Block(x0, y0, x1, y1, text, font_size, lines))
    return blocks


def is_page_furniture(block: Block, height: float, settings: dict[str, Any]) -> bool:
    text = normalise_text(block.text)
    if PAGE_NUMBER_RE.fullmatch(text):
        return True
    # The observed running furniture occupies y=49--64.  Keep normal prose
    # outside that spatial band even if it repeats a title-like phrase.
    return block.y1 <= settings["header_bottom"] or block.y0 >= height - 35


def printed_page_number(blocks: Iterable[Block], height: float) -> int | None:
    candidates: list[int] = []
    for block in blocks:
        if block.y0 < 35 or block.y1 > height - 20:
            match = PAGE_NUMBER_RE.fullmatch(normalise_text(block.text))
            if match:
                candidates.append(int(match.group(1)))
        # This book combines its running title and printed page at the top.
        if block.y1 <= 72:
            match = re.search(r"\b(\d{1,4})\s*$", normalise_text(block.text))
            if match:
                candidates.append(int(match.group(1)))
    return candidates[-1] if candidates else None


def ordered_body_blocks(blocks: list[Block], width: float, height: float,
                        settings: dict[str, Any]) -> tuple[list[Block], list[str]]:
    body = [b for b in blocks if not is_page_furniture(b, height, settings)
            and b.y1 >= settings["body_top"] and b.y0 <= settings["body_bottom"]
            and normalise_text(b.text)]
    warnings: list[str] = []
    if not body:
        return [], ["no_body_text"]
    wide = [b for b in body if b.width >= width * settings["wide_block_fraction"]]
    narrow = [b for b in body if b not in wide]
    if narrow and not any(b.x0 < width * .48 for b in narrow):
        warnings.append("no_left_column_blocks")
    if narrow and not any(b.x1 > width * .52 for b in narrow):
        warnings.append("no_right_column_blocks")

    # A wide block starts a full-width band.  Within each following band read
    # all left-column material before its right-column material.  This matches
    # the observed PDF blocks and leaves genuinely unusual pages flagged.
    result: list[Block] = []
    anchors = sorted(wide, key=lambda b: (b.y0, b.x0))
    start = settings["body_top"]
    for anchor in anchors:
        band = [b for b in narrow if b.y0 >= start and b.y0 < anchor.y0]
        left = sorted((b for b in band if (b.x0 + b.x1) / 2 < width / 2), key=lambda b: (b.y0, b.x0))
        right = sorted((b for b in band if b not in left), key=lambda b: (b.y0, b.x0))
        result.extend(left)
        result.extend(right)
        result.append(anchor)
        start = anchor.y1
    band = [b for b in narrow if b.y0 >= start]
    left = sorted((b for b in band if (b.x0 + b.x1) / 2 < width / 2), key=lambda b: (b.y0, b.x0))
    right = sorted((b for b in band if b not in left), key=lambda b: (b.y0, b.x0))
    result.extend(left)
    result.extend(right)
    if len(body) >= 12 or len(wide) >= 3:
        warnings.append("complex_layout")
    return result, warnings


def split_block_into_passages(block: Block) -> list[str]:
    """Use visible vertical gaps and indentation as paragraph boundaries."""
    if not block.lines:
        return [normalise_text(block.text)]
    line_heights = [y1 - y0 for _x0, y0, y1, _text in block.lines]
    line_height = statistics.median(line_heights)
    parts: list[str] = []
    current: list[str] = []
    previous_y1: float | None = None
    baseline_x = min(x0 for x0, _y0, _y1, _text in block.lines)
    for x0, y0, y1, line in block.lines:
        # Paragraph starts are visibly separated or indented in the PDF.  The
        # threshold is intentionally cautious so uncertain text remains joined.
        gap = 0 if previous_y1 is None else y0 - previous_y1
        indented = x0 - baseline_x > max(8, line_height * .7)
        if current and (gap > line_height * .55 or (indented and gap > line_height * .12)):
            parts.append(normalise_text("\n".join(current)))
            current = []
        current.append(line)
        previous_y1 = y1
    if current:
        parts.append(normalise_text("\n".join(current)))
    return [part for part in parts if token_count(part) >= 3]


def heading(text: str, font_size: float) -> bool:
    compact = normalise_text(text)
    return bool(HEADING_RE.match(compact)) or (font_size >= 13 and token_count(compact) <= 24)


def credible_chapter_boundary(text: str, font_size: float) -> bool:
    """Avoid mistaking reference continuations such as ``95 pp.`` for chapters."""
    match = CHAPTER_BOUNDARY_RE.match(normalise_text(text))
    return bool(match and (font_size >= 13 or "." in match.group(0).split()[0]))


def contents_material(block: Block) -> bool:
    text = normalise_text(block.text)
    lines = [normalise_text(line) for _x0, _y0, _y1, line in block.lines if normalise_text(line)]
    entries = sum(bool(CONTENTS_ENTRY_RE.search(line)) for line in lines)
    return bool(CONTENTS_HEADING_RE.match(text) or CONTENTS_ENTRY_RE.search(text) or (len(lines) >= 3 and entries >= 2))


def image_regions(page: Any) -> list[tuple[float, float, float, float]]:
    """Return actual image rectangles when the PDF exposes them; no OCR guesswork."""
    regions: list[tuple[float, float, float, float]] = []
    try:
        for image in page.get_images(full=True):
            for rect in page.get_image_rects(image[0]):
                regions.append((float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)))
    except Exception:
        pass
    return regions


def image_associated_caption(block: Block, regions: list[tuple[float, float, float, float]]) -> str | None:
    """Classify only short labels/credits spatially attached to a real image."""
    text = normalise_text(block.text)
    if not regions:
        return None
    near_image = any(
        block.x1 >= x0 - 24 and block.x0 <= x1 + 24 and block.y1 >= y0 - 36 and block.y0 <= y1 + 42
        for x0, y0, x1, y1 in regions
    )
    if not near_image:
        return None
    if PHOTO_CREDIT_RE.search(text):
        return "photo_credit"
    if token_count(text) <= 18 and block.font_size <= 11 and not re.search(r"[.!?]\s*$", text):
        return "image_caption"
    return None


def overlaps_table_region(block: Block, regions: list[tuple[float, float, float, float]]) -> bool:
    """Return true only for a materially overlapping detected table rectangle."""
    for x0, y0, x1, y1 in regions:
        overlap_width = max(0.0, min(block.x1, x1) - max(block.x0, x0))
        overlap_height = max(0.0, min(block.y1, y1) - max(block.y0, y0))
        if overlap_width * overlap_height >= min(block.width * (block.y1 - block.y0), (x1 - x0) * (y1 - y0)) * .2:
            return True
    return False


def table_regions(page: Any, has_numbered_caption: bool) -> list[tuple[float, float, float, float]]:
    """Use PyMuPDF's table finder when this PDF/page exposes table geometry."""
    if not has_numbered_caption:
        return []
    try:
        finder = getattr(page, "find_tables", None)
        if finder is None:
            return []
        found = finder()
        return [tuple(map(float, table.bbox)) for table in found.tables]
    except Exception:
        # The numbered-caption fallback below remains deliberately conservative
        # for pages whose vector/text layout cannot be recognised as a table.
        return []


def content_type(block: Block, *, table_active: bool, bibliography_active: bool,
                 regions: list[tuple[float, float, float, float]], settings: dict[str, bool],
                 contents_active: bool = False, images: list[tuple[float, float, float, float]] | None = None) -> tuple[str | None, bool, bool]:
    """Classify only high-confidence non-prose units for retrieval exclusion."""
    text = normalise_text(block.text)
    if bibliography_active and credible_chapter_boundary(text, block.font_size):
        bibliography_active = False
    if contents_active and credible_chapter_boundary(text, block.font_size):
        contents_active = False
    if settings.get("exclude_contents", True) and (contents_active or contents_material(block)):
        return "contents", table_active, bibliography_active
    if settings.get("exclude_front_matter", True) and FRONT_MATTER_RE.search(text):
        return "front_matter", table_active, bibliography_active
    if settings["exclude_bibliography"] and BIBLIOGRAPHY_RE.match(text):
        return "bibliography", table_active, True
    if bibliography_active and settings["exclude_bibliography"]:
        return "bibliography", table_active, bibliography_active
    if settings["exclude_figure_captions"] and FIGURE_CAPTION_RE.match(text):
        return "figure_caption", table_active, bibliography_active
    image_kind = image_associated_caption(block, images or [])
    if image_kind and settings.get("exclude_image_captions", True):
        return image_kind, table_active, bibliography_active
    if settings["exclude_table_bodies"] and overlaps_table_region(block, regions):
        return "table_content", table_active, bibliography_active
    if settings["exclude_table_captions"] and TABLE_CAPTION_RE.match(text):
        # When PyMuPDF cannot identify a table rectangle, the numbered caption
        # is the conservative fallback boundary for its following text blocks.
        return "table_caption", not bool(regions), bibliography_active
    # A numbered table caption is the strongest fallback boundary available
    # in this PDF. It is used only where table geometry was unavailable.
    if table_active and settings["exclude_table_bodies"]:
        return "table_content", table_active, bibliography_active
    return None, table_active, bibliography_active


def make_passages(pdf_path: Path, settings: dict[str, Any],
                  filter_settings: dict[str, bool]) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required; install requirements_translation.txt") from exc
    document = fitz.open(pdf_path)
    passages: list[dict[str, Any]] = []
    suspicious: dict[int, list[str]] = {}
    excluded_units: list[dict[str, Any]] = []
    current_chapter: str | None = None
    current_section: str | None = None
    bibliography_active = False
    contents_active = False
    for page_index, page in enumerate(document):
        raw_blocks = page_blocks(page)
        ordered, warnings = ordered_body_blocks(raw_blocks, page.rect.width, page.rect.height, settings)
        if warnings:
            suspicious[page_index + 1] = warnings
        printed_page = printed_page_number(raw_blocks, page.rect.height)
        ordinal = 0
        has_numbered_caption = any(TABLE_CAPTION_RE.match(normalise_text(block.text)) for block in ordered)
        regions = table_regions(page, has_numbered_caption)
        images = image_regions(page)
        table_active = False
        for block_ordinal, block in enumerate(ordered, start=1):
            if contents_active and credible_chapter_boundary(normalise_text(block.text), block.font_size):
                contents_active = False
            kind, table_active, bibliography_active = content_type(
                block, table_active=table_active, bibliography_active=bibliography_active,
                regions=regions, settings=filter_settings, contents_active=contents_active, images=images)
            if kind == "contents":
                contents_active = True
            source_ids: list[str] = []
            excluded_by_kind: dict[str, list[tuple[str, str]]] = {}
            for text in split_block_into_passages(block):
                ordinal += 1
                passage_id = f"rc_pdf{page_index + 1:03d}_{ordinal:03d}"
                source_ids.append(passage_id)
                unit_kind = kind
                # A bibliography heading can share a PyMuPDF block with the
                # final prose paragraph before it. Classify from the heading
                # passage forward, retaining that preceding prose.
                if unit_kind is None and filter_settings["exclude_bibliography"]:
                    if bibliography_active and credible_chapter_boundary(text, block.font_size):
                        bibliography_active = False
                    if BIBLIOGRAPHY_RE.match(text):
                        bibliography_active, unit_kind = True, "bibliography"
                    elif bibliography_active:
                        unit_kind = "bibliography"
                if unit_kind:
                    excluded_by_kind.setdefault(unit_kind, []).append((passage_id, text))
                    continue
                if heading(text, block.font_size):
                    if re.match(r"^\d+\s", text):
                        current_chapter, current_section = text, None
                    else:
                        current_section = text
                passages.append({
                    "id": passage_id,
                    "pdf_page": page_index + 1,
                    "printed_page": printed_page,
                    "chapter": current_chapter,
                    "section": current_section,
                    "text": text,
                    "source_bbox": [round(block.x0, 1), round(block.y0, 1), round(block.x1, 1), round(block.y1, 1)],
                })
            for excluded_kind, entries in excluded_by_kind.items():
                excluded_units.append({
                    "id": f"rc_pdf{page_index + 1:03d}_block{block_ordinal:03d}_{excluded_kind}",
                    "content_type": excluded_kind,
                    "exclusion_reason": excluded_kind,
                    "pdf_page": page_index + 1,
                    "printed_page": printed_page,
                    "source_passage_ids": [passage_id for passage_id, _text in entries],
                    "source_bbox": [round(block.x0, 1), round(block.y0, 1), round(block.x1, 1), round(block.y1, 1)],
                    "text": "\n".join(text for _passage_id, text in entries),
                })
    metadata = {"total_pdf_pages": len(document), "suspicious_pages": suspicious}
    document.close()
    return passages, metadata, excluded_units


def passage_eligibility(passage: dict[str, Any]) -> dict[str, Any]:
    """Describe quotation suitability without changing the canonical passage."""
    text = passage["text"]
    categories = ["substantive_prose"]
    reasons: list[str] = []
    flags: list[str] = []
    is_heading = heading(text, 0)
    lower = text.casefold()
    if is_heading:
        categories = ["isolated_heading"]
        reasons.append("heading_not_standalone_anchor")
    if re.search(r"\b(?:acknowledg(?:e)?ments?)\b", lower):
        categories.append("acknowledgement")
        reasons.append("acknowledgement_not_anchor")
    if re.search(r"\b(?:about the author|biography|biographical)\b", lower):
        categories.append("author_biography")
        reasons.append("biography_not_anchor")
    if re.search(r"\b(?:author|affiliation|university|department)\b", lower) and token_count(text) < 35:
        categories.append("author_affiliation_metadata")
        reasons.append("metadata_not_anchor")
    if URL_RE.search(text):
        categories.append("url_or_source_credit")
        flags.append("contains_url")
    if "�" in text:
        categories.append("replacement_glyph_contamination")
        reasons.append("replacement_glyph")
    if re.search(r"(?:\b\d{4}[a-z]?\b.*){3,}|\b(?:ed\.|pp\.|vol\.)\b", text, re.IGNORECASE):
        categories.append("suspicious_reference_like")
        flags.append("reference_like")
    numbers = len(re.findall(r"\d+(?:[.,]\d+)?", text))
    if numbers >= 8 or numbers / max(token_count(text), 1) > .28:
        categories.append("dense_numerical_material")
        flags.append("dense_numerical")
    if re.match(r"^[a-z]", text):
        flags.append("fragmentary_start")
    if token_count(text) >= 6 and not re.search(r"[.!?…:]$", text):
        flags.append("fragmentary_end")
    bbox = passage.get("source_bbox", [])
    if len(bbox) == 4 and bbox[3] - bbox[1] < 9:
        flags.append("suspicious_layout")
    anchor = not reasons
    return {
        "source_passage_id": passage["id"],
        "eligible_as_relevance_anchor": anchor,
        "eligible_as_surrounding_context": "replacement_glyph" not in reasons,
        "content_categories": sorted(set(categories)),
        "eligibility_reasons": sorted(set(reasons)),
        "layout_flags": sorted(set(flags)),
    }


def make_chunks(passages: list[dict[str, Any]], config: dict[str, int]) -> list[dict[str, Any]]:
    target, minimum, maximum = (config[k] for k in ("target_tokens", "minimum_tokens", "maximum_tokens"))
    overlap = config["overlap_passages"]
    if not 0 < minimum <= target <= maximum or overlap < 0:
        raise ValueError("invalid chunking configuration")
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(passages):
        included: list[dict[str, Any]] = []
        size = 0
        cursor = start
        while cursor < len(passages):
            candidate = passages[cursor]
            count = token_count(candidate["text"])
            if included and size + count > maximum:
                break
            included.append(candidate)
            size += count
            cursor += 1
            if size >= target:
                break
        # Do not loop forever when a short passage precedes an oversized one:
        # preserve the boundary and report its size instead of splitting prose.
        ids = [p["id"] for p in included]
        chunks.append({
            "id": f"rc_chunk_{len(chunks) + 1:05d}",
            "passage_ids": ids,
            "pdf_pages": sorted({p["pdf_page"] for p in included}),
            "printed_pages": sorted({p["printed_page"] for p in included if p["printed_page"] is not None}),
            "chapters": sorted({p["chapter"] for p in included if p["chapter"]}),
            "text": "\n\n".join(p["text"] for p in included),
            "token_count": size,
        })
        start = max(cursor - overlap, start + 1)
    return chunks


def distribution(records: list[dict[str, Any]], key: str = "text") -> dict[str, float | int]:
    values = [token_count(record[key]) for record in records]
    if not values:
        return {"count": 0}
    return {"count": len(values), "min": min(values), "median": statistics.median(values), "max": max(values),
            "mean": round(statistics.mean(values), 1)}


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build(config_path: Path, root: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    pdf_path = root / config["source_pdf"]
    passages, extraction, excluded_units = make_passages(pdf_path, config["layout"], config["content_filter"])
    chunks = make_chunks(passages, config["chunking"])
    eligibility = [passage_eligibility(passage) for passage in passages]
    source = {"filename": pdf_path.name, "sha256": sha256(pdf_path)}
    report = {"corpus_version": config.get("corpus_version", CORPUS_VERSION), "source": source,
              "extraction_settings": config["layout"], "chunking": config["chunking"], **extraction,
              "pages_processed": extraction["total_pdf_pages"], "empty_pages": [], "failed_pages": [],
              "canonical_passages": len(passages), "generated_chunks": len(chunks),
              "content_filter": config["content_filter"],
              "excluded_unit_counts": dict(Counter(unit["content_type"] for unit in excluded_units)),
              "excluded_units": len(excluded_units),
              "passage_token_distribution": distribution(passages), "chunk_token_distribution": distribution(chunks),
              "missing_printed_page_metadata": sum(p["printed_page"] is None for p in passages),
              "replacement_characters": sum(p["text"].count("�") for p in passages),
              "replacement_character_passage_ids": [p["id"] for p in passages if "�" in p["text"]],
              "eligibility": {
                  "anchors_eligible": sum(record["eligible_as_relevance_anchor"] for record in eligibility),
                  "anchors_ineligible": sum(not record["eligible_as_relevance_anchor"] for record in eligibility),
                  "context_eligible": sum(record["eligible_as_surrounding_context"] for record in eligibility),
                  "reason_counts": dict(Counter(reason for record in eligibility for reason in record["eligibility_reasons"])),
                  "category_counts": dict(Counter(category for record in eligibility for category in record["content_categories"])),
                  "layout_flag_counts": dict(Counter(flag for record in eligibility for flag in record["layout_flags"])),
              },
              "suspicious_short_passages": [p["id"] for p in passages if token_count(p["text"]) < 5],
              "suspicious_long_passages": [p["id"] for p in passages if token_count(p["text"]) > 800]}
    write_jsonl(root / config["passages_output"], passages)
    write_jsonl(root / config["chunks_output"], chunks)
    write_jsonl(root / config["excluded_units_output"], excluded_units)
    write_jsonl(root / config["eligibility_output"], eligibility)
    (root / config["report_output"]).write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return report


def inspect_jsonl(path: Path, identifier: str | None, sample: int | None) -> None:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    selected = [r for r in records if identifier is None or r["id"] == identifier]
    if sample:
        selected = random.Random(0).sample(records, min(sample, len(records)))
    if not selected:
        raise SystemExit("no matching record")
    for record in selected:
        print(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "chunks", "inspect"))
    parser.add_argument("--config", type=Path, default=Path("translation/configs/river_culture_corpus.json"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--id")
    parser.add_argument("--sample", type=int)
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build(args.config, args.root), indent=2, ensure_ascii=False, sort_keys=True))
    elif args.command == "chunks":
        if not args.input or not args.output:
            parser.error("chunks requires --input and --output")
        config = json.loads(args.config.read_text(encoding="utf-8"))
        write_jsonl(args.output, make_chunks(read_jsonl(args.input), config["chunking"]))
    else:
        if not args.input:
            parser.error("inspect requires --input")
        inspect_jsonl(args.input, args.id, args.sample)


if __name__ == "__main__":
    main()

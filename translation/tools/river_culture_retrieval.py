#!/usr/bin/env python3
"""Build, query, and evaluate the River Culture semantic chunk index.

This is intentionally retrieval only: returned chunks retain source wording and
provenance; no quotation selection, cleanup, or display shaping occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np

RETRIEVAL_VERSION = "1.0.0"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def slug(model_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", model_id).strip("_").lower()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def model_config(config: dict[str, Any], model_id: str) -> dict[str, Any]:
    for candidate in config["models"]:
        if candidate["id"] == model_id:
            return candidate
    raise ValueError(f"model is not listed in retrieval config: {model_id}")


def paths(config: dict[str, Any], root: Path, model_id: str) -> tuple[Path, Path]:
    name = slug(model_id)
    directory = root / config["index_directory"]
    return directory / f"river_culture_embeddings_{name}.npy", directory / f"river_culture_index_{name}.json"


def load_encoder(model_id: str) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Install requirements_river_culture_retrieval.txt before building or querying an index") from exc
    return SentenceTransformer(model_id)


def encode(encoder: Any, texts: list[str], prefix: str, batch_size: int) -> np.ndarray:
    values = [prefix + text for text in texts]
    embeddings = encoder.encode(values, batch_size=batch_size, show_progress_bar=True,
                                convert_to_numpy=True, normalize_embeddings=True)
    return np.asarray(embeddings, dtype=np.float32)


def layout_flags(chunk: dict[str, Any], report: dict[str, Any]) -> list[str]:
    suspicious = report.get("suspicious_pages", {})
    flags = {flag for page in chunk.get("pdf_pages", []) for flag in suspicious.get(str(page), [])}
    if not chunk.get("printed_pages"):
        flags.add("missing_printed_page")
    if "�" in chunk.get("text", ""):
        flags.add("replacement_glyph")
    return sorted(flags)


def metadata_for_chunks(chunks: list[dict[str, Any]], report: dict[str, Any]) -> list[dict[str, Any]]:
    metadata: list[dict[str, Any]] = []
    for ordinal, chunk in enumerate(chunks):
        metadata.append({
            "ordinal": ordinal, "id": chunk["id"], "passage_ids": chunk["passage_ids"],
            "pdf_pages": chunk.get("pdf_pages", []), "printed_pages": chunk.get("printed_pages", []),
            "chapters": chunk.get("chapters", []), "layout_flags": layout_flags(chunk, report),
            "replacement_glyph_count": chunk.get("text", "").count("�"), "text": chunk["text"],
        })
    return metadata


def process_rss_bytes() -> int | None:
    try:
        import psutil
        return psutil.Process().memory_info().rss
    except Exception:
        return None


def model_parameter_bytes(encoder: Any) -> int | None:
    """Model weights in memory; useful where the Hub cache path is variable."""
    try:
        return sum(parameter.numel() * parameter.element_size() for parameter in encoder.parameters())
    except Exception:
        return None


def build(config: dict[str, Any], root: Path, model_id: str) -> dict[str, Any]:
    chunks_path = root / config["chunks_input"]
    report_path = root / config["corpus_report_input"]
    chunks, report = read_jsonl(chunks_path), json.loads(report_path.read_text(encoding="utf-8"))
    candidate = model_config(config, model_id)
    encoder = load_encoder(model_id)
    started, before_rss = time.perf_counter(), process_rss_bytes()
    embeddings = encode(encoder, [chunk["text"] for chunk in chunks], candidate["passage_prefix"], config["batch_size"])
    build_seconds = time.perf_counter() - started
    embedding_path, metadata_path = paths(config, root, model_id)
    embedding_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(embedding_path, embeddings, allow_pickle=False)
    metadata = {
        "retrieval_version": config.get("retrieval_version", RETRIEVAL_VERSION), "model": candidate,
        "similarity": "normalized_dot_product_cosine", "embedding_dimension": int(embeddings.shape[1]),
        "chunk_count": len(chunks), "chunk_sha256": file_hash(chunks_path),
        "stage4_report_sha256": file_hash(report_path), "stage4_corpus_version": report.get("corpus_version"),
        "stage4_source": report.get("source"), "stage4_chunking": report.get("chunking"),
        "chunks": metadata_for_chunks(chunks, report),
        "performance": {"build_seconds": round(build_seconds, 3), "embedding_bytes": embedding_path.stat().st_size,
                        "rss_before_bytes": before_rss, "rss_after_bytes": process_rss_bytes(),
                        "model_parameter_bytes": model_parameter_bytes(encoder),
                        "platform": platform.platform()},
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


def load_index(config: dict[str, Any], root: Path, model_id: str) -> tuple[np.ndarray, dict[str, Any]]:
    embedding_path, metadata_path = paths(config, root, model_id)
    if not embedding_path.exists() or not metadata_path.exists():
        raise RuntimeError(f"index missing for {model_id}; run build first")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("model", {}).get("id") != model_id:
        raise RuntimeError("index model identity mismatch")
    if metadata.get("chunk_sha256") != file_hash(root / config["chunks_input"]):
        raise RuntimeError("index/chunk mismatch; rebuild after changing Stage 4 chunks")
    if metadata.get("stage4_report_sha256") != file_hash(root / config["corpus_report_input"]):
        raise RuntimeError("index/corpus-report mismatch; rebuild after changing Stage 4 report")
    embeddings = np.load(embedding_path, allow_pickle=False)
    if embeddings.shape != (metadata["chunk_count"], metadata["embedding_dimension"]):
        raise RuntimeError("index embedding shape mismatch")
    return embeddings, metadata


def grouped_regions(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Greedily group overlapping page ranges; raw ranking is never changed."""
    regions: list[dict[str, Any]] = []
    for result in raw:
        pages = set(result["pdf_pages"])
        for region in regions:
            if pages.intersection(region["pdf_pages"]):
                region["members"].append(result["id"])
                region["pdf_pages"].update(pages)
                break
        else:
            regions.append({"best_chunk_id": result["id"], "best_score": result["score"],
                            "members": [result["id"]], "pdf_pages": pages})
    return [{**region, "pdf_pages": sorted(region["pdf_pages"])} for region in regions]


def query(config: dict[str, Any], root: Path, model_id: str, text: str, top_k: int) -> dict[str, Any]:
    if not text.strip():
        raise ValueError("query text must not be empty")
    embeddings, metadata = load_index(config, root, model_id)
    encoder = load_encoder(model_id)
    started = time.perf_counter()
    vector = encode(encoder, [text], metadata["model"]["query_prefix"], config["batch_size"])[0]
    embedding_seconds = time.perf_counter() - started
    started = time.perf_counter()
    scores = embeddings @ vector
    positions = np.argsort(-scores, kind="stable")[:top_k]
    search_seconds = time.perf_counter() - started
    raw: list[dict[str, Any]] = []
    for rank, position in enumerate(positions, start=1):
        record = dict(metadata["chunks"][int(position)])
        record.update({"rank": rank, "score": float(scores[position])})
        raw.append(record)
    return {"query": text, "model": model_id, "similarity": metadata["similarity"], "raw_results": raw,
            "grouped_regions": grouped_regions(raw), "performance": {"query_embedding_seconds": round(embedding_seconds, 5),
                                                                           "search_seconds": round(search_seconds, 5)}}


def evaluate(config: dict[str, Any], root: Path, model_id: str, evaluation_path: Path, top_k: int) -> dict[str, Any]:
    cases = json.loads(evaluation_path.read_text(encoding="utf-8"))
    backend = model_config(config, model_id).get("embedding_backend", "multilingual")
    english_by_concept = {case["concept_id"]: case["query"] for case in cases if case.get("language") == "en"}
    results = []
    for case in cases:
        # Route A receives English produced by ASR translation; this controlled
        # text-set proxy uses the equivalent English evaluation question. Route
        # B receives the native-language query exactly as supplied.
        retrieval_query = english_by_concept.get(case.get("concept_id"), case["query"]) if backend == "english" else case["query"]
        results.append({**case, "retrieval_route": "route_a_translated_english" if backend == "english" else "route_b_native_multilingual",
                        "retrieval_query": retrieval_query,
                        "retrieval": query(config, root, model_id, retrieval_query, top_k)})
    scores = [item["retrieval"]["raw_results"][0]["score"] for item in results]
    return {"model": model_id, "embedding_backend": backend, "top_k": top_k, "cases": results,
            "top1_score_summary": {"min": min(scores), "max": max(scores), "mean": sum(scores) / len(scores)},
            "cross_language_consistency": cross_language_consistency(results),
            "evaluation_note": "Route A uses controlled equivalent English text, not an ASR translation-quality measurement." if backend == "english" else "Route B uses native-language text directly."}


def cross_language_consistency(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose page/region overlap for equivalent multilingual questions."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(result.get("concept_id", result["id"]), []).append(result)
    summaries: list[dict[str, Any]] = []
    for concept_id, members in grouped.items():
        if len(members) < 2:
            continue
        baseline = next((item for item in members if item.get("language") == "en"), members[0])
        baseline_pages = {page for item in baseline["retrieval"]["raw_results"] for page in item["pdf_pages"]}
        comparisons = []
        for item in members:
            pages = {page for candidate in item["retrieval"]["raw_results"] for page in candidate["pdf_pages"]}
            union = baseline_pages | pages
            comparisons.append({"language": item.get("language"), "top_chunk_id": item["retrieval"]["raw_results"][0]["id"],
                                "top_pdf_pages": item["retrieval"]["raw_results"][0]["pdf_pages"],
                                "top_k_page_jaccard_with_en": (len(baseline_pages & pages) / len(union)) if union else 1.0})
        summaries.append({"concept_id": concept_id, "baseline_language": baseline.get("language"), "comparisons": comparisons})
    return summaries


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "query", "evaluate"))
    parser.add_argument("--config", type=Path, default=Path("translation/configs/river_culture_retrieval.json"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--model", required=True)
    parser.add_argument("--text")
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--evaluation", type=Path, default=Path("translation/configs/river_culture_retrieval_evaluation.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    top_k = args.top_k or config["top_k"]
    if args.command == "build":
        result = build(config, args.root, args.model)
    elif args.command == "query":
        if not args.text:
            parser.error("query requires --text")
        result = query(config, args.root, args.model, args.text, top_k)
    else:
        result = evaluate(config, args.root, args.model, args.evaluation, top_k)
    rendered = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()

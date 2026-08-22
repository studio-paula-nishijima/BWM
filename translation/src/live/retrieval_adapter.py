"""Thin runtime adapter for the existing River Culture retrieval entry point."""
from __future__ import annotations

import importlib.util
import json
import numpy as np
from pathlib import Path
from typing import Any


class RiverCultureRetrievalAdapter:
    """Keep index/model lifetime here; Voice only sees query -> response text."""

    def __init__(self, repository_root: Path, *, config_path: Path | None = None,
                 model_id: str | None = None):
        self.repository_root = Path(repository_root)
        self.config_path = config_path or self.repository_root / "translation/configs/river_culture_retrieval.json"
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.model_id = model_id or self.config["models"][0]["id"]
        module_path = self.repository_root / "translation/tools/river_culture_retrieval.py"
        spec = importlib.util.spec_from_file_location("bwm_river_culture_retrieval_runtime", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("River Culture retrieval runtime is unavailable")
        self._module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self._module)
        self._runtime = None

    def prepare(self):
        """Load index and embedding model once; called only by retrieval worker."""
        embeddings, metadata = self._module.load_index(self.config, self.repository_root, self.model_id)
        self._runtime = embeddings, metadata, self._module.load_encoder(self.model_id)

    def retrieve(self, text: str) -> dict[str, Any]:
        """Return the existing top-ranked source text without shaping it."""
        if self._runtime is None: self.prepare()
        embeddings, metadata, encoder = self._runtime
        vector = self._module.encode(encoder, [text], metadata["model"]["query_prefix"], self.config["batch_size"])[0]
        positions = np.argsort(-(embeddings @ vector), kind="stable")[:self.config["top_k"]]
        raw = []
        for rank, position in enumerate(positions, 1):
            record = dict(metadata["chunks"][int(position)]); record.update({"rank": rank, "score": float((embeddings @ vector)[position])}); raw.append(record)
        result = {"query": text, "model": self.model_id, "similarity": metadata["similarity"], "raw_results": raw,
                  "grouped_regions": self._module.grouped_regions(raw)}
        response = raw[0].get("text", "") if raw else ""
        return {"ok": bool(response), "response_text": response, "metadata": result}

    def fallback_response(self, reason: str) -> dict[str, Any]:
        """Return the retrieval-owned configured River Culture response."""
        fallback = self.config.get("fallback_response", {})
        response = fallback.get("text", "")
        if not isinstance(response, str) or not response.strip():
            raise RuntimeError(f"configured fallback response is unavailable ({reason})")
        return {"ok": True, "response_text": response,
                "metadata": {"fallback": True, "reason": reason, "id": fallback.get("id")}}

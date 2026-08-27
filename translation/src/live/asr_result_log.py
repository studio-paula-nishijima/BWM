"""Best-effort append-only logging at the structured ASR result boundary."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path


class ASRResultLogger:
    """Persist completed result metadata without making the Voice path depend on I/O."""
    def __init__(self, path, *, emit=print):
        self.path = Path(path)
        self.emit = emit

    def __call__(self, item):
        result = item.get("result") or {}
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "capture_id": item.get("capture_id"),
            "capture_index": (item.get("metadata") or {}).get("capture", {}).get("capture_index"),
            "detector_profile": item.get("detector_profile"),
            "recognized_text": result.get("recognized_text", ""),
            "detected_language": result.get("detected_language"),
            "asr_status": item.get("status"),
            "inference_duration_seconds": item.get("inference_duration"),
            "timeout": item.get("status") == "timeout",
            "error": item.get("error"),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            self.emit(f"[ASR] result log failed: {exc}")

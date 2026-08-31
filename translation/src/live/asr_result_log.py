"""Best-effort append-only logging at the structured ASR result boundary."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


class ASRResultLogger:
    """Best-effort compact transcript persistence at the ASR result boundary."""
    def __init__(self, path, *, emit=print):
        self.path = Path(path)
        self.emit = emit

    def __call__(self, item):
        result = item.get("result") or {}
        text = result.get("recognized_text", "")
        if item.get("status") != "ok" or not isinstance(text, str) or not text.strip():
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not self.path.exists() or self.path.stat().st_size == 0
            with self.path.open("a", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                if write_header:
                    writer.writerow(("timestamp", "capture_id", "language", "text"))
                writer.writerow((datetime.now(timezone.utc).isoformat(), item.get("capture_id") or "",
                                 result.get("detected_language") or "", text))
        except Exception as exc:
            self.emit(f"[ASR] result log failed: {exc}")

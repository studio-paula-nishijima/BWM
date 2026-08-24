import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "translation" / "src")]

from live.retrieval_adapter import RiverCultureRetrievalAdapter


class RiverCultureRetrievalAdapterTests(unittest.TestCase):
    def test_existing_response_boundary_receives_presentation_text(self) -> None:
        adapter = RiverCultureRetrievalAdapter(ROOT)
        metadata = {
            "model": {"query_prefix": ""}, "similarity": "normalized_dot_product_cosine",
            "chunks": [{"id": "chunk", "text": "Floods shape rivers (Smith, 2018).",
                        "pdf_pages": [1], "passage_ids": ["p1"]}],
        }
        adapter._runtime = np.array([[1.0]], dtype=np.float32), metadata, object()
        original_encode = adapter._module.encode
        adapter._module.encode = lambda *_args: np.array([[1.0]], dtype=np.float32)
        try:
            result = adapter.retrieve("floods")
        finally:
            adapter._module.encode = original_encode
        self.assertEqual(result["response_text"], "Floods shape rivers.")
        self.assertEqual(result["metadata"]["raw_results"][0]["text"], "Floods shape rivers (Smith, 2018).")


if __name__ == "__main__":
    unittest.main()

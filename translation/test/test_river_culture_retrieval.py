import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE = Path(__file__).parents[1] / "tools" / "river_culture_retrieval.py"
SPEC = importlib.util.spec_from_file_location("river_culture_retrieval", MODULE)
retrieval = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = retrieval
SPEC.loader.exec_module(retrieval)


class RiverCultureRetrievalTests(unittest.TestCase):
    def test_grouped_regions_keeps_raw_neighbours_together(self) -> None:
        grouped = retrieval.grouped_regions([
            {"id": "a", "score": .8, "pdf_pages": [10, 11]},
            {"id": "b", "score": .7, "pdf_pages": [11, 12]},
            {"id": "c", "score": .6, "pdf_pages": [20]},
        ])
        self.assertEqual(grouped[0]["members"], ["a", "b"])
        self.assertEqual(grouped[0]["pdf_pages"], [10, 11, 12])
        self.assertEqual(grouped[1]["best_chunk_id"], "c")

    def test_cross_language_consistency_compares_equivalent_pages(self) -> None:
        def result(language, pages):
            return {"id": language, "concept_id": "feeling", "language": language,
                    "retrieval": {"raw_results": [{"id": language + "-chunk", "pdf_pages": pages}]}}
        summary = retrieval.cross_language_consistency([result("en", [1, 2]), result("de", [2, 3])])
        self.assertEqual(summary[0]["concept_id"], "feeling")
        self.assertAlmostEqual(summary[0]["comparisons"][1]["top_k_page_jaccard_with_en"], 1 / 3)

    def test_index_rejects_changed_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = root / "chunks.jsonl"
            report = root / "report.json"
            embeddings = root / "embeddings.npy"
            index = root / "index.json"
            chunks.write_text('{"id":"one"}\n', encoding="utf-8")
            report.write_text("{}", encoding="utf-8")
            retrieval.np.save(embeddings, retrieval.np.zeros((1, 2), dtype=retrieval.np.float32))
            index.write_text(json.dumps({"model": {"id": "test"}, "chunk_sha256": retrieval.file_hash(chunks),
                "stage4_report_sha256": retrieval.file_hash(report), "chunk_count": 1, "embedding_dimension": 2}), encoding="utf-8")
            config = {"chunks_input": "chunks.jsonl", "corpus_report_input": "report.json", "index_directory": "."}
            original_paths = retrieval.paths
            retrieval.paths = lambda _c, _r, _m: (embeddings, index)
            try:
                retrieval.load_index(config, root, "test")
                chunks.write_text('{"id":"changed"}\n', encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "index/chunk mismatch"):
                    retrieval.load_index(config, root, "test")
            finally:
                retrieval.paths = original_paths

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
    def test_presentation_cleanup_removes_only_supported_citations(self) -> None:
        canonical = "Floods shape rivers (Junk et al., 1989; Poff and Allan, 1997; Wantzen and Junk 2004, 2006) [12]."
        cleaned = retrieval.presentation_text(canonical)
        self.assertEqual(canonical, "Floods shape rivers (Junk et al., 1989; Poff and Allan, 1997; Wantzen and Junk 2004, 2006) [12].")
        self.assertEqual(cleaned, "Floods shape rivers.")

    def test_presentation_cleanup_retains_substantive_parentheses_and_years(self) -> None:
        canonical = "The river (which floods in spring) changed in 2018, as Maria explained."
        self.assertEqual(retrieval.presentation_text(canonical), canonical)

    def test_presentation_cleanup_is_configurable(self) -> None:
        canonical = "Floods shape rivers (Smith, 2018)."
        self.assertEqual(retrieval.presentation_text(canonical, {"remove_inline_citations": False}), canonical)

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

    def test_english_route_uses_equivalent_english_question(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evaluation = Path(directory) / "cases.json"
            evaluation.write_text(json.dumps([
                {"id": "en", "concept_id": "water", "language": "en", "query": "How is water?"},
                {"id": "de", "concept_id": "water", "language": "de", "query": "Wie ist Wasser?"},
            ]), encoding="utf-8")
            original_query = retrieval.query
            retrieval.query = lambda *_args: {"raw_results": [{"id": "x", "score": .5, "pdf_pages": [1]}]}
            try:
                result = retrieval.evaluate({"models": [{"id": "english", "embedding_backend": "english"}]}, Path(directory), "english", evaluation, 1)
            finally:
                retrieval.query = original_query
            self.assertEqual(result["cases"][1]["retrieval_query"], "How is water?")
            self.assertEqual(result["cases"][1]["retrieval_route"], "route_a_translated_english")

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

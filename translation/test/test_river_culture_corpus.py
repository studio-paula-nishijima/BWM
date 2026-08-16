import importlib.util
import sys
import unittest
from pathlib import Path


MODULE = Path(__file__).parents[1] / "tools" / "river_culture_corpus.py"
SPEC = importlib.util.spec_from_file_location("river_culture_corpus", MODULE)
corpus = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = corpus
SPEC.loader.exec_module(corpus)


class RiverCultureCorpusTests(unittest.TestCase):
    def test_normalise_text_joins_line_hyphenation(self) -> None:
        self.assertEqual(corpus.normalise_text("inter-\n national  river"), "international river")

    def test_chunks_preserve_passage_ids_and_overlap(self) -> None:
        passages = [{"id": f"p{i}", "pdf_page": i, "printed_page": i, "chapter": None,
                     "text": "word " * 100} for i in range(1, 4)]
        chunks = corpus.make_chunks(passages, {"target_tokens": 150, "minimum_tokens": 50,
                                                "maximum_tokens": 250, "overlap_passages": 1})
        self.assertEqual(chunks[0]["passage_ids"], ["p1", "p2"])
        self.assertEqual(chunks[1]["passage_ids"], ["p2", "p3"])

    def test_heading_does_not_misclassify_year_as_chapter(self) -> None:
        self.assertFalse(corpus.heading("2019 to draft another national policy", 10))


if __name__ == "__main__":
    unittest.main()

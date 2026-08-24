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
    FILTER = {"exclude_figure_captions": True, "exclude_table_captions": True,
              "exclude_table_bodies": True, "exclude_bibliography": True}

    @staticmethod
    def block(text: str, *, x0: float = 10, y0: float = 10, x1: float = 100, y1: float = 30) -> object:
        return corpus.Block(x0, y0, x1, y1, text, 10, ((x0, y0, y1, text),))

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

    def test_figure_and_table_caption_and_content_are_excluded(self) -> None:
        figure = self.block("Fig. 2.1 River channels in the floodplain")
        caption = self.block("Table 4.1 Seasonal river flow")
        cell = self.block("Dry season  18.4", y0=40, y1=60)
        self.assertEqual(corpus.content_type(figure, table_active=False, bibliography_active=False,
                                             regions=[], settings=self.FILTER)[0], "figure_caption")
        kind, table_active, _ = corpus.content_type(caption, table_active=False, bibliography_active=False,
                                                     regions=[], settings=self.FILTER)
        self.assertEqual(kind, "table_caption")
        self.assertTrue(table_active)
        self.assertEqual(corpus.content_type(cell, table_active=table_active, bibliography_active=False,
                                             regions=[], settings=self.FILTER)[0], "table_content")

    def test_table_geometry_keeps_nearby_prose_before_and_after_table(self) -> None:
        before = self.block("The river changes with the seasons.", y0=10, y1=30)
        cell = self.block("Wet season  42.0", y0=40, y1=60)
        after = self.block("Communities adapt their practices afterwards.", y0=70, y1=90)
        regions = [(5, 35, 105, 65)]
        self.assertIsNone(corpus.content_type(before, table_active=False, bibliography_active=False,
                                              regions=regions, settings=self.FILTER)[0])
        self.assertEqual(corpus.content_type(cell, table_active=False, bibliography_active=False,
                                             regions=regions, settings=self.FILTER)[0], "table_content")
        self.assertIsNone(corpus.content_type(after, table_active=False, bibliography_active=False,
                                              regions=regions, settings=self.FILTER)[0])

    def test_excluded_material_cannot_reach_chunks(self) -> None:
        prose = {"id": "p1", "pdf_page": 1, "printed_page": 1, "chapter": None,
                 "text": "Substantive prose about people and rivers. " * 20}
        chunks = corpus.make_chunks([prose], {"target_tokens": 50, "minimum_tokens": 20,
                                              "maximum_tokens": 200, "overlap_passages": 0})
        self.assertNotIn("Table 4.1", chunks[0]["text"])
        self.assertNotIn("Fig. 2.1", chunks[0]["text"])

    def test_bibliography_can_start_after_retained_prose(self) -> None:
        prose = self.block("River communities maintain local knowledge.")
        bibliography = self.block("Bibliography Smith, A. 2018. Rivers.")
        self.assertIsNone(corpus.content_type(prose, table_active=False, bibliography_active=False,
                                              regions=[], settings=self.FILTER)[0])
        self.assertEqual(corpus.content_type(bibliography, table_active=False, bibliography_active=False,
                                             regions=[], settings=self.FILTER)[0], "bibliography")


if __name__ == "__main__":
    unittest.main()

# River Culture corpus ingestion (Retrieval Stage 4)

`river_culture_corpus.py` builds a canonical JSONL passage corpus from the
local source PDF, then derives configurable retrieval chunks from it. Generated
JSONL and report files are ignored with the source PDF because they contain
copyrighted book text.

## Build

Create the Pi-aligned environment from `translation/requirements/requirements_translation.txt`, then run from the repository root:

```bash
python translation/tools/river_culture_corpus.py build
```

The source and outputs are configured in
`translation/configs/river_culture_corpus.json`. Regenerate an alternative
chunking layout without touching the PDF or canonical corpus with:

```bash
python translation/tools/river_culture_corpus.py chunks --input files/river_culture/river_culture_passages.jsonl --output files/river_culture/river_culture_chunks_alt.jsonl
```

Inspect deterministic examples without modifying any artifact:

```bash
python translation/tools/river_culture_corpus.py inspect --input files/river_culture/river_culture_passages.jsonl --id rc_pdf026_001
python translation/tools/river_culture_corpus.py inspect --input files/river_culture/river_culture_chunks.jsonl --sample 3
```

## Observed layout and rules

The 894-page A4 PDF has a usable text layer. Standard body pages use two
separate text blocks at roughly x=70--286 and x=296--512 (or x=85--301 and
x=310--526); the extractor reads all left blocks before right blocks within a
vertical band. It drops only spatially identified furniture: the running header
at y=49--64, bottom page furniture, and isolated page-number blocks. It does
not use a global title-string removal rule. Wide blocks establish full-width
bands and complex/table/image-heavy pages are reported for review.

Canonical records contain stable PDF-page/ordinal IDs, PDF and recovered
printed page numbers, current chapter/section when detected, source bounding
box, and cleaned passage text. Chunk records retain all source passage IDs and
page/chapter provenance. The JSON report records SHA-256, configuration,
counts, distributions, missing metadata, and suspicious pages/passages.

Known limitation: text within figures, tables, and some captions is retained
when present in the text layer but is not semantically classified. The report
marks complex layouts for manual review before using the corpus in Stage 5.
The embedded text layer also contains a small number of replacement characters
for unavailable glyph mappings; their count is reported so it can be assessed
before quotation use.

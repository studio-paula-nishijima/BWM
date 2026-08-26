# River Culture corpus ingestion (Retrieval Stage 4)

`river_culture_corpus.py` builds a canonical JSONL passage corpus from the
local source PDF, then derives configurable retrieval chunks from it. Generated
JSONL and report files are ignored with the source PDF because they contain
copyrighted book text.

## Build

Create the dedicated `river_culture_venv` from the small Stage 4 requirements
file, then run from the repository root. This intentionally does not alter the
Pi-aligned `translation_venv` used by the translation/event pipeline.

```bash
python3.11 -m venv --system-site-packages translation/river_culture_venv
translation/river_culture_venv/bin/python -m pip install -r translation/requirements/requirements_river_culture_corpus.txt
translation/river_culture_venv/bin/python translation/tools/river_culture_corpus.py build
```

On Windows, use:

```powershell
py -3.11 -m venv translation\river_culture_venv
.\translation\river_culture_venv\Scripts\python.exe -m pip install -r translation\requirements\requirements_river_culture_corpus.txt
.\translation\river_culture_venv\Scripts\python.exe translation\tools\river_culture_corpus.py build
```

On Raspberry Pi OS, preserve apt-provided GPIO availability with
`--system-site-packages` as shown above. The corpus tool itself has only the
PyMuPDF dependency.

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

Before canonical passage construction, the extractor classifies and excludes
contents listings, clear publication/source-credit apparatus, figure captions,
image descriptions and photo credits spatially adjacent to embedded images,
numbered table captions, and table content. It first uses
PyMuPDF's `find_tables()` rectangles on pages with a strict numbered table
caption, where available, to exclude intersecting
table blocks. On pages without a detected rectangle, a strict numbered `Table
N` caption starts a same-page fallback table-content boundary. This keeps prose
outside a detected table rectangle, including prose immediately after it.
Strict `Fig.`/`Figure` numbering identifies figure captions. Clearly headed
`Bibliography`, `Bibliographie`, and `References` sections are excluded until a
credible chapter boundary, rather than any line beginning with a number.
Contents is identified from its heading and entry layout, not a fixed PDF-page
range.

The ignored `river_culture_excluded_units.jsonl` is a compact audit trail with
each excluded block's classification, page, bounding box, and source-passage
ordinal(s). The report includes counts by exclusion type. Canonical passages
and their derived chunks therefore contain prose-only source material; there
is no second caption/table filter downstream.

Stable IDs remain PDF-page/ordinal IDs. Ordinals include excluded split units,
so unaffected passage IDs on the same page remain stable even when neighbouring
non-prose material is newly excluded.

The derived, ignored `river_culture_eligibility.jsonl` remains separate from
the canonical passage schema. Each record identifies its source passage,
anchor/context eligibility, content categories, explicit reasons, and layout
flags. Headings, acknowledgements, biographies, and metadata can remain
canonical but are normally unsuitable relevance anchors. Numerical prose stays
eligible by default with a quality flag. This prepares quotation selection but
does not rank, select, or expand quotations.

PDF C0 formatting debris and soft hyphens are removed before canonical text is
written; high-confidence wrapped-word hyphenation is joined. Authentic Unicode
is retained. Replacement glyphs are never guessed or silently removed: their
count and passage IDs are reported and they make a passage ineligible as an
anchor. The Oracle defensively removes non-semantic controls when displaying an
older corpus without mutating source records. Font selection is unchanged in
this stage; installed-display font coverage remains a deployment check.

Stage 2 is intentionally deferred: no sentence units, semantic quotation
ranking, contextual expansion, thresholds, or generated rewriting is present.

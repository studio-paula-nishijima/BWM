# River Culture semantic retrieval (Retrieval Stage 5)

This Stage 5 tool embeds Stage 4's derived chunks, not canonical passages.
It uses exact cosine search (normalized float32 embeddings plus a dot product),
which is simpler than an ANN dependency and is ample for 1,622 chunks.

## Pi setup and build

From `/home/raspi/BWM`, after Stage 4 has produced its ignored local JSONL:

```bash
python3.11 -m venv --system-site-packages translation/river_culture_venv
translation/river_culture_venv/bin/python -m pip install -r translation/requirements/requirements_river_culture_retrieval.txt

translation/river_culture_venv/bin/python translation/tools/river_culture_retrieval.py build \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

The first model use downloads and caches the model locally; later builds and
queries use that cache offline. The generated `.npy` embeddings and JSON index
metadata remain ignored because they derive from copyrighted source text.

## Query and evaluate

```bash
translation/river_culture_venv/bin/python translation/tools/river_culture_retrieval.py query \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --top-k 8 \
  --text "How does the water feel today?"

translation/river_culture_venv/bin/python translation/tools/river_culture_retrieval.py evaluate \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --top-k 8 \
  --output files/river_culture/river_culture_evaluation_multilingual_minilm.json
```

Query output preserves raw rank and score, complete chunk wording, chunk IDs,
ordered canonical `passage_ids`, page/chapter provenance, and propagated layout
flags. `grouped_regions` is an optional page-overlap grouping for human review;
it never alters `raw_results`.

## Model shortlist

The configuration intentionally evaluates a small shortlist:

1. `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: compact
   multilingual direct-retrieval baseline for English, German, and Italian.
2. `intfloat/multilingual-e5-small`: multilingual candidate using E5's
   `query:`/`passage:` prefixes; it is expected to cost more memory/storage.
3. `sentence-transformers/all-MiniLM-L6-v2`: compact English-only comparator,
   retained to quantify the practical cost of failing the multilingual need.

Direct multilingual retrieval is the baseline architecture. The editable set
contains equivalent English/German/Italian questions and smaller PT-BR probes;
evaluation reports page-overlap consistency against each English query. Compare
human judgments and that consistency signal, then measure the selected model on
the Pi while Whisper is also running. Do not add upstream translation unless
these direct multilingual candidates prove inadequate.

## Reproducibility and safety

Index metadata records the SHA-256 of Stage 4 chunks/report, Stage 4 corpus
source and chunk settings, model identifier/prefixes, vector dimension, metric,
and build/resource measurements. Querying rejects a changed chunk/report file
or an inconsistent embedding shape. The tool deliberately does not apply score
thresholds, select display quotations, remove citations, or exclude suspicious
layout material.
